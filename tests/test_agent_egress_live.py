"""The live-Docker controls for #442's provider-only egress: what a LIVE agent
container, built exactly as `DockerBackend(egress=True)` builds it, can and
cannot reach on a real daemon. The fake CLI (`tests/test_egress.py`) proves
the argv and the lifecycle; only a real daemon can prove the network.

Run from inside the agent container (`docker exec`, inheriting the proxy env
the container was started with, as the real client does):

  provider   a request to `https://chatgpt.com/` through the proxy gets an
             HTTP response (any status: a reply from the provider's edge is
             reachability, which is the property).
  denial     a request through the proxy to `github.com` and to
             `raw.githubusercontent.com` gets the proxy's 403, and the proxy
             log records both as denied.
  isolation  a client that IGNORES the proxy has no way out: resolving
             `github.com` fails, and a direct TCP connection to a GitHub
             address fails with no route.

DNS is closed by the internal network itself: measured on the runner (Docker
29.8.2), an `--internal` network does not resolve external names even with
`--dns 8.8.8.8`. `--dns 0.0.0.0` is defence in depth. A DNS-server break could
therefore never break anything, so the resolution check's own negative control
maps the name in `/etc/hosts` instead: a real lookup that succeeds in the real
container.

`SKILLC_EGRESS_LIVE_BREAK` selects one negative control, each breaking exactly
one property, which must then FAIL to hold (strict xfail on that property's
own exception type, so an unrelated setup failure stays a hard failure):

    none            (default) every property holds.
    allow-all       the proxy also forwards github.com and
                    raw.githubusercontent.com: `denial` must fail.
    bridge-network  the agent is ALSO attached to the default bridge: the
                    direct-route half of `isolation` must fail.
    dns-hosts       github.com is mapped in the agent's /etc/hosts (no route
                    added): the name-resolution half of `isolation` must fail.

`provider` holds in every mode. Every container and network this file
creates is removed by `destroy()` in a `finally`.

LEAK SAFETY: no host path, address or container name is printed into an
assertion message.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT
from egress_diagnostics import describe_observation

from skillc import docker_backend as d
from skillc import egress as eg

LIVE_TEST_IMAGE = os.environ.get("SKILLC_LIVE_TEST_IMAGE", "python:3.12-slim")
BREAK_MODE = os.environ.get("SKILLC_EGRESS_LIVE_BREAK", "none")
_VALID_BREAK_MODES = ("none", "allow-all", "bridge-network", "dns-hosts")
if BREAK_MODE not in _VALID_BREAK_MODES:
    raise RuntimeError(f"SKILLC_EGRESS_LIVE_BREAK={BREAK_MODE!r} must be one of {_VALID_BREAK_MODES}")

#: A GitHub address for the direct-connect probe (github.com's own, resolved
#: on the runner's bridge network 2026-10-17). Reaching ANY outside address is
#: the failure; this one is simply the one a grader fetch would use.
GITHUB_ADDRESS = "140.82.112.3"


class _DenialFailed(Exception):
    """The proxy did NOT refuse GitHub. The only exception the `allow-all`
    xfail matches, so a setup failure (a plain `AssertionError`) can never be
    read as "the break worked"."""


class _IsolationFailed(Exception):
    """A proxy-ignoring client DID get a direct route out. The only exception
    the `bridge-network` xfail matches."""


class _ResolutionFailed(Exception):
    """A name DID resolve inside the agent. The only exception the
    `dns-hosts` xfail matches."""


def _require(condition: bool, error: type[Exception], message: str) -> None:
    if not condition:
        raise error(message)


_DOCKER_BIN_PRESENT = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(
        not _DOCKER_BIN_PRESENT or d.probe_daemon(["docker"]) is None,
        reason="no reachable Docker daemon in this environment (binary "
               + ("present" if _DOCKER_BIN_PRESENT else "absent")
               + ") - this test needs a real daemon for #442's provider-only egress evidence; "
                 "real-daemon execution is owed to the real-Docker runner (#315)",
    ),
]


def _image_available(image: str) -> bool:
    inspect = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=10, check=False)
    if inspect.returncode == 0:
        return True
    pull = subprocess.run(["docker", "pull", image], capture_output=True, timeout=120, check=False)
    return pull.returncode == 0


@pytest.fixture
def attempt() -> Iterator[tuple[d.DockerBackend, d._Handle]]:
    assert _image_available(LIVE_TEST_IMAGE), "the live test image could not be made available"
    hosts = (*eg.ALLOWED_HOSTS, "github.com", "raw.githubusercontent.com") if BREAK_MODE == "allow-all" \
        else eg.ALLOWED_HOSTS
    with tempfile.TemporaryDirectory() as tmp:
        backend = d.DockerBackend(image=LIVE_TEST_IMAGE, base_dir=Path(tmp), egress=True, egress_hosts=hosts,
                                  daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT)
        handle = backend.prepare(f"a-egress-live-{os.getpid()}")
        assert isinstance(handle, d._Handle)
        try:
            if BREAK_MODE == "bridge-network":
                joined = subprocess.run(["docker", "network", "connect", "bridge", handle.name],
                                        capture_output=True, timeout=30, check=False)
                assert joined.returncode == 0, "setup: could not attach the agent to bridge for the break"
            if BREAK_MODE == "dns-hosts":
                # A real lookup that succeeds inside the real container, with no
                # route added: the DNS property alone must fail.
                mapped = subprocess.run(["docker", "exec", "-u", "0", handle.name, "sh", "-c",
                                         f"echo '{GITHUB_ADDRESS} github.com' >> /etc/hosts"],
                                        capture_output=True, timeout=30, check=False)
                assert mapped.returncode == 0, "setup: could not map github.com for the break"
            yield backend, handle
        finally:
            backend.destroy(handle)


#: Runs in the agent container with its own interpreter. argv: probe, target.
_PROBE = r'''
import json, socket, sys, urllib.error, urllib.request
kind, target = sys.argv[1], sys.argv[2]
out = {}
if kind == "https":
    try:
        with urllib.request.urlopen(target, timeout=20) as r:
            out = {"result": "http", "status": r.status}
    except urllib.error.HTTPError as e:
        out = {"result": "http", "status": e.code}
    except Exception as e:
        out = {"result": "error", "error": type(e).__name__ + ": " + str(e)[:160]}
elif kind == "resolve":
    try:
        socket.getaddrinfo(target, 443)
        out = {"result": "resolved"}
    except Exception as e:
        out = {"result": "error", "error": type(e).__name__}
elif kind == "direct":
    try:
        socket.create_connection((target, 443), timeout=10).close()
        out = {"result": "connected"}
    except Exception as e:
        out = {"result": "error", "error": type(e).__name__ + ": " + str(e)[:160]}
print(json.dumps(out))
'''


def _probe(handle: d._Handle, kind: str, target: str, *, use_proxy: bool = True) -> dict[str, object]:
    """`docker exec` into the agent container: the env it was STARTED with
    (the proxy settings) applies, exactly as for the real client. With
    `use_proxy=False` the proxy variables are cleared for this one process,
    which is what a client that ignores them amounts to."""
    clear = [] if use_proxy else [arg for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy",
                                                   "http_proxy", "all_proxy") for arg in ("-e", f"{key}=")]
    done = subprocess.run(["docker", "exec", *clear, handle.name, "python3", "-c", _PROBE, kind, target],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, "setup: the in-container probe itself failed to run"
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert isinstance(result, dict)
    return result


def _observed(backend: d.DockerBackend, handle: d._Handle, results: dict[str, dict[str, object]]) -> str:
    """#460: what was actually seen, for a failure message. Read BEFORE any
    `_require`, because `destroy()` removes the proxy and its log."""
    return describe_observation(results, backend.egress_log(handle))


def test_provider_is_reachable_through_the_proxy(attempt: tuple[d.DockerBackend, d._Handle]) -> None:
    backend, handle = attempt
    result = _probe(handle, "https", "https://chatgpt.com/")
    assert result["result"] == "http", f"the provider was not reachable through the proxy: {result.get('error')}"
    log = backend.egress_log(handle)
    assert log is not None and "chatgpt.com:443" in eg.summarize_log(log)["allowed"]  # type: ignore[operator]


#: Sleeps before `asyncio.run(serve())`, i.e. before the bind: a proxy slower
#: to start than everything else in `prepare()`. #460's red case.
_SLOW_START_DELAY_SECONDS = 10
_SLOW_START_ANCHOR = "\n    asyncio.run(serve())\n"


def test_prepare_returns_only_once_the_proxy_listens(monkeypatch: pytest.MonkeyPatch) -> None:
    """#460: `prepare()` must not hand back an attempt whose proxy is not yet
    listening. Without a readiness wait, the first CONNECT is refused (Errno
    111) - in a live attempt, an unusable start counted against tolerance.

    The probe asks for a name no mode ever allowlists, so the only possible
    "ready" answer is the proxy's OWN 403: no provider, DNS or upstream is
    involved, and an outage elsewhere cannot fail (or pass) this test. The
    10 s delay outlasts the rest of prepare() by a wide margin (measured on
    kyle19: the pre-fix probe fails about 2 s in)."""
    assert _image_available(LIVE_TEST_IMAGE), "the live test image could not be made available"
    assert eg.PROXY_SOURCE.count(_SLOW_START_ANCHOR) == 1, "setup: the slow-start anchor moved"
    monkeypatch.setattr(eg, "PROXY_SOURCE", eg.PROXY_SOURCE.replace(
        _SLOW_START_ANCHOR, f"\n    time.sleep({_SLOW_START_DELAY_SECONDS})\n    asyncio.run(serve())\n"))
    with tempfile.TemporaryDirectory() as tmp:
        backend = d.DockerBackend(image=LIVE_TEST_IMAGE, base_dir=Path(tmp), egress=True,
                                  daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT)
        handle = backend.prepare(f"a-egress-slow-{os.getpid()}")
        assert isinstance(handle, d._Handle)
        try:
            result = _probe(handle, "https", "https://never-allowlisted.invalid/")
            answered = result["result"] == "error" and "403" in str(result.get("error"))
            assert answered, ("the first request after prepare() got no answer from the proxy: "
                              + _observed(backend, handle, {"never-allowlisted.invalid": result}))
        finally:
            backend.destroy(handle)


@pytest.mark.xfail(BREAK_MODE == "allow-all", raises=_DenialFailed, strict=True,
                   reason="allow-all widens the proxy to GitHub, so the denial must fail")
def test_the_proxy_denies_github(attempt: tuple[d.DockerBackend, d._Handle]) -> None:
    backend, handle = attempt
    targets = ("https://github.com/", "https://raw.githubusercontent.com/cooneycw/skillc/main/README.md")
    results = {target: _probe(handle, "https", target) for target in targets}
    refused = [t for t, r in results.items() if r["result"] == "error" and "403" in str(r.get("error"))]
    seen = _observed(backend, handle, results)  # before ANY assertion: destroy() takes the log with it (#460)
    if BREAK_MODE == "allow-all":
        # The break itself, shown first as a hard assertion: GitHub really
        # answered through the widened proxy. Only then can the xfail below
        # come from the property failing for this reason.
        assert all(r["result"] == "http" for r in results.values()), f"setup: allow-all did not reach GitHub - observed: {seen}"
    _require(sorted(refused) == sorted(targets), _DenialFailed,
             f"the proxy must refuse github.com and raw.githubusercontent.com with 403 - observed: {seen}")
    log = backend.egress_log(handle)
    assert log is not None
    denied = eg.summarize_log(log)["denied"]
    assert isinstance(denied, dict)
    assert {"github.com:443", "raw.githubusercontent.com:443"} <= set(denied)


@pytest.mark.xfail(BREAK_MODE == "dns-hosts", raises=_ResolutionFailed, strict=True,
                   reason="dns-hosts maps github.com in the container, so resolution must succeed")
def test_a_client_that_ignores_the_proxy_cannot_resolve_names(attempt: tuple[d.DockerBackend, d._Handle]) -> None:
    backend, handle = attempt
    resolve = _probe(handle, "resolve", "github.com", use_proxy=False)
    seen = _observed(backend, handle, {"resolve github.com": resolve})  # before ANY assertion (#460)
    if BREAK_MODE == "dns-hosts":
        assert resolve["result"] == "resolved", f"setup: dns-hosts did not make github.com resolve - observed: {seen}"
    if resolve["result"] == "error":
        assert resolve.get("error") == "gaierror", f"inconclusive: resolution failed for a non-DNS reason - observed: {seen}"
    _require(resolve["result"] == "error", _ResolutionFailed,
             f"github.com must not resolve inside the agent - observed: {seen}")


@pytest.mark.xfail(BREAK_MODE == "bridge-network", raises=_IsolationFailed, strict=True,
                   reason="bridge-network gives the agent a direct route, so isolation must fail")
def test_a_client_that_ignores_the_proxy_has_no_route_out(attempt: tuple[d.DockerBackend, d._Handle]) -> None:
    backend, handle = attempt
    direct = _probe(handle, "direct", GITHUB_ADDRESS, use_proxy=False)
    seen = _observed(backend, handle, {"direct to a GitHub address": direct})  # before ANY assertion (#460)
    if BREAK_MODE == "bridge-network":
        assert direct["result"] == "connected", f"setup: bridge-network gave no direct route - observed: {seen}"
    if direct["result"] == "error":
        # Only "no route" is isolation. A refusal or a timeout means a route
        # existed and the far end did not answer - an outage there would read
        # as isolation here, so it is inconclusive, a hard failure.
        error = str(direct.get("error"))
        assert "Errno 101" in error or "Errno 113" in error or "unreachable" in error.lower(), \
            f"inconclusive: the direct connection failed for a reason other than no route - observed: {seen}"
    _require(direct["result"] == "error", _IsolationFailed,
             f"a direct connection to GitHub must have no route - observed: {seen}")
