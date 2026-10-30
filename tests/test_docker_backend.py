"""Tests for the Docker backend (#77, sub-issue of #10): the `DockerBackend`
constructor/config, `describe()`'s claims, the composed `docker run` argv
(`compose_run_argv`, PR #83's interface), and the real lifecycle
(`prepare`, `install`, `execute`, `confirm_stopped`, `export`, `destroy`,
`confirm_absent`) this PR adds.

Tested here only against a fake `docker` CLI script
(`tests/fixtures/docker-backend/fake_docker.py`) - no daemon is available in
this session. This proves the lifecycle state machine, argv composition and
`describe()`'s claims, never a containment boundary; see `describe()`'s own
`unobserved` claims.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import io
import json
import os
import shutil
import signal
import socket as socket_module
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import types
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from conftest import FAKE_DOCKER_DAEMON_TIMEOUT

from skillc import docker_backend as d
from skillc import lifecycle as lc
from skillc.backend import BackendUnavailable, Confirmation, ExecutionBackend, Limits
from skillc.decide_reply_channel import DecideReplyChannel

needs_setsid = pytest.mark.skipif(
    shutil.which("setsid") is None or shutil.which("sh") is None,
    reason="needs setsid and sh to detach a grandchild from this attempt's process group",
)

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


def _slowed_docker_bin(state_dir: Path, tmp_path: Path, delays: Mapping[str, float]) -> list[str]:
    """The fake CLI, delayed by a fixed number of seconds before the named
    subcommands run: a slow daemon by construction rather than by host load
    (issue #382). A loaded runner is what turned the timing-bound tests red
    on CI, and load alone does not reproduce it on demand."""
    if not delays:
        return _docker_bin(state_dir)
    wrapper = tmp_path / "slowed_docker.py"
    wrapper.write_text(
        "import runpy, sys, time\n"
        f"time.sleep({dict(delays)!r}.get(sys.argv[3], 0.0))\n"
        f"sys.argv = [{str(FAKE_DOCKER)!r}, *sys.argv[1:]]\n"
        f"runpy.run_path({str(FAKE_DOCKER)!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    return [sys.executable, str(wrapper), "--state", str(state_dir)]


def _spy_on_drain_joins(monkeypatch: pytest.MonkeyPatch) -> list[float | None]:
    """Record the `timeout` handed to each `_BoundedDrain` thread's `join()`,
    in call order (issue #382). Joins of any other thread are not recorded.
    Reads CPython's private `Thread._target`: if that ever stops working the
    list stays empty, and `_assert_one_shared_deadline` refuses an empty list."""
    timeouts: list[float | None] = []
    real_join = threading.Thread.join

    def join(thread: threading.Thread, timeout: float | None = None) -> None:
        if isinstance(getattr(getattr(thread, "_target", None), "__self__", None), d._BoundedDrain):
            timeouts.append(timeout)
        real_join(thread, timeout)

    monkeypatch.setattr(threading.Thread, "join", join)
    return timeouts


def _assert_one_shared_deadline(timeouts: list[float | None], bound: float) -> None:
    """Both drains are held open past the join, so the first join waits out
    the whole deadline. Against ONE shared deadline the second join is then
    handed `max(0.0, deadline - now)`, which is 0.0: host load can only push
    `now` later, never the timeout higher. Sequential joins, the regression
    these tests exist to catch, hand the second join the full bound again.
    No wall-clock ceiling is involved (issue #382)."""
    assert len(timeouts) == 2, f"expected exactly the stdout and stderr drain joins, saw {timeouts!r}"
    first, second = timeouts
    # 0.0 is legitimate: scheduling may exhaust the deadline before the first
    # join's own `max(0.0, ...)` is even evaluated (Codex review of #382).
    assert first is not None and 0.0 <= first <= bound, (
        f"the first drain join must be bounded by the one deadline ({bound}s), got {first!r}"
    )
    assert second is not None and second <= 0.1, (
        f"the second drain join got timeout={second!r} after the first had already waited out the deadline - "
        "it was given its own bound instead of the remainder of one shared deadline"
    )


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


def _backend(
    base: Path, docker_state: Path, daemon_timeout: float = FAKE_DOCKER_DAEMON_TIMEOUT,
) -> d.DockerBackend:
    """A backend over the fake CLI, bounded by the TEST-only daemon budget
    (issue #385) - production's 5s bounds a real daemon, and one fake process
    spawn on a loaded host can exceed it. A test that needs the bound to FIRE
    passes its own small `daemon_timeout`, so its claim and runtime do not
    depend on this default."""
    return d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state), daemon_timeout=daemon_timeout,
    )


def _sentinel(docker_state: Path, name: str) -> None:
    """Fault injection is FILE-based (see fake_docker.py's own docstring for
    why): a `monkeypatch.setenv` reaches a real `docker run` invocation only
    by accident, since the implementation PR deliberately launches it with a
    stripped, explicit environment, never the test process's own."""
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / name).touch()


# ------------------------------------------------------------------ _docker_env


def test_docker_env_forwards_the_declared_connection_vars_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_docker_env()` is an ALLOWLIST, never a passthrough of the whole
    ambient environment: only `PATH` and the named `DOCKER_CONNECTION_VARS`
    may reach a docker invocation this backend makes. Named by cross-model
    review as an untested distinction - a real ambient variable that is not
    on the allowlist must never leak through, whatever else is set."""
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/test-daemon.sock")
    monkeypatch.setenv("UNDECLARED_SECRET", "sentinel")
    env = d._docker_env()
    assert env.get("DOCKER_HOST") == "unix:///tmp/test-daemon.sock"
    assert "UNDECLARED_SECRET" not in env
    assert "PATH" in env


def test_docker_env_omits_a_connection_var_that_is_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    env = d._docker_env()
    assert "DOCKER_CONTEXT" not in env


# --------------------------------------------------------------------- describe


def test_the_protocol_runtime_check_passes(base: Path, docker_state: Path) -> None:
    """Even with every lifecycle method stubbed, `DockerBackend` already
    satisfies the `ExecutionBackend` Protocol structurally - the exact
    signatures are what #78/#79 build against before the implementation PR
    lands."""
    assert isinstance(_backend(base, docker_state), ExecutionBackend)


def test_describe_reports_version_and_claims(base: Path, docker_state: Path) -> None:
    description = _backend(base, docker_state).describe()
    assert description.name == "docker"
    assert description.version == "26.0.0-fake"
    assert description.isolation
    assert description.unobserved
    assert any("sandbox" in claim for claim in description.isolation)
    assert any(d.OWNER_LABEL_KEY in claim for claim in description.isolation)


def test_describe_states_disk_limit_is_unset_by_default(base: Path, docker_state: Path) -> None:
    description = _backend(base, docker_state).describe()
    assert any("disk_limit is None" in claim for claim in description.isolation)
    assert any("storage-opt" in claim for claim in description.unobserved)


def test_describe_states_the_configured_disk_limit(base: Path, docker_state: Path) -> None:
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state), daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT, disk_limit="3g",
    )
    description = backend.describe()
    assert any("size=3g" in claim for claim in description.isolation)


def test_describe_reports_unreachable_when_the_daemon_is_down(base: Path, docker_state: Path) -> None:
    _sentinel(docker_state, ".down")
    description = _backend(base, docker_state).describe()
    assert description.version == "unreachable"


def test_describe_reports_the_fixed_candidate_user_regardless_of_the_host_caller(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Design correction (orchestrator review of PR #83, 2026-09-26): an
    earlier draft derived the container's user from the HOST caller's own
    uid/gid, which the container's own `id`, file ownership and transcripts
    would then carry straight into the trial's evidence - a leak `describe()`
    hiding the number could not prevent, since the number was never only in
    `describe()`'s prose. The claim must name the fixed candidate identity
    and must not change with the host caller's uid - this fails on the
    pre-fix code, whose claim (and the composed --user) tracked
    `os.getuid()`/`os.getgid()` directly."""
    monkeypatch.setattr(d.os, "getuid", lambda: 0)
    monkeypatch.setattr(d.os, "getgid", lambda: 0)
    description = _backend(base, docker_state).describe()
    assert any(f"{d.CANDIDATE_UID}:{d.CANDIDATE_GID}" in claim for claim in description.isolation)
    assert any("non-root" in claim for claim in description.isolation)
    assert not any("0:0" in claim for claim in description.isolation)


# -------------------------------------------------------------- compose_run_argv


def _compose(**overrides: object) -> list[str]:
    defaults: dict[str, object] = {
        "docker_bin": ["docker"],
        "image": "fake-image:1",
        "name": "skillc-a-000000000000",
        "attempt_id": "a-000000000000",
        "subject_argv": ["echo", "hi"],
        "env": {},
        "network": "none",
        "memory": d.DEFAULT_MEMORY,
        "pids_limit": d.DEFAULT_PIDS_LIMIT,
        "cpus": d.DEFAULT_CPUS,
        "shm_size": d.DEFAULT_SHM_SIZE,
        "container_user": d._container_user(),
        "disk_limit": None,
    }
    defaults.update(overrides)
    return d.compose_run_argv(**defaults)  # type: ignore[arg-type]


def test_composed_argv_never_mounts_the_docker_socket_or_widens_privilege() -> None:
    """Addendum item C12: never mount the docker socket, never give the
    trial a docker binary. There is no passthrough parameter for extra
    flags, so this is structural, not merely unused."""
    argv = _compose()
    text = " ".join(argv)
    assert "docker.sock" not in text
    assert "--privileged" not in argv
    assert "--cap-add" not in argv
    assert "--pid" not in argv  # never --pid=host


def test_composed_argv_places_image_after_an_end_of_options_marker() -> None:
    """Regression for a bug found by cross-model review: `image` was appended
    as a bare positional with nothing marking where options end. Docker's
    flag parser keeps scanning for recognized flags throughout the argument
    list rather than stopping at the first positional, so an `image` value
    that itself looks like a flag - `--privileged`, say - was not guaranteed
    to be consumed as the IMAGE rather than reinterpreted as an option,
    contradicting the closed-argv guarantee the test above checks. `--` is
    Docker's own end-of-options marker; this fails on the pre-fix code,
    which places `image` with nothing before it to end option parsing."""
    argv = _compose(image="--privileged")
    assert "--" in argv
    dash_dash = argv.index("--")
    assert argv[dash_dash + 1] == "--privileged"
    # the flag-shaped image value must appear only AFTER the "--" boundary,
    # never anywhere in the option region ahead of it
    assert "--privileged" not in argv[:dash_dash]


def test_composed_argv_carries_neutral_identity() -> None:
    argv = _compose()
    assert "--user" in argv and argv[argv.index("--user") + 1] == d._container_user()
    assert "--hostname" in argv and argv[argv.index("--hostname") + 1] == d.CONTAINER_HOSTNAME
    assert "-w" in argv and argv[argv.index("-w") + 1] == d.CONTAINER_WORKSPACE
    home_values = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert f"HOME={d.CONTAINER_HOME}" in home_values


def test_composed_argv_never_bind_mounts_the_workspace_or_home() -> None:
    """Design decision (orchestrator review of PR #83, 2026-09-26): no bind
    mount for the workspace or home, ever - a mount matched to the fixed
    candidate uid would need a host directory made writable for that exact
    uid, which is either another uid-matching problem or over-broad write
    access. `docker cp` moves the declared surface in and the exported
    output out instead (the implementation PR's install()/export())."""
    argv = _compose()
    assert "-v" not in argv


# ------------------------------------------------- #183 trigger-socket mount


def test_composed_argv_omits_the_trigger_mount_by_default() -> None:
    """Every caller before #183 passes nothing for `trigger_socket_host_path`
    (it defaults to `None`), and the resulting argv must be byte-for-byte
    what it was before #183 - no `--mount` flag anywhere."""
    argv = _compose()
    assert "--mount" not in argv


def test_composed_argv_adds_exactly_one_trigger_socket_mount_when_given(tmp_path: Path) -> None:
    host_path = tmp_path / "trigger-sockets" / "skillc-a-000000000000.sock"
    argv = _compose(trigger_socket_host_path=host_path)
    mount_flags = [i for i, a in enumerate(argv) if a == "--mount"]
    assert len(mount_flags) == 1
    value = argv[mount_flags[0] + 1]
    assert value == f"type=bind,source={host_path},target={d.TRIGGER_SOCKET_PATH}"


def test_composed_argv_trigger_mount_target_is_fixed_never_the_callers_choice(tmp_path: Path) -> None:
    """The design's whole guarantee (decide-reply-channel.md §2c): the
    SOURCE varies per attempt, but the TARGET never does, and there is no
    parameter through which a caller could ask for a different one -
    `compose_run_argv`'s signature has no such parameter at all."""
    for host_path in (tmp_path / "a.sock", tmp_path / "nested" / "b.sock", Path("/tmp/weird name.sock")):
        argv = _compose(trigger_socket_host_path=host_path)
        value = argv[argv.index("--mount") + 1]
        assert value.endswith(f",target={d.TRIGGER_SOCKET_PATH}")
        assert d.TRIGGER_SOCKET_PATH not in (d.CONTAINER_WORKSPACE, d.CONTAINER_HOME)  # sanity: distinct constants


def test_trigger_socket_host_path_stays_short_even_for_a_long_attempt_id(tmp_path: Path) -> None:
    """`_container_name` allows up to 128 characters; this must not
    reintroduce the AF_UNIX overflow `DEFAULT_TRIGGER_SOCKET_DIR`'s
    comment names - the digest keeps the FILENAME fixed-length regardless
    of how long the attempt id (and so the container name) is."""
    long_name = d._container_name("a-" + "x" * 200)
    assert len(long_name) <= 128
    path = d.trigger_socket_host_path_for(tmp_path, long_name)
    assert path.name.endswith(".sock")
    assert len(path.name) < 32  # hash-derived, independent of long_name's own length


def test_ensure_private_trigger_dir_creates_mode_0700_when_absent(tmp_path: Path) -> None:
    target = tmp_path / "trigger-dir"
    d._ensure_private_trigger_dir(target)
    assert target.is_dir()
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_ensure_private_trigger_dir_accepts_an_existing_correctly_owned_0700_dir(tmp_path: Path) -> None:
    target = tmp_path / "trigger-dir"
    target.mkdir(mode=0o700)
    os.chmod(target, 0o700)
    d._ensure_private_trigger_dir(target)  # must not raise


def test_ensure_private_trigger_dir_refuses_an_existing_dir_with_the_wrong_mode(tmp_path: Path) -> None:
    target = tmp_path / "trigger-dir"
    target.mkdir(mode=0o700)
    os.chmod(target, 0o755)  # world-readable/executable - the exact hazard named in review
    with pytest.raises(BackendUnavailable, match="0o700"):
        d._ensure_private_trigger_dir(target)


def test_ensure_private_trigger_dir_refuses_an_existing_dir_owned_by_a_different_uid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Can't actually chown to a different uid without privilege in this
    environment, so the OTHER side of the comparison is mocked instead:
    `os.getuid()` is made to disagree with the directory's real owner,
    exercising the exact branch a real cross-uid collision would hit."""
    target = tmp_path / "trigger-dir"
    target.mkdir(mode=0o700)
    os.chmod(target, 0o700)
    real_getuid = os.getuid
    monkeypatch.setattr(d.os, "getuid", lambda: real_getuid() + 1)
    with pytest.raises(BackendUnavailable, match="uid"):
        d._ensure_private_trigger_dir(target)


def test_composed_argv_has_no_parameter_for_a_second_mount_or_any_other_extra_flag() -> None:
    """Structural, not a convention: calling `compose_run_argv` with an
    unrecognized keyword (a second mount, `privileged=True`, a plausibly-
    named override of the mount TARGET, anything not in its fixed
    signature) is a `TypeError` from Python itself, not a value this
    function could silently accept and act on. The target-override names
    are not hypothetical: a mutation that added exactly such a parameter
    (defaulting to `TRIGGER_SOCKET_PATH`, so every existing call site stayed
    unaffected) passed every other test in this file silently - only a test
    that actively tries the parameter name catches it."""
    with pytest.raises(TypeError):
        _compose(extra_mount="/host/other:/container/other")
    with pytest.raises(TypeError):
        _compose(privileged=True)
    with pytest.raises(TypeError):
        _compose(trigger_socket_target="/evil/path")
    with pytest.raises(TypeError):
        _compose(trigger_target="/evil/path")
    with pytest.raises(TypeError):
        _compose(mount_target="/evil/path")


def test_container_user_is_fixed_and_never_tracks_the_host_callers_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orchestrator's requested control (PR #83 review, 2026-09-26): the
    composed `--user` must be the fixed candidate identity and must NEVER be
    `os.getuid()`/`os.getgid()`, whatever the host caller's real uid is. This
    fails on the design an earlier draft shipped, where `_container_user()`
    returned `f"{os.getuid()}:{os.getgid()}"` directly."""
    monkeypatch.setattr(d.os, "getuid", lambda: 777777)
    monkeypatch.setattr(d.os, "getgid", lambda: 888888)
    assert d._container_user() == f"{d.CANDIDATE_UID}:{d.CANDIDATE_GID}"
    argv = _compose(container_user=d._container_user())
    assert argv[argv.index("--user") + 1] == f"{d.CANDIDATE_UID}:{d.CANDIDATE_GID}"
    assert "777777:888888" not in argv


def test_composed_argv_carries_ownership_labels() -> None:
    """#77's ownership requirement: every container carries a fixed
    "this belongs to skillc" label plus a per-attempt label - a reaping sweep
    (#79) filters on the fixed label to find every skillc-owned container
    without trusting name matching, and a foreign container sharing a similar
    name but carrying neither label is never touched."""
    argv = _compose(attempt_id="a-abc123")
    labels = [argv[i + 1] for i, a in enumerate(argv) if a == "--label"]
    assert f"{d.OWNER_LABEL_KEY}={d.OWNER_LABEL_VALUE}" in labels
    assert f"{d.ATTEMPT_LABEL_KEY}=a-abc123" in labels


def test_composed_argv_omits_storage_opt_when_no_disk_limit_is_set() -> None:
    argv = _compose(disk_limit=None)
    assert "--storage-opt" not in argv


def test_composed_argv_carries_a_storage_opt_disk_bound_when_set() -> None:
    argv = _compose(disk_limit="2g")
    assert "--storage-opt" in argv
    assert argv[argv.index("--storage-opt") + 1] == "size=2g"


def test_composed_argv_carries_matched_memory_and_swap_and_other_limits() -> None:
    """Addendum item C9: --memory-swap must equal --memory, or swap silently
    doubles the effective bound."""
    argv = _compose(memory="2g")
    assert argv[argv.index("--memory") + 1] == "2g"
    assert argv[argv.index("--memory-swap") + 1] == "2g"
    assert "--pids-limit" in argv
    assert "--cpus" in argv
    assert "--shm-size" in argv


def test_composed_argv_refuses_a_bare_env_name() -> None:
    with pytest.raises(TypeError, match="explicit string value"):
        _compose(env={"TOKEN": None})


def test_composed_argv_never_forwards_a_bare_dash_e() -> None:
    argv = _compose(env={"FOO": "bar"})
    assert "-e" in argv
    # every -e's following value must have a "=" - never a bare name
    values = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
    assert all("=" in v for v in values)


# ------------------------------------------------------------------ lifecycle


def test_prepare_raises_when_daemon_unreachable(base: Path, docker_state: Path) -> None:
    _sentinel(docker_state, ".down")
    backend = _backend(base, docker_state)
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-lc-000000000001")


def test_prepare_raises_when_docker_run_itself_fails(base: Path, docker_state: Path) -> None:
    """The daemon is reachable (`version` succeeds) but the actual `docker
    run -d` that starts this attempt's container is refused - prepare() must
    turn that into BackendUnavailable too, never construct a handle for a
    container that was never actually created."""
    _sentinel(docker_state, ".refuse-run")
    backend = _backend(base, docker_state)
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-lc-000000000002")


def test_prepare_raises_when_the_docker_binary_is_missing(base: Path) -> None:
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=["/nonexistent/docker-binary-xyz"], daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT,
    )
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-lc-000000000003")


def test_prepare_refuses_a_missing_image_without_attempting_run(
    base: Path, docker_state: Path,
) -> None:
    """Issue #133 item 1: an explicit `docker image inspect` precheck refuses
    outright when the image is not present locally, rather than letting
    `docker run -d` discover that itself by implicitly pulling it - which can
    run far longer than any bound this backend places on `run -d` itself."""
    _sentinel(docker_state, ".no-image")
    backend = _backend(base, docker_state)
    with pytest.raises(BackendUnavailable, match="not present locally"):
        backend.prepare("a-lc-000000000003b")
    # No container state was ever created - `run -d` was never even attempted.
    name = d._container_name("a-lc-000000000003b")
    assert not (docker_state / f"{name}.json").exists()


def test_prepare_raises_within_the_bound_when_docker_run_stalls(
    base: Path, docker_state: Path,
) -> None:
    """Red case for issue #133 item 1: the pre-fix `docker run -d` call in
    `prepare()` carried no `timeout=` at all, unlike every other daemon call
    in this module, so a stalled daemon (or an implicit image pull mid-call)
    hung the trial instead of reporting BLOCKED/UNKNOWN within a bound. This
    fixture's `.hang-run` sentinel makes `run -d` sleep for 10s before
    answering; a `daemon_timeout` far shorter than that must still turn it
    into BackendUnavailable and return well before the full sleep elapses.
    The 10x margin (and a generous assertion threshold) is deliberate: this
    spawns several real Python interpreter subprocesses, and a tight bound
    was measured flaky under load from the rest of the suite running
    concurrently. Fails on the pre-fix code, which would block for the
    full 10s (or hang forever against a daemon that never answers at all)."""
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".hang-run").write_text("10", encoding="utf-8")
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
        daemon_timeout=1.0,
    )
    started = time.monotonic()
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-lc-000000000003c")
    elapsed = time.monotonic() - started
    assert elapsed < 6.0, f"prepare() took {elapsed:.2f}s - the daemon_timeout bound was not enforced"


def test_install_reports_discovery_canary_violated_when_nothing_is_declared(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000004")
    readiness = backend.install(handle, {})
    assert readiness["discovery_canary"] == "VIOLATED"
    assert readiness["declared"] == 0
    assert "canary_path" not in readiness
    backend.destroy(handle)


def test_install_accepts_raw_bytes_surface_values(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Regression (#81): `verify.py`'s own probe-surface convention (#76)
    declares files as raw `bytes`, never a host path - `install()` used to
    silently skip every such entry (`_as_existing_path` correctly returns
    `None` for bytes), so nothing was ever actually copied in, discovered
    only when #81's demo command tried to grade through this backend for
    real and every probe failed with "no such file". Fails on the pre-fix
    code (installed == 0, discovery_canary VIOLATED, and the file is
    genuinely absent from the container's own filesystem)."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000005b")
    assert isinstance(handle, d._Handle)
    readiness = backend.install(handle, {"probe.py": b"print('hello')\n"})
    assert readiness["installed"] == 1
    assert readiness["discovery_canary"] == "SATISFIED"
    dest = tmp_path / "export"
    backend.export(handle, dest)
    assert (dest / "probe.py").read_bytes() == b"print('hello')\n"
    backend.destroy(handle)


def _observe_install_calls(
    monkeypatch: pytest.MonkeyPatch, calls: list[tuple[list[str], bytes | None]], probe_fails: bool = False,
) -> None:
    real_run = subprocess.run

    def observed_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        payload = kwargs.get("input")
        calls.append((list(argv), payload if isinstance(payload, bytes) else None))
        if probe_fails and _is_parent_probe(argv):
            return subprocess.CompletedProcess(argv, 1, b"", b"probe exploded")
        return real_run(argv, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "run", observed_run)


def _is_parent_probe(argv: list[str]) -> bool:
    return "exec" in argv and any(a.startswith("i=0; for p do") for a in argv)


def _tar_members(payload: bytes) -> list[tarfile.TarInfo]:
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        return archive.getmembers()


def test_missing_parent_candidates_lists_every_ancestor_parents_first() -> None:
    assert d._missing_parent_candidates(["top.py", "tests/unit/x.py", "tests/y.py", "ci/deep/gate.sh"]) == [
        "ci", "tests", "ci/deep", "tests/unit",
    ]
    assert d._missing_parent_candidates(["flat.py", "other"]) == []


def test_owned_tar_dirs_are_candidate_owned_directories_in_order() -> None:
    members = _tar_members(d._owned_tar_dirs(["tests", "tests/unit"]))
    assert [m.name for m in members] == ["tests", "tests/unit"]
    for m in members:
        assert m.isdir()
        assert (m.uid, m.gid, m.mode) == (d.CANDIDATE_UID, d.CANDIDATE_GID, 0o755)


def test_install_delivers_only_absent_nested_parents_as_owned_directories_first(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """#393: a one-file tar for `tests/unit/x.py` names no directory, so a
    real `docker cp` creates `tests/` and `tests/unit/` owned by root and
    the candidate cannot add a file there. The absent ancestors now go in
    first, as candidate-owned directory entries - and ONLY the absent ones:
    `pre/` already exists, and a directory entry landing on it would rewrite
    its owner and mode on a real daemon. Fails on the pre-fix code (no
    probe, no directory tar). The ownership itself is real-Docker evidence:
    `tests/test_install_nested_dirs_live.py`."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-nested-parents-01")
    assert isinstance(handle, d._Handle)
    (docker_state / f"{handle.name}.fsroot" / "work" / "pre").mkdir(parents=True)
    host_dir = tmp_path / "kit"
    host_dir.mkdir()
    (host_dir / "a.sh").write_text("true\n")
    calls: list[tuple[list[str], bytes | None]] = []
    try:
        with monkeypatch.context() as patch:
            _observe_install_calls(patch, calls)
            readiness = backend.install(handle, {
                "tests/unit/x.py": b"x", "pre/y.py": b"y", "tools/kit": host_dir, "flat.py": b"f",
            })
        assert readiness["entries"] == {
            "tests/unit/x.py": "installed", "pre/y.py": "installed", "tools/kit": "installed", "flat.py": "installed",
        }
        assert list(readiness["entries"]) == ["tests/unit/x.py", "pre/y.py", "tools/kit", "flat.py"]
        probes = [argv for argv, _ in calls if _is_parent_probe(argv)]
        assert len(probes) == 1
        probe = probes[0][len(backend.docker_bin):]
        assert probe[:4] == ["exec", "-u", "0", "--"]
        assert sorted(probe[-4:]) == ["/work/pre", "/work/tests", "/work/tests/unit", "/work/tools"]
        copies = [payload for argv, payload in calls if "cp" in argv and payload is not None]
        dirs = _tar_members(copies[0])
        assert [m.name for m in dirs] == ["tests", "tools", "tests/unit"]
        assert all(m.isdir() and m.uid == d.CANDIDATE_UID for m in dirs)
        assert len(copies) == 1 + 4
        dest = tmp_path / "export"
        backend.export(handle, dest)
        assert (dest / "tests/unit/x.py").read_bytes() == b"x"
        assert (dest / "tools/kit/a.sh").is_file()
    finally:
        backend.destroy(handle)


def test_install_of_a_flat_surface_makes_no_parent_probe(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-nested-parents-02")
    assert isinstance(handle, d._Handle)
    calls: list[tuple[list[str], bytes | None]] = []
    try:
        with monkeypatch.context() as patch:
            _observe_install_calls(patch, calls)
            backend.install(handle, {"a.py": b"a", "b.py": b"b", "gone/x.py": "/no/such/host/path"})
        assert not [argv for argv, _ in calls if _is_parent_probe(argv)]
        assert len([p for argv, p in calls if "cp" in argv and p is not None]) == 2
    finally:
        backend.destroy(handle)


def test_install_refuses_before_copying_anything_when_the_parent_probe_fails(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unanswered probe is never guessed: "absent" would rewrite an
    existing directory, "present" would leave a root-owned one."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-nested-parents-03")
    assert isinstance(handle, d._Handle)
    calls: list[tuple[list[str], bytes | None]] = []
    try:
        with monkeypatch.context() as patch:
            _observe_install_calls(patch, calls, probe_fails=True)
            with pytest.raises(BackendUnavailable, match="parent probe failed"):
                backend.install(handle, {"tests/x.py": b"x"})
        assert not [p for argv, p in calls if "cp" in argv and p is not None]
    finally:
        backend.destroy(handle)


def test_install_refuses_when_the_parent_directory_copy_fails(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The directory tar is copied before any file; if it fails, no file is
    copied into a parent the candidate would not own."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-nested-parents-05")
    assert isinstance(handle, d._Handle)
    real_run = subprocess.run
    file_copies: list[bytes] = []

    def failing_dir_copy(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        payload = kwargs.get("input")
        if "cp" in argv and isinstance(payload, bytes):
            if all(m.isdir() for m in _tar_members(payload)):
                return subprocess.CompletedProcess(argv, 1, b"", b"no space left")
            file_copies.append(payload)
        return real_run(argv, **kwargs)  # type: ignore[call-overload]

    try:
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "run", failing_dir_copy)
            with pytest.raises(BackendUnavailable, match="nested parent directories"):
                backend.install(handle, {"tests/x.py": b"x"})
        assert file_copies == []
    finally:
        backend.destroy(handle)


@pytest.mark.parametrize("stdout", [b"zero\n", b"7\n", b"-1\n"])
def test_absent_parents_refuses_an_unreadable_or_out_of_range_answer(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, stdout: bytes,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-nested-parents-04")
    assert isinstance(handle, d._Handle)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout, b""))
            with pytest.raises(BackendUnavailable, match="parent probe answered"):
                backend._absent_parents(handle, "/work", ["tests", "tests/unit"])
    finally:
        backend.destroy(handle)


def test_install_counts_a_non_path_surface_value_without_copying_it(
    base: Path, docker_state: Path,
) -> None:
    """Regression for a cross-model review finding (PR #85): `discovery_canary`
    must reflect what was actually COPIED, never merely what was declared - a
    non-path value (or a path that does not exist) is counted in `declared`
    but installs nothing, so readiness must not certify SATISFIED for it.
    This fails on the pre-fix code, which reported SATISFIED here regardless
    of whether anything was actually installed."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000005")
    readiness = backend.install(handle, {"meta": {"not": "a host path"}})
    assert readiness["declared"] == 1
    assert readiness["installed"] == 0
    assert readiness["discovery_canary"] == "VIOLATED"
    assert readiness["entries"] == {"meta": "not-a-path"}
    backend.destroy(handle)


def test_install_reports_a_partial_install_as_violated_not_masked_by_a_success(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Red case for issue #133 item 4: the pre-fix `discovery_canary` derivation
    was `"SATISFIED" if installed else "VIOLATED"` - VIOLATED only when NOTHING
    installed, so one missing helper among several successes was invisible.
    Two entries declared, one a real file and one a host path that does not
    exist: `installed == 1` alone used to read as success. Fails on that
    pre-fix code (discovery_canary SATISFIED here); the fix requires every
    declared entry to install, and names which one did not."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000005c")
    good_file = tmp_path / "good.txt"
    good_file.write_text("present\n")
    missing_path = str(tmp_path / "does-not-exist.txt")
    readiness = backend.install(handle, {"good.txt": good_file, "missing.txt": missing_path})
    assert readiness["declared"] == 2
    assert readiness["installed"] == 1
    assert readiness["entries"] == {"good.txt": "installed", "missing.txt": "missing"}
    assert readiness["discovery_canary"] == "VIOLATED"
    backend.destroy(handle)


def test_install_reports_baseline_contamination_for_a_preexisting_entry(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Red case for issue #133 item 4: an undeclared skill already present in
    the IMAGE (never installed by this attempt) used to be invisible -
    `baseline_absence` was hardcoded permanently SATISFIED. Seeds a file at
    the container's own workspace path before `install()` runs (simulating
    something baked into the image), declares a REAL host file at that same
    key, and asserts the pre-existing entry is reported rather than silently
    accepted as this attempt's own install. Fails on the pre-fix code, which
    never inspected the container's contents before copying and always
    reported `baseline_absence: SATISFIED`."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000005d")
    assert isinstance(handle, d._Handle)
    container_workspace = docker_state / f"{handle.name}.fsroot" / "work"
    container_workspace.mkdir(parents=True, exist_ok=True)
    (container_workspace / "baked-in.txt").write_text("was already here\n")

    surface_file = tmp_path / "baked-in.txt"
    surface_file.write_text("declared content\n")
    readiness = backend.install(handle, {"baked-in.txt": surface_file})
    assert readiness["baseline_absence"] == "VIOLATED"
    assert readiness["preexisting"] == ["baked-in.txt"]
    # The install itself still proceeds and is still reported per-entry -
    # contamination is a distinct fact from whether THIS run's copy worked.
    assert readiness["entries"] == {"baked-in.txt": "installed"}
    backend.destroy(handle)


def test_install_reports_baseline_absence_satisfied_for_a_clean_workspace(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000005e")
    surface_file = tmp_path / "clean.txt"
    surface_file.write_text("content\n")
    readiness = backend.install(handle, {"clean.txt": surface_file})
    assert readiness["baseline_absence"] == "SATISFIED"
    assert "preexisting" not in readiness
    backend.destroy(handle)


def test_install_reports_installed_and_discovery_canary_satisfied_for_a_real_copy(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000005b")
    surface_file = tmp_path / "skill.txt"
    surface_file.write_text("skill contents\n")
    readiness = backend.install(handle, {"skill.txt": surface_file})
    assert readiness["declared"] == 1
    assert readiness["installed"] == 1
    assert readiness["discovery_canary"] == "SATISFIED"
    backend.destroy(handle)


def test_install_reports_the_image_the_container_was_created_from(base: Path, docker_state: Path) -> None:
    """#12: the digest that ACTUALLY ran, asked of the container - the same id
    `image inspect` resolves for the configured image when nothing moved."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-0000000000e01")
    readiness = backend.install(handle, {})
    assert readiness["image_digest"] == "sha256:fake-digest-for-fake-image:1"
    backend.destroy(handle)


def test_install_reports_a_republished_image_not_the_configured_tag(base: Path, docker_state: Path) -> None:
    """The configured string is never echoed back as the digest: when the
    container was created from a different id, that id is what is reported."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-0000000000e02")
    assert isinstance(handle, d._Handle)
    (docker_state / f".image-id-{handle.name}").write_text("sha256:republished\n")
    assert backend.install(handle, {})["image_digest"] == "sha256:republished"
    backend.destroy(handle)


def test_install_reports_no_image_digest_when_the_daemon_cannot_say(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-0000000000e03")
    assert isinstance(handle, d._Handle)
    _sentinel(docker_state, f".no-image-id-{handle.name}")
    assert backend.install(handle, {})["image_digest"] is None
    backend.destroy(handle)


def test_install_raises_when_the_container_is_already_gone(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000006")
    backend.destroy(handle)
    surface_file = tmp_path / "x.txt"
    surface_file.write_text("x")
    with pytest.raises(BackendUnavailable):
        backend.install(handle, {"x.txt": surface_file})


def test_full_lifecycle_happy_path_installs_executes_and_exports(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """The whole seam, end to end, against the fake CLI: prepare() starts one
    persistent container; install() copies a declared surface file and plants
    the liveness canary via `docker cp`; execute() runs a real subprocess via
    `docker exec` that touches the canary and writes its own output;
    confirm_stopped() reports CONFIRMED once the container's own placeholder
    has been stopped too (not just the exec'd process); export() copies
    everything back out via `docker cp`; destroy()+confirm_absent() tear it
    down for real."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000007")

    surface_file = tmp_path / "skill.txt"
    surface_file.write_text("skill contents\n")
    nonce = "test-nonce-abc"
    readiness = backend.install(handle, {"skill.txt": surface_file, lc.CANARY_NONCE_KEY: nonce})
    assert readiness["discovery_canary"] == "SATISFIED"
    assert readiness["declared"] == 1
    assert readiness["canary_path"] == d.CANARY_RESULT_FILENAME

    script = (
        "import pathlib;"
        "p = pathlib.Path('.skillc-canary');"
        "n = p.read_text(encoding='utf-8') if p.exists() else '';"
        "pathlib.Path('.skillc-canary-result').write_text(f'touched:{n}', encoding='utf-8');"
        "pathlib.Path('out.txt').write_text('subject output', encoding='utf-8')"
    )
    result = backend.execute(handle, [sys.executable, "-c", script], Limits(timeout=5))
    assert result.reason == "exited"
    assert result.exit_code == 0

    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED

    dest = tmp_path / "export"
    backend.export(handle, dest)
    assert (dest / "out.txt").read_text(encoding="utf-8") == "subject output"
    assert (dest / d.CANARY_RESULT_FILENAME).read_text(encoding="utf-8") == f"touched:{nonce}"
    assert (dest / "skill.txt").read_text(encoding="utf-8") == "skill contents\n"

    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.CONFIRMED


# ---------------------------------------------- deliver_home_file (#98)

def test_deliver_home_file_lands_where_a_client_would_read_it(base: Path, docker_state: Path) -> None:
    """`deliver_home_file` targets CONTAINER_HOME, never CONTAINER_WORKSPACE.

    Checked against the fake CLI's own mapped state, not through `execute()`
    reading an absolute path back - the fake CLI runs a REAL host subprocess
    with no chroot (its own module docstring: "proves the LIFECYCLE, never
    a containment boundary"), so an absolute `/home/candidate/...` read
    would resolve on the REAL host filesystem, not inside any simulated
    container, and could not tell "landed in the container's home" apart
    from "happens to exist on this host". The mapped-path convention
    (`{name}.fsroot/<container path>`) is the fake CLI's own documented
    state model, used here deliberately rather than by accident."""
    backend = _backend(base, docker_state)
    attempt_id = "a-lc-000000000010"
    handle = backend.prepare(attempt_id)
    backend.deliver_home_file(handle, ".claude/.credentials.json", b"fake-credential-bytes")

    name = d._container_name(attempt_id)
    mapped = docker_state / f"{name}.fsroot" / "home" / "candidate" / ".claude" / ".credentials.json"
    assert mapped.read_bytes() == b"fake-credential-bytes"
    backend.destroy(handle)


def test_a_delivered_home_file_is_absent_from_export_output(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Control (#98's own acceptance): the credential is absent from
    export() output, PROVIDED nothing inside the container copies it out of
    home first. `export()` never reads CONTAINER_HOME itself, so this test's
    own placement of the file is never the reason it stays absent here - but
    that is narrower than "the credential can never leak into an export"
    (see `deliver_home_file`'s own docstring, and the sibling test below,
    which is the negative case cross-model review asked for)."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000011")
    backend.deliver_home_file(handle, ".claude/.credentials.json", b"fake-credential-bytes")

    surface_file = tmp_path / "skill.txt"
    surface_file.write_text("skill contents\n")
    backend.install(handle, {"skill.txt": surface_file})

    dest = tmp_path / "export"
    backend.export(handle, dest)
    exported_names = {p.name for p in dest.rglob("*") if p.is_file()}
    assert ".credentials.json" not in exported_names
    for path in dest.rglob("*"):
        if path.is_file():
            assert b"fake-credential-bytes" not in path.read_bytes()
    backend.destroy(handle)


def test_a_candidate_copying_its_own_credential_into_work_does_reach_export(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Red case for the guarantee above (cross-model review, #98): a
    delivered home file is absent from export() only because nothing put it
    in CONTAINER_WORKSPACE. If a candidate process reads its own home
    directory and writes those bytes into `/work` - exactly what a real
    agent COULD do, on purpose or by accident - export DOES surface them.
    `deliver_home_file`/`export()` structurally prevent nothing here; this
    is why `skillc/leak.py` scans exported content independently rather
    than relying on the credential's delivery location alone."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000011a")
    backend.deliver_home_file(handle, ".claude/.credentials.json", b"fake-credential-bytes")
    backend.install(handle, {})

    name = d._container_name("a-lc-000000000011a")
    home_file = docker_state / f"{name}.fsroot" / "home" / "candidate" / ".claude" / ".credentials.json"
    work_copy = docker_state / f"{name}.fsroot" / "work" / "auth-copy.json"
    work_copy.parent.mkdir(parents=True, exist_ok=True)
    work_copy.write_bytes(home_file.read_bytes())  # simulates a candidate's own `cp`

    dest = tmp_path / "export"
    backend.export(handle, dest)
    assert (dest / "auth-copy.json").read_bytes() == b"fake-credential-bytes"
    backend.destroy(handle)


def test_a_delivered_home_file_is_gone_after_destroy(base: Path, docker_state: Path) -> None:
    """Control (#98's own acceptance): the credential is absent from the
    container after destroy() - the whole container is confirmed gone, so
    nothing delivered to its home survives independently of it."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000012")
    backend.deliver_home_file(handle, ".codex/auth.json", b"fake-codex-auth-bytes")
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.CONFIRMED
    # The container is gone entirely - a second delivery attempt against the
    # same (now-dead) handle must fail, never silently re-create it.
    with pytest.raises(BackendUnavailable):
        backend.deliver_home_file(handle, ".codex/auth.json", b"fake-codex-auth-bytes")


def test_read_home_file_reads_back_what_was_delivered(base: Path, docker_state: Path) -> None:
    """`read_home_file` is `deliver_home_file`'s read-side counterpart
    (#98): a caller compares its result against what it delivered to observe
    whether an in-container refresh happened, before `destroy()` discards
    the container and that fact along with it."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000013")
    backend.deliver_home_file(handle, ".claude/.credentials.json", b"fake-credential-bytes")
    assert backend.read_home_file(handle, ".claude/.credentials.json") == b"fake-credential-bytes"
    backend.destroy(handle)


def test_read_home_file_observes_an_in_container_change(base: Path, docker_state: Path) -> None:
    """A refresh happening inside the container changes the file's bytes on
    disk under the fake CLI's mapped state - the same white-box convention
    `test_deliver_home_file_lands_where_a_client_would_read_it` uses, standing
    in for what a real refreshing client would do to its own credential
    file. `read_home_file` must see the CHANGED bytes, not the delivered
    ones, or `credential.refresh_observed` could never detect a real one."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000014")
    backend.deliver_home_file(handle, ".claude/.credentials.json", b"original-bytes")

    name = d._container_name("a-lc-000000000014")
    mapped = docker_state / f"{name}.fsroot" / "home" / "candidate" / ".claude" / ".credentials.json"
    mapped.write_bytes(b"refreshed-bytes")

    assert backend.read_home_file(handle, ".claude/.credentials.json") == b"refreshed-bytes"
    backend.destroy(handle)


def test_read_home_file_fails_on_a_dead_container(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000015")
    backend.deliver_home_file(handle, ".claude/.credentials.json", b"fake-credential-bytes")
    backend.destroy(handle)
    with pytest.raises(BackendUnavailable):
        backend.read_home_file(handle, ".claude/.credentials.json")


# ---------------------------------------------- read_home_tree (#106)

def test_read_home_tree_on_a_missing_directory_is_empty_not_an_error(base: Path, docker_state: Path) -> None:
    """The ordinary state before an agent has run at all - not a failure."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000016")
    assert backend.read_home_tree(handle, ".claude/projects") == {}
    backend.destroy(handle)


def test_read_home_tree_finds_a_realistic_transcript_path(base: Path, docker_state: Path) -> None:
    """A real transcript's exact name (a client-chosen session uuid nested
    under a mangled-cwd directory) cannot be predicted in advance - this is
    exactly why the tree read exists rather than a fixed relpath."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000017")
    backend.deliver_home_file(
        handle, ".claude/projects/-work/22222222-2222-2222-2222-222222222222.jsonl", b"line one\n",
    )
    tree = backend.read_home_tree(handle, ".claude/projects")
    assert tree == {"-work/22222222-2222-2222-2222-222222222222.jsonl": b"line one\n"}
    backend.destroy(handle)


def test_read_home_tree_finds_multiple_files_under_the_directory(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000018")
    backend.deliver_home_file(handle, ".codex/sessions/2026/09/27/rollout-a.jsonl", b"a")
    backend.deliver_home_file(handle, ".codex/sessions/2026/09/27/rollout-b.jsonl", b"b")
    tree = backend.read_home_tree(handle, ".codex/sessions")
    assert tree == {
        "2026/09/27/rollout-a.jsonl": b"a",
        "2026/09/27/rollout-b.jsonl": b"b",
    }
    backend.destroy(handle)


@needs_setsid
@pytest.mark.skipif(shutil.which("cat") is None, reason="needs cat to block the detached grandchild on a FIFO")
@pytest.mark.parametrize("delays", [{}, {"cp": 1.2}], ids=["nominal", "slow-cp"])
def test_read_home_tree_joins_stdout_and_stderr_against_one_shared_deadline(
    base: Path, docker_state: Path, tmp_path: Path, delays: dict[str, float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """issue #20 Nit Store: read_home_tree's own stdout/stderr drain joins
    had the identical sequential-join shape execute()'s just got fixed for
    - measured directly (not merely reasoned about) at ~2.02x the single
    daemon_timeout bound before this fix, ~1.02x after, using a detached
    grandchild that holds THIS fake docker process's own stdout open past
    its exit (`.cp-hold-open-NAME`, fake_docker.py's own fault-injection
    sentinel for this path - the same construction `.inspect-delay-NAME`
    and execute()'s drain-EOF test both use). Unlike execute()'s own
    trigger (a candidate's exec'd argv can adversarially or accidentally
    detach a descendant), a real `docker cp` invocation never runs
    caller-supplied code - this proves the MECHANISM no longer costs 2x
    under a constructed still-alive-at-join-time case, not a claim that
    this exact scenario arises from an untrusted subject the way
    execute()'s does; a real trigger here would be host scheduling delay,
    not an adversarial descendant.

    TIMING ONLY, deliberately: any tar bytes genuinely written before the
    grandchild holds the pipe open (even an empty directory's own tar
    header) trip issue #189 (`_BoundedDrain.run()`'s `.read(65536)` blocks
    to fill the full size rather than returning what is already available,
    so a still-open pipe under that size reads back EMPTY instead of
    partial) - a separate, pre-existing bug this test does not attempt to
    characterize or fix. `read_home_tree()` is expected to raise under that
    bug; only the JOIN SHAPE is this test's own claim.

    Issue #382: this used to assert `elapsed < daemon_timeout + 0.8` with a
    1.0s `daemon_timeout` on every fake-CLI call, and once failed in SETUP -
    `deliver_home_file`'s `docker cp` exceeded 1.0s on a loaded host. It now
    asserts the join shape directly (`_assert_one_shared_deadline`), which
    host load cannot move, at the suite-default `daemon_timeout`. `slow-cp`
    delays every fake `docker cp` by 1.2s, the setup failure by
    construction; it failed the old test and passes this one."""
    daemon_timeout = 5.0
    # SETUP on the suite's fake-CLI budget (#412): on CI 806 the 1.2 s-slowed
    # `docker cp` in deliver_home_file overran 5.0 s before the read under
    # test ever ran. Only `read_home_tree` - the call whose join shape this
    # test pins - keeps the 5.0 s bound.
    setup = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_slowed_docker_bin(docker_state, tmp_path, delays),
        daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT,
    )
    handle = setup.prepare("a-lc-000000000018b")
    assert isinstance(handle, d._Handle)
    setup.deliver_home_file(handle, ".claude/projects/-work/x.jsonl", b"line\n")
    backend = dataclasses.replace(setup, daemon_timeout=daemon_timeout)
    assert backend.daemon_timeout == 5.0 and setup.daemon_timeout == FAKE_DOCKER_DAEMON_TIMEOUT
    fifo = tmp_path / "hold-open.fifo"
    os.mkfifo(fifo)
    docker_state.mkdir(parents=True, exist_ok=True)
    sentinel = docker_state / f".cp-hold-open-{handle.name}"
    sentinel.write_text(str(fifo), encoding="utf-8")
    joins = _spy_on_drain_joins(monkeypatch)
    try:
        try:
            backend.read_home_tree(handle, ".claude/projects")
        except tarfile.ReadError:
            pass  # issue #189, not this test's own claim - see the docstring above
    finally:
        sentinel.unlink(missing_ok=True)
        try:
            with open(fifo, "wb"):
                pass
        except OSError:
            pass
    _assert_one_shared_deadline(joins, daemon_timeout)
    setup.destroy(handle)


def test_read_home_tree_refuses_past_the_file_count_bound(base: Path, docker_state: Path) -> None:
    """Control (#106's own acceptance, in the spirit of #102): never
    silently truncate a population that is too large - refuse instead."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000019")
    for i in range(3):
        backend.deliver_home_file(handle, f".claude/projects/f{i}.jsonl", b"x")
    with pytest.raises(d.HomeTreeTooLarge):
        backend.read_home_tree(handle, ".claude/projects", max_files=2)
    backend.destroy(handle)


def test_read_home_tree_refuses_past_the_byte_bound(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-00000000001a")
    backend.deliver_home_file(handle, ".claude/projects/big.jsonl", b"x" * 100)
    with pytest.raises(d.HomeTreeTooLarge):
        backend.read_home_tree(handle, ".claude/projects", max_bytes=10)
    backend.destroy(handle)


def test_read_home_tree_on_a_dead_container_is_empty_not_an_error(base: Path, docker_state: Path) -> None:
    """Deliberately NOT the same contract as `read_home_file` (its own dead-
    container test expects `BackendUnavailable`): the fake CLI (and real
    `docker cp`) report a destroyed container and a merely-missing directory
    through the SAME `No such container:path` shape, with no reliable way
    to tell them apart from the caller's side - and a caller here already
    treats both as "found nothing" identically (`agent_trial.py`'s own
    exactly-one-file check reports UNKNOWN either way), so there is nothing
    to gain by trying to distinguish them."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-00000000001b")
    backend.destroy(handle)
    assert backend.read_home_tree(handle, ".claude/projects") == {}


def test_execute_resolves_an_absolute_workspace_path_in_argv(base: Path, docker_state: Path) -> None:
    """Regression (#81, in the fake CLI fixture itself): the fake's `cwd=`
    change resolves a RELATIVE path, but does nothing for an absolute one -
    `verify.py`'s own probe invocation convention passes an absolute path
    (`/work/probe.py`), which failed with "No such file or directory"
    against the pre-fix fake even though the file genuinely existed in the
    container's own simulated filesystem. Fails on the pre-fix fixture."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000008c")
    backend.install(handle, {"probe.py": b"print('ran via absolute path')\n"})
    result = backend.execute(handle, [sys.executable, d.CONTAINER_WORKSPACE + "/probe.py"], Limits(timeout=5))
    assert result.reason == "exited"
    assert result.exit_code == 0
    backend.destroy(handle)


def test_execute_delivers_stdin_like_a_bare_host_process(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000008")
    backend.install(handle, {})
    script = "import sys, pathlib; pathlib.Path('in.txt').write_bytes(sys.stdin.buffer.read())"
    result = backend.execute(
        handle, [sys.executable, "-c", script], Limits(timeout=5), stdin=b"hello from the test",
    )
    assert result.reason == "exited"
    assert result.exit_code == 0
    dest = docker_state.parent / "stdin-export"
    backend.export(handle, dest)
    assert (dest / "in.txt").read_bytes() == b"hello from the test"
    backend.destroy(handle)


def test_execute_writes_the_subjects_stdout_back_as_observations(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Regression (#81): `verify.py`'s own documented convention (#76,
    `_probe_via_backend`'s docstring) is that a probe-serving backend
    captures the exec'd process's stdout to a file named `observations` at
    the workspace root, so it survives `export()`. This backend threw the
    exec'd process's stdout away entirely (`stdout=subprocess.DEVNULL`) until
    #81's demo command tried to grade a real candidate through it and every
    probe "produced no report" despite exiting 0 with a real report on its
    own stdout. Fails on the pre-fix code (no `observations` file at all)."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000008b")
    backend.install(handle, {})
    result = backend.execute(handle, [sys.executable, "-c", "print('probe report text')"], Limits(timeout=5))
    assert result.reason == "exited"
    assert result.exit_code == 0
    dest = tmp_path / "export"
    backend.export(handle, dest)
    assert (dest / "observations").read_text(encoding="utf-8").strip() == "probe report text"
    assert result.observations_capture == "written"
    backend.destroy(handle)


def test_a_directory_symlink_at_observations_makes_the_writeback_fail_visibly(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Red case (issue #186): a subject that pre-creates `/work/observations`
    as a symlink to a directory makes the write-back's tar extraction fail
    with `IsADirectoryError` - measured directly against the fake CLI
    (`docker cp -` exits 1, traceback on stderr). Before this fix, that
    failure was swallowed entirely: `check=False`, the result never
    inspected, no `ExecuteResult` field existed to report it at all - this
    assertion fails on pre-#186 code with `AttributeError: 'ExecuteResult'
    object has no attribute 'observations_capture'`, not merely a wrong
    value. The subject's own directory survives untouched; the real capture
    never lands."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000022")
    backend.install(handle, {})
    script = (
        "import os\n"
        "os.makedirs('elsewhere', exist_ok=True)\n"
        "os.symlink('elsewhere', 'observations')\n"
        "print('real capture')\n"
    )
    # The suite's fake-CLI budget, not 5 s (#412): the subject exits at once
    # (0.20-0.22 s measured), and this test's property is that the write-back
    # failure is VISIBLE, not any timing. A 5 s limit read `timeout` on CI 806.
    result = backend.execute(handle, [sys.executable, "-c", script], Limits(timeout=FAKE_DOCKER_DAEMON_TIMEOUT))
    assert result.reason == "exited"
    assert result.exit_code == 0
    assert result.observations_capture == "failed"
    dest = tmp_path / "export"
    backend.export(handle, dest)
    assert not (dest / "observations").is_file()  # the subject's own object, never the real capture
    backend.destroy(handle)


def test_execute_bounds_captured_stdout_and_keeps_draining_past_the_cap(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Red case (#102): the pre-fix drain appended every chunk to an
    unbounded `list[bytes]` with no cap at all, so a subject that writes
    continuously could exhaust the HOST controller's own memory before
    `limits.timeout` ever fires - a resource-exhaustion path independent of
    any container-side memory limit.

    This subject writes 200,000 bytes - comfortably more than an OS pipe's
    buffer (typically 64 KiB) - while `max_captured_stdout_bytes` is set to
    100: if the drain stopped CONSUMING the pipe once past the cap (rather
    than only stopping RETENTION), the subject's own `write()` would block on
    the now-full, undrained pipe, and this call would time out instead of
    the subject exiting cleanly - the deadlock this fix exists to prevent."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000021")
    backend.install(handle, {})
    script = "import sys; sys.stdout.buffer.write(b'x' * 200_000); sys.stdout.flush()"
    result = backend.execute(
        handle, [sys.executable, "-c", script], Limits(timeout=5, max_captured_stdout_bytes=100),
    )
    assert result.reason == "exited", "a full undrained pipe would time out the subject instead - it must not"
    assert result.exit_code == 0
    assert result.stdout_truncated is True
    assert result.stdout_bytes == 200_000
    dest = tmp_path / "export"
    backend.export(handle, dest)
    assert len((dest / "observations").read_bytes()) == 100
    backend.destroy(handle)


def test_execute_does_not_report_truncation_under_the_cap(base: Path, docker_state: Path) -> None:
    """Green case beside the red one: a subject that stays under the cap
    must report `stdout_truncated=False` and its own true byte count -
    proves the flag is not simply always set."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000022")
    backend.install(handle, {})
    result = backend.execute(
        handle, [sys.executable, "-c", "print('short')"], Limits(timeout=5, max_captured_stdout_bytes=100),
    )
    assert result.stdout_truncated is False
    assert result.stdout_bytes == len(b"short\n")
    backend.destroy(handle)


def test_execute_bounds_captured_stderr_and_keeps_draining_past_the_cap(
    base: Path, docker_state: Path,
) -> None:
    """Red case (orchestrator review of PR #109): the identical unbounded
    pattern #102 fixed for stdout also applied to stderr, one screen down -
    a subject flooding stderr could exhaust the HOST controller's own memory
    exactly as #102 describes for stdout, and (separately) a naive fix that
    stopped CONSUMING the pipe at the cap would deadlock the same way stdout
    could. This subject writes 200,000 bytes to stderr - comfortably more
    than an OS pipe's buffer - then exits 1 so `ExecuteResult.error` is
    actually populated."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000023")
    backend.install(handle, {})
    script = "import sys; sys.stderr.buffer.write(b'x' * 200_000); sys.exit(1)"
    result = backend.execute(
        handle, [sys.executable, "-c", script], Limits(timeout=5, max_captured_stderr_bytes=100),
    )
    assert result.reason == "exited", "a full undrained stderr pipe would time out the subject instead - it must not"
    assert result.exit_code == 1
    # Explicit, not a silently shown prefix (orchestrator's own wording):
    # a caller reading `error` alone must be told it is not the whole message.
    assert result.error is not None
    assert result.error.endswith("(truncated, 200000 bytes total)")
    assert len(result.error) < 300, "the retained prefix itself must still be bounded, not the whole 200,000 bytes"
    backend.destroy(handle)


def test_execute_does_not_annotate_stderr_truncation_under_the_cap(base: Path, docker_state: Path) -> None:
    """Green case beside the red one: an ordinary error message under the
    cap must not gain a truncation suffix - proves the annotation is not
    simply always appended."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000024")
    backend.install(handle, {})
    script = "import sys; sys.stderr.write('a short error'); sys.exit(1)"
    result = backend.execute(
        handle, [sys.executable, "-c", script], Limits(timeout=5, max_captured_stderr_bytes=100),
    )
    assert result.error == "a short error"
    backend.destroy(handle)


@needs_setsid
@pytest.mark.skipif(shutil.which("cat") is None, reason="needs cat to block the detached grandchild on a FIFO")
@pytest.mark.parametrize("delays", [{}, {"exec": 1.5}], ids=["nominal", "slow-exec"])
def test_execute_reports_stdout_incomplete_when_the_drain_never_reaches_eof(
    base: Path, docker_state: Path, tmp_path: Path, delays: dict[str, float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case for issue #133 item 3: the pre-fix code read
    `stdout_drain.captured_bytes()` unconditionally after `stdout_thread.join(
    timeout=...)`, whether or not that join actually confirmed the thread had
    finished - so a subject that exits while leaving a descendant holding the
    pipe open (`ExecuteResult`'s own docstring already named this gap) was
    silently reported as a complete, non-truncated capture.

    The subject uses `setsid` to detach a grandchild into its own session
    before exiting itself - real, not simulated: `os.killpg` (`_stop`'s own
    kill path) cannot reach a process outside its group, and the shell exits
    almost immediately, so `reason` is `"exited"`, not `"timeout"`. The
    grandchild blocks in `open()` reading a FIFO nothing has opened for
    writing yet - a POSIX FIFO open-for-read blocks until a writer shows up,
    so "never reaches EOF" holds by construction, not by racing a fixed
    sleep against `grace`/`daemon_timeout` (issue #174: the prior version
    used a real `sleep 8`, which flaked under host load because the margin
    between 8s and the join bound was itself timing, not a guarantee). The
    `finally` block opens the FIFO for writing so the grandchild is released
    and exits cleanly instead of leaking a process; it runs whether or not
    the assertions below it pass. Fails on the pre-fix code (pre-#164),
    which reported `stdout_truncated=False` here - indistinguishable from a
    clean, complete, empty capture.

    Issue #382: the joins' shared deadline used to be checked with an
    absolute `elapsed < 3.5` ceiling, ~1s above the ~2.46s the fixed code
    takes, and a loaded runner crossed it (push pipeline 457: 3.92s). The
    join shape is now asserted directly (`_assert_one_shared_deadline`),
    which host load cannot move. `slow-exec` delays the fake `docker exec`
    by 1.5s; it failed the old ceiling and passes this assertion."""
    grace, daemon_timeout = 0.5, 5.0
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_slowed_docker_bin(docker_state, tmp_path, delays),
        daemon_timeout=daemon_timeout,
    )
    handle = backend.prepare("a-lc-000000000024b")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    fifo = tmp_path / "hold-open.fifo"
    os.mkfifo(fifo)
    argv = ["sh", "-c", f"setsid sh -c 'exec cat {fifo}' </dev/null & true"]
    joins = _spy_on_drain_joins(monkeypatch)
    try:
        result = backend.execute(handle, argv, Limits(timeout=30, grace=grace))
        assert result.reason == "exited"
        assert result.stdout_incomplete is True
        assert result.stderr_incomplete is True
        assert result.stdout_truncated is False, "capped-and-discarded is a different fact from never-reached-EOF"
        # A bounded first join is "gave up instead of waiting for the
        # detached grandchild"; a zero second join is "one shared deadline".
        _assert_one_shared_deadline(joins, grace + daemon_timeout)
    finally:
        try:
            with open(fifo, "wb"):
                pass
        except OSError:
            pass
    backend.destroy(handle)


@needs_setsid
@pytest.mark.skipif(shutil.which("cat") is None, reason="needs cat to block the detached grandchild on a FIFO")
def test_stdout_and_stderr_incomplete_report_independently_under_the_shared_join_deadline(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """issue #20 Nit Store: joining stdout/stderr against ONE shared
    deadline (instead of each against its own full bound, sequentially)
    must not collapse `stdout_incomplete`/`stderr_incomplete` into one
    combined fact - each stream's completeness is still its own,
    independently observed truth. Only the grandchild's STDOUT stays open
    here (its own stderr fd is closed, `2>&-`, before it blocks on the
    FIFO), so only `stdout_incomplete` should read True."""
    grace, daemon_timeout = 1.0, 1.0
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state), daemon_timeout=daemon_timeout,
    )
    handle = backend.prepare("a-lc-000000000024c2")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    fifo = tmp_path / "hold-open.fifo"
    os.mkfifo(fifo)
    argv = ["sh", "-c", f"setsid sh -c 'exec cat {fifo} 2>&-' </dev/null & true"]
    try:
        result = backend.execute(handle, argv, Limits(timeout=5, grace=grace))
        assert result.reason == "exited"
        assert result.stdout_incomplete is True
        assert result.stderr_incomplete is False
    finally:
        try:
            with open(fifo, "wb"):
                pass
        except OSError:
            pass
    backend.destroy(handle)


def test_execute_does_not_report_incomplete_for_an_ordinary_subject(base: Path, docker_state: Path) -> None:
    """Green case beside the red one: a subject with no lingering descendant
    must report both streams complete - proves the flag is not simply always
    set once a join carries a timeout at all."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000024c")
    backend.install(handle, {})
    result = backend.execute(
        handle, [sys.executable, "-c", "print('short')"], Limits(timeout=5),
    )
    assert result.stdout_incomplete is False
    assert result.stderr_incomplete is False
    backend.destroy(handle)


def test_execute_timeout_kills_the_container_and_confirm_stopped_agrees(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000009")
    backend.install(handle, {})
    result = backend.execute(
        handle, [sys.executable, "-c", "import time; time.sleep(60)"],
        Limits(timeout=0.3, grace=1.0),
    )
    assert result.reason == "timeout"
    assert result.signal in ("SIGTERM", "SIGKILL")
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.CONFIRMED


def test_a_container_level_kill_does_not_reach_the_execd_subject_but_still_kills_it(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """Fake-fidelity fix, and #158's own acceptance red case for free: before
    this fix, `fake_docker.py`'s `cmd_kill` signaled the exec'd subject's
    real pid with the REQUESTED signal directly (`os.killpg(exec_pid, SIG)`)
    - no real Docker daemon forwards its own requested signal to a sibling
    `docker exec` session that way (issue #158's whole premise). Against
    the pre-fix fake, this test's first assertion FAILS: the fake delivered
    a graceful TERM to the subject when no real daemon would, so the fake
    was more capable than the system it stands in for, and #158's own
    acceptance criterion (a red case proving the pre-fix subject never
    receives TERM) could not be shown against it at all.

    Fixed, in two passes (see fake_docker.py's own `cmd_kill` docstring for
    the full reasoning; the first pass here modeled `kill` as a bare status
    flip touching nothing, which is ALSO wrong - a real container's PID 1
    dying still triggers a kernel PID-namespace teardown that SIGKILLs
    every other process in it, exec sessions included, so the subject does
    not survive a container-level kill either, even though it is never
    forwarded a graceful signal). `cmd_kill` now flips status to "exited"
    AND `os.killpg`s the recorded `exec_pid` with SIGKILL always - never
    the requested `--signal` - modeling the kernel's own teardown rather
    than a forwarded signal.
    """
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state), daemon_timeout=1.0,
    )
    handle = backend.prepare("a-lc-000000000030")
    backend.install(handle, {})
    sentinel = tmp_path / "term-received"
    pidfile = tmp_path / "subject-pid"
    script = (
        "import os, signal, sys, time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
        "def handler(signum, frame):\n"
        f"    open({str(sentinel)!r}, 'w').write('term')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, handler)\n"
        "time.sleep(20)\n"
    )
    result = backend.execute(
        handle, [sys.executable, "-c", script], Limits(timeout=0.3, grace=1.0),
    )
    assert result.reason == "timeout"
    assert not sentinel.exists(), (
        "the exec'd subject received a graceful TERM from a container-level "
        "kill - no real Docker daemon forwards its own requested signal that way (#158)"
    )
    assert pidfile.exists(), "the subject never started - the test proves nothing"
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # dead - a real container's PID-1 teardown does not spare it either

    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.CONFIRMED


def _alive(pid: int) -> bool:
    """`os.kill(pid, 0)` alone reads a zombie as alive: a SIGKILLed process
    keeps its pid until its PARENT reaps it. Same idiom as
    `tests/test_verify.py`/`tests/test_trial.py`."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); read its state instead.
    try:
        state = Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0]
    except OSError:
        return False
    return state != "Z"


def _dies_within(pid: int, seconds: float) -> bool:
    """SIGKILL delivery is asynchronous: the target must still be scheduled
    to exit. Poll to a deadline instead of reading one instant."""
    deadline = time.monotonic() + seconds
    while _alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.mark.parametrize("parent_stopped", [False, True], ids=["parent-running", "parent-stopped"])
def test_removing_a_container_without_a_preceding_kill_still_reaps_a_live_exec_session(
    base: Path, docker_state: Path, tmp_path: Path, parent_stopped: bool,
) -> None:
    """Separate test for the remove path (issue #158 fidelity fix, second
    pass): `DockerBackend` itself always issues a `docker kill` before
    `docker rm -f` (`execute()`'s own unconditional kill after a normal
    exit, or `_stop()`'s escalation on timeout/cancellation), so exercising
    `DockerBackend` alone would never independently prove `cmd_rm`'s own
    reaping - `cmd_kill`'s new reaping would always get there first. This
    drives the fake CLI directly, bypassing `DockerBackend`'s own automatic
    kill entirely, to prove `rm -f` alone - with no preceding `kill` at all
    - still reaps a live exec'd session, exactly as real container removal
    does."""
    backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state), daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT)
    handle = backend.prepare("a-lc-000000000031")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})

    pidfile = tmp_path / "subject-pid"
    script = f"import os, time\nopen({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(20)\n"
    exec_argv = [*backend.docker_bin, "exec", "-w", d.CONTAINER_WORKSPACE, "--", handle.name, sys.executable, "-c", script]
    exec_proc = subprocess.Popen(exec_argv, env=handle.env)
    try:
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pidfile.exists(), "the exec'd subject never started - the test proves nothing"
        pid = int(pidfile.read_text())
        os.kill(pid, 0)  # alive - never touched by any docker kill call in this test

        if parent_stopped:
            os.kill(exec_proc.pid, signal.SIGSTOP)
        backend.destroy(handle)  # rm -f, with no preceding docker kill at all

        # Killed, not necessarily reaped: the subject is the fake `docker
        # exec` process's child, so it stays a zombie until that parent's
        # `proc.wait()` runs. Under CI load that lag made a bare
        # `os.kill(pid, 0)` read the killed subject as alive (push pipelines
        # 457 and 759). `parent-stopped` holds the parent so the zombie
        # persists deterministically; a subject `rm -f` never signals still
        # sleeps 20s and fails the 5s deadline.
        assert _dies_within(pid, 5), f"subject {pid} survived container removal"
        assert backend.confirm_absent(handle) is Confirmation.CONFIRMED
    finally:
        if parent_stopped:
            os.kill(exec_proc.pid, signal.SIGCONT)
        exec_proc.kill()
        exec_proc.wait(timeout=5)


def test_a_late_exec_cleanup_never_resurrects_a_removed_container(tmp_path: Path) -> None:
    """Issue #382 (found on a serial run): the fake `docker exec`'s cleanup
    (`_rewrite_state` clearing `exec_pid`) and `docker rm -f` (`cmd_rm`) are
    separate OS processes. `cmd_rm` used to unlink the state file WITHOUT the
    per-name lock, so a cleanup that had already read the file wrote it back
    after the removal - resurrecting the container, which `confirm_absent()`
    then honestly reported as NOT_CONFIRMED (the
    `test_removing_a_container_without_a_preceding_kill_still_reaps_a_live_exec_session`
    red). Reproduced deterministically by holding the cleanup open between
    its read and its write while `rm -f` runs."""
    spec = importlib.util.spec_from_file_location("fake_docker_under_test", FAKE_DOCKER)
    assert spec is not None and spec.loader is not None
    fake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fake)
    state_dir, name = tmp_path / "state", "skillc-a-resurrect"
    state_dir.mkdir()
    fake._write_state(state_dir, name, "running", "fake-image:1", {}, {}, "id-1")
    fake._container_root(state_dir, name).mkdir(parents=True)
    cleanup_has_read, release_cleanup = threading.Event(), threading.Event()

    def clear_exec_pid_slowly(data: dict[str, object]) -> dict[str, object]:
        cleanup_has_read.set()
        release_cleanup.wait(timeout=5)
        return {k: v for k, v in data.items() if k != "exec_pid"}

    cleanup = threading.Thread(target=fake._rewrite_state, args=(state_dir, name, clear_exec_pid_slowly))
    cleanup.start()
    try:
        assert cleanup_has_read.wait(timeout=5), "the cleanup never read the state file - the test proves nothing"
        remover = threading.Thread(target=fake.cmd_rm, args=(state_dir, ["-f", name]))
        remover.start()
    finally:
        release_cleanup.set()
        cleanup.join(timeout=10)
    remover.join(timeout=10)
    assert not cleanup.is_alive() and not remover.is_alive()
    assert not fake._state_file(state_dir, name).exists(), "a late exec cleanup resurrected the removed container"


def test_execute_never_prefixes_the_argv_when_the_image_lacks_forwarding_support(
    base: Path, docker_state: Path,
) -> None:
    """Red case 3 (issue #158): every image today lacks skillc-wrap - the
    #78 Dockerfile change is HELD - so `_forwarding_available`'s probe must
    find nothing, the exec argv must never be prefixed with it, and
    `ExecuteResult.term_forwarding` must say so explicitly rather than
    leaving a caller to guess from an ordinary-looking result. Against
    pre-#158 code this fails outright: `ExecuteResult` has no
    `term_forwarding` attribute at all."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000034")
    backend.install(handle, {})
    result = backend.execute(handle, [sys.executable, "-c", "print('hello')"], Limits(timeout=5))
    assert result.reason == "exited"
    assert result.exit_code == 0
    assert result.term_forwarding == "unavailable-in-image"
    backend.destroy(handle)


def test_execute_never_prefixes_the_argv_when_no_supervisor_is_actually_running(
    base: Path, docker_state: Path,
) -> None:
    """Red case for the capability gate itself (review must-fix, PR #182):
    an image can carry `skillc-wrap`'s binary WITHOUT a running supervisor
    - exactly every real image today, since `_keepalive_run_argv` never
    starts the supervisor in this PR (`prepare()` always starts the plain
    `sleep infinity` placeholder; that switch belongs with the held image
    change - see docs/specs/evaluation-facility/signal-forwarding.md
    section 7). A probe that checked only the wrap binary's executable bit
    would report "available" here and prefix the argv onto a wrapper that
    can never reach anything, turning every stop into
    `killed-at-escalation` - forwarding this backend can never actually
    produce. Fails against the wrap-binary-only probe (this PR's own first
    draft): it finds the binary sentinel and stops looking, so it reports
    something other than `unavailable-in-image` here."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000036")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    (docker_state / f".supervisor-{handle.name}").touch()  # binary present...
    # ...but no .supervisor-running-{name} sentinel: no live control socket,
    # exactly like every real image today.

    result = backend.execute(handle, [sys.executable, "-c", "print('hello')"], Limits(timeout=5))
    assert result.reason == "exited"
    assert result.term_forwarding == "unavailable-in-image"
    backend.destroy(handle)


@pytest.mark.parametrize(
    "delays,subject_delay,stall_first_poll",
    [({}, 0.0, False), ({}, 1.0, False), ({"exec": 1.0}, 0.0, False), ({}, 0.0, True)],
    ids=["nominal", "slow-subject", "slow-exec", "stalled-first-poll"],
)
def test_execute_forwards_term_through_a_capable_image_and_reports_exited_within_grace(
    base: Path, docker_state: Path, tmp_path: Path, delays: dict[str, float], subject_delay: float,
    stall_first_poll: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Red case 1 (issue #158): with the fake's "supervisor present and
    survives TERM" mode fully on (BOTH `.supervisor-NAME` - the binary - AND
    `.supervisor-running-NAME` - a live control socket, review must-fix on
    PR #182: the binary alone is not enough, since `_keepalive_run_argv`
    never starts the supervisor in this PR), the capability probe finds
    both, `execute()` prefixes the exec argv with `skillc-wrap`, and the
    container-level TERM `_stop()` sends on timeout reaches the subject for
    real - its own SIGTERM handler runs and it exits before the SIGKILL
    escalation. Against pre-#158 code this fails: there is no capability
    probe, the argv is never prefixed, and the subject - having no
    supervisor to relay anything - never receives TERM at all (the
    companion red case
    `test_a_container_level_kill_does_not_reach_the_execd_subject_but_still_kills_it`,
    above, is exactly that scenario without either sentinel).

    Issue #382: the timeout (0.3s) used to fire whenever it fired, so on a
    loaded runner TERM could arrive before the subject installed its
    handler, or before the fake `docker exec` had registered it for
    forwarding - either way the sentinel was never written (push pipeline
    457). TERM is now held until both have happened. `execute()`'s wait loop
    polls `cancel`; this test's `cancel` blocks until the subject is ready
    and then returns False, so the stop is deferred, not changed - the run
    still ends as `reason == "timeout"`. The loop checks its deadline BEFORE
    `cancel`, so a controller descheduled past the deadline would skip the
    gate (Codex review of #382): `docker_backend`'s clock is therefore held
    still for the duration of `_launch_and_wait` until the gate opens, and
    the real timeout runs from there. `slow-subject` delays the handler by
    1s, `slow-exec` delays the fake exec's registration by 1s - both failed
    the old test - and `stalled-first-poll` stalls 2.5s straight after the
    deadline is computed, which skips the gate without the held clock.
    `grace` (10s) and the suite-default `daemon_timeout` only bound how long
    a slow host may take; nothing here passes faster for being given more."""
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_slowed_docker_bin(docker_state, tmp_path, delays),
        daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT,
    )
    handle = backend.prepare("a-lc-000000000035")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    (docker_state / f".supervisor-{handle.name}").touch()
    (docker_state / f".supervisor-running-{handle.name}").touch()

    sentinel = tmp_path / "term-received"
    ready = tmp_path / "subject-ready"
    script = (
        "import os, signal, sys, time\n"
        f"time.sleep({subject_delay!r})\n"
        "def handler(signum, frame):\n"
        f"    open({str(sentinel)!r}, 'w').write('term')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, handler)\n"
        f"open({str(ready)!r} + '.tmp', 'w').write(str(os.getpid()))\n"
        f"os.replace({str(ready)!r} + '.tmp', {str(ready)!r})\n"
        "time.sleep(60)\n"
    )
    state_file = docker_state / f"{handle.name}.json"
    gate = {"open": False, "gave_up": False}
    gate_deadline = time.monotonic() + 30
    real_monotonic = time.monotonic
    clock: dict[str, float | None] = {"held_at": None}
    held_reads = [0]

    def monotonic() -> float:
        held_at = clock["held_at"]
        if held_at is None:
            return real_monotonic()
        held_reads[0] += 1
        if stall_first_poll and held_reads[0] == 2:
            time.sleep(2.5)  # descheduled between computing the deadline and checking it
        return held_at

    real_launch_and_wait = d.DockerBackend._launch_and_wait

    def launch_and_wait_on_held_clock(self: d.DockerBackend, *args: Any, **kwargs: Any) -> Any:
        clock["held_at"] = real_monotonic()
        try:
            return real_launch_and_wait(self, *args, **kwargs)
        finally:
            clock["held_at"] = None

    monkeypatch.setattr(d, "time", types.SimpleNamespace(monotonic=monotonic, sleep=time.sleep))
    monkeypatch.setattr(d.DockerBackend, "_launch_and_wait", launch_and_wait_on_held_clock)

    def hold_term_until_forwardable() -> bool:
        """Block until the handler is installed AND the fake has registered
        this subject for forwarding, then never cancel."""
        while not gate["open"]:
            try:
                pid = int(ready.read_text(encoding="utf-8"))
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                state, pid = {}, None
            if state.get("supervisor_registered") is True and state.get("exec_pid") == pid:
                gate["open"] = True
                clock["held_at"] = None  # release the clock: the real timeout runs from here
            elif time.monotonic() >= gate_deadline:
                gate["gave_up"] = True
                return True  # stop the run; the assertion below names why
            else:
                time.sleep(0.01)
        return False

    result = backend.execute(
        handle, [sys.executable, "-c", script], Limits(timeout=0.3, grace=10.0),
        cancel=hold_term_until_forwardable,
    )
    assert not gate["gave_up"], (
        "the subject never became forwardable within 30s - no installed handler, or never registered "
        "with the supervisor; this is not the forwarding claim failing"
    )
    assert gate["open"], "the timeout fired before the readiness gate was ever consulted - TERM was not held"
    assert result.reason == "timeout"
    assert sentinel.exists(), "the subject should have received a real, forwarded TERM"
    assert result.signal == "SIGTERM"
    assert result.term_forwarding == "exited-within-grace"
    backend.destroy(handle)


def test_execute_cancellation_kills_the_container(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000010")
    backend.install(handle, {})
    result = backend.execute(
        handle, [sys.executable, "-c", "import time; time.sleep(60)"],
        Limits(timeout=30, grace=1.0), cancel=lambda: True,
    )
    assert result.reason == "operator-cancelled"
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED
    backend.destroy(handle)


def test_execute_reports_launch_failed_when_the_docker_binary_is_missing(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000011")
    backend.install(handle, {})
    broken = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=["/nonexistent/docker-binary-xyz"], daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT,
    )
    result = broken.execute(handle, ["true"], Limits(timeout=1))
    assert result.reason == "launch-failed"
    assert result.exit_code is None
    assert result.error is not None
    # #158: the capability probe fails the same way the exec itself just
    # did (both go through the same missing binary), so this is the common
    # real case for a launch-failed term_forwarding, not the residual
    # genuinely-unmeasured None - see ExecuteResult.term_forwarding's own
    # docstring.
    assert result.term_forwarding == "unavailable-in-image"
    backend.destroy(handle)


def test_a_second_execute_against_an_already_stopped_handle_is_refused_not_fabricated(
    base: Path, docker_state: Path,
) -> None:
    """THE RED CASE for #304. `execute()`'s own contract always stops the
    container before returning (its docstring), so a second call against
    the same handle used to fall through to a real `docker exec` the
    daemon rejects - a genuine nonzero exit that read as an ordinary
    `reason="exited", exit_code=1`, fabricating a second execution that
    never touched the container. The fix refuses instead, with the same
    `attempt-not-running` reason `exec_in_attempt()` already uses for this
    exact situation."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000012")
    backend.install(handle, {})
    first = backend.execute(handle, ["true"], Limits(timeout=5.0))
    assert first.reason == "exited" and first.exit_code == 0
    second = backend.execute(handle, ["true"], Limits(timeout=5.0))
    assert second.reason == "attempt-not-running"
    assert second.exit_code is None
    backend.destroy(handle)


def _home(docker_state: Path, handle: d._Handle) -> Path:
    return docker_state / f"{handle.name}.fsroot" / d.CONTAINER_HOME.lstrip("/")


def _ready(base: Path, docker_state: Path, attempt_id: str) -> tuple[d.DockerBackend, d._Handle]:
    backend = _backend(base, docker_state)
    handle = backend.prepare(attempt_id)
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    return backend, handle


_DAEMON_WORDING = "Error response from daemon: container is not running"
_Events = list[tuple[int, str, str | None]]


def test_exec_in_attempt_reports_launch_failed_when_the_docker_binary_is_missing(
    base: Path, docker_state: Path,
) -> None:
    """#550 item 3: an unknown container state is not a confirmed stop."""
    backend, handle = _ready(base, docker_state, "a-exec-550-missing")
    broken = d.DockerBackend(
        image="fake-image:1", base_dir=base,
        docker_bin=["/nonexistent/docker-binary-xyz"],
        daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT,
    )
    try:
        result = broken.exec_in_attempt(handle, ["true"], Limits(timeout=1))
        assert result.reason == "launch-failed"
        assert result.exit_code is None
        assert result.error is not None
    finally:
        backend.destroy(handle)


@pytest.mark.parametrize("state", ["created", "exited", "absent"])
def test_exec_in_attempt_refuses_a_confirmed_nonrunning_container(
    base: Path, docker_state: Path, state: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opposite verdict: a reachable inspect must still refuse known stops."""
    backend, handle = _ready(base, docker_state, "a-exec-550-stopped")
    def unexpected_launch(*args: object, **kwargs: object) -> None:
        pytest.fail("a confirmed nonrunning container must be refused before launch")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(d.DockerBackend, "_inspect", lambda *_: (True, state == "absent", state))
            patch.setattr(d.DockerBackend, "_launch_and_wait", unexpected_launch)
            result = backend.exec_in_attempt(handle, ["true"], Limits(timeout=1))
        assert (result.reason, result.exit_code) == ("attempt-not-running", None)
    finally:
        backend.destroy(handle)


def test_exec_in_attempt_refuses_to_launch_after_an_unreachable_inspect(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown state must never turn a daemon rejection into gate coverage."""
    backend, handle = _ready(base, docker_state, "a-exec-550-unknown")

    def unexpected_launch(*args: object, **kwargs: object) -> None:
        pytest.fail("an unknown container state must be refused before launch")

    try:
        monkeypatch.setattr(d.DockerBackend, "_inspect", lambda *_: (False, False, None))
        monkeypatch.setattr(d.DockerBackend, "_launch_and_wait", unexpected_launch)
        result = backend.exec_in_attempt(handle, ["true"], Limits(timeout=5))
        assert (result.reason, result.exit_code) == ("launch-failed", None)
        assert result.error is not None and "unknown" in result.error
    finally:
        backend.destroy(handle)


def test_exec_in_attempt_reports_not_started_when_the_daemon_is_down(
    base: Path, docker_state: Path,
) -> None:
    """#644 review control: a running CLI can fail before any gate starts."""
    backend, handle = _ready(base, docker_state, "a-exec-550-daemon-down")
    _sentinel(docker_state, ".down")
    try:
        result = backend.exec_in_attempt(handle, ["true"], Limits(timeout=5))
        assert (result.reason, result.exit_code) == ("launch-failed", None)
        assert result.error is not None and "unknown" in result.error
    finally:
        (docker_state / ".down").unlink()
        backend.destroy(handle)


def _edit_events(monkeypatch: pytest.MonkeyPatch, edit: Callable[[_Events, int], _Events | None]) -> None:
    """Feed the decision a doctored copy of the fake daemon's REAL event answer
    (buffer loss, format drift) - the edit receives the window start."""
    real = d.DockerBackend._exec_events

    def doctored(self: d.DockerBackend, handle: d._Handle, since_ns: int) -> _Events | None:
        events = real(self, handle, since_ns)
        return None if events is None else edit(events, since_ns)

    monkeypatch.setattr(d.DockerBackend, "_exec_events", doctored)


def test_execute_reports_a_daemon_refused_exec_as_attempt_not_running(base: Path, docker_state: Path) -> None:
    """#317 red case: the container stops between execute()'s entry inspect
    and the real exec (`.stop-before-exec-NAME`, deterministic), so the daemon
    refuses it. Before the fix that read as an ordinary nonzero `exited`; now
    the daemon's own record - this call's probe exec, then the die, and no
    exec carrying this call's token - reports it as never started."""
    backend, handle = _ready(base, docker_state, "a-lc-000000000013")
    _sentinel(docker_state, f".stop-before-exec-{handle.name}")
    result = backend.execute(handle, ["true"], Limits(timeout=5.0))
    assert (result.reason, result.exit_code) == ("attempt-not-running", None)
    backend.destroy(handle)


@pytest.mark.parametrize("code", [0, 3])
def test_execute_on_a_running_container_is_unchanged(base: Path, docker_state: Path, code: int) -> None:
    backend, handle = _ready(base, docker_state, f"a-lc-00000000017{code}")
    result = backend.execute(handle, ["sh", "-c", f"printf out; printf err >&2; exit {code}"], Limits(timeout=5.0))
    assert (result.reason, result.exit_code) == ("exited", code)
    assert (result.stdout, result.stderr) == (b"out", b"err")
    backend.destroy(handle)


def test_a_subject_that_ran_and_then_stopped_its_container_keeps_its_result(
    base: Path, docker_state: Path,
) -> None:
    """#317 negative control - the forgery the marker design fell to (the
    container runs with --init, so a subject CAN stop it): the subject really
    ran, printed the daemon's own rejection wording, deleted whatever it liked,
    exited 1, and its container stopped before execute()'s re-check
    (`.stop-after-exec-NAME`). The daemon recorded its exec, so it stands."""
    backend, handle = _ready(base, docker_state, "a-lc-000000000180")
    _sentinel(docker_state, f".stop-after-exec-{handle.name}")
    script = f"rm -rf {d.CONTAINER_HOME}/* 2>/dev/null; echo '{_DAEMON_WORDING}' >&2; exit 1"
    result = backend.execute(handle, ["sh", "-c", script], Limits(timeout=5.0))
    assert (result.reason, result.exit_code) == ("exited", 1)
    assert result.stderr == f"{_DAEMON_WORDING}\n".encode()
    backend.destroy(handle)


def test_the_prelude_leaves_the_subjects_bytes_untouched_even_with_an_unusable_home(
    base: Path, docker_state: Path,
) -> None:
    """Approver condition: nothing of the prelude reaches the subject's
    streams (#334 byte identity), even where its home is not a directory."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000182")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    home = _home(docker_state, handle)
    home.parent.mkdir(parents=True, exist_ok=True)
    home.write_text("not a directory")
    result = backend.execute(handle, ["sh", "-c", "printf 'O\\n'; printf 'E\\n' >&2; exit 1"], Limits(timeout=5.0))
    assert (result.reason, result.exit_code) == ("exited", 1)
    assert (result.stdout, result.stderr) == (b"O\n", b"E\n")
    backend.destroy(handle)


def _probe(command: str | None) -> bool:
    return command is not None and command.startswith(d._FORWARDING_PROBE_COMMAND + " ")


@pytest.mark.parametrize("fault", ["query-fails", "probe-missing", "probe-unparseable", "die-missing",
                                   "die-before-probe", "paused", "another-calls-probe", "exec-unreadable"])
def test_a_refused_exec_without_complete_daemon_proof_keeps_the_real_result(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    """Conservative by construction: every way the daemon's answer can fail to
    PROVE "never started" keeps the pre-#317 shape - a query failure, buffer
    loss at the lower bound (this call's probe event gone, even with an older
    probe event retained), format drift (the probe's command unreadable), the
    die missing, or a status that is not exited/dead."""
    backend, handle = _ready(base, docker_state, f"a-lc-00000000019{len(fault) % 10}")
    _sentinel(docker_state, f".stop-before-exec-{handle.name}")
    if fault == "query-fails":
        monkeypatch.setattr(d.DockerBackend, "_exec_events", lambda self, h, since: None)
    elif fault == "probe-missing":
        # Buffer loss at the lower bound. #426: the real daemon keeps a GLOBAL
        # 256-event ring that evicts oldest-first, so on a busy host the probe
        # is what goes first - this case.
        _edit_events(monkeypatch, lambda ev, since: [e for e in ev if not _probe(e[2])])
    elif fault == "die-before-probe":
        # The only die precedes this call's probe in the daemon's stream: the
        # window does not run through a stop after our launch.
        _edit_events(monkeypatch, lambda ev, since: [
            *[(min(ns for ns, _, c in ev if _probe(c)) - 1, k, c) for _, k, c in ev if k == "die"],
            *[e for e in ev if e[1] != "die"]])
    elif fault == "probe-unparseable":
        _edit_events(monkeypatch, lambda ev, since: [(ns, k, None if _probe(c) else c) for ns, k, c in ev])
    elif fault == "die-missing":
        _edit_events(monkeypatch, lambda ev, since: [e for e in ev if e[1] != "die"])
    elif fault == "another-calls-probe":
        # This call's probe lost; an identical probe from another call (its own
        # token) retained in the window - never this call's lower bound.
        _edit_events(monkeypatch, lambda ev, since: [
            *[e for e in ev if not _probe(e[2])],
            (since + 1, "exec_start", f"{d._FORWARDING_PROBE_COMMAND} {d._FORWARDING_PROBE_TOKEN_PREFIX}another")])
    elif fault == "exec-unreadable":
        # Format drift on ANOTHER exec in the window (its command unreadable):
        # the window cannot prove our token absent.
        _edit_events(monkeypatch, lambda ev, since: [*ev, (since + 1, "exec_start", None)])
    else:
        real_inspect = d.DockerBackend._inspect
        calls = {"n": 0}

        def paused(self: d.DockerBackend, h: d._Handle) -> tuple[bool, bool, str | None]:
            calls["n"] += 1
            return real_inspect(self, h) if calls["n"] == 1 else (True, False, "paused")

        monkeypatch.setattr(d.DockerBackend, "_inspect", paused)
    result = backend.execute(handle, ["true"], Limits(timeout=5.0))
    assert result.reason == "exited" and result.exit_code not in (0, None)
    backend.destroy(handle)


@pytest.mark.parametrize("skew_ns", [-3_600_000_000_000, 3_600_000_000_000])
@pytest.mark.parametrize("refused", [True, False])
def test_the_decision_never_compares_the_daemons_clock_with_the_controllers(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, skew_ns: int, refused: bool,
) -> None:
    """Approver condition: every daemon timestamp shifted an hour either way
    (a daemon on another host) changes neither verdict - the refused exec is
    still never-started, and a subject that ran and stopped its container
    still keeps its result. Ordering is the daemon's own."""
    backend, handle = _ready(base, docker_state, f"a-lc-0000000002{int(refused)}{int(skew_ns > 0)}")
    _sentinel(docker_state, f".{'stop-before' if refused else 'stop-after'}-exec-{handle.name}")
    _edit_events(monkeypatch, lambda ev, since: [(ns + skew_ns, k, c) for ns, k, c in ev])
    argv = ["true"] if refused else ["sh", "-c", f"echo '{_DAEMON_WORDING}' >&2; exit 1"]
    result = backend.execute(handle, argv, Limits(timeout=5.0))
    assert result.reason == ("attempt-not-running" if refused else "exited")
    backend.destroy(handle)


def test_a_token_event_before_the_probe_still_vetoes(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counter-model case: this call's own exec event, readable and in the
    window but timestamped BEFORE the probe event, still proves execution."""
    backend, handle = _ready(base, docker_state, "a-lc-000000000185")
    _sentinel(docker_state, f".stop-before-exec-{handle.name}")
    holder: dict[str, str] = {}
    real_exec_events = d.DockerBackend._exec_events

    def with_token(self: d.DockerBackend, h: d._Handle, since_ns: int) -> _Events | None:
        events = real_exec_events(self, h, since_ns)
        assert events is not None
        probe = next(c for _, k, c in events if _probe(c))
        assert probe is not None
        call_id = probe.rsplit(d._FORWARDING_PROBE_TOKEN_PREFIX, 1)[1]
        holder["token"] = f"{d._EXEC_TOKEN_PREFIX}{call_id}"
        return [(since_ns + 1, "exec_start", f"sh -c exec \"$@\" {holder['token']} true"),
                *[(ns + 10, k, c) for ns, k, c in events]]

    monkeypatch.setattr(d.DockerBackend, "_exec_events", with_token)
    result = backend.execute(handle, ["true"], Limits(timeout=5.0))
    assert holder["token"]
    assert result.reason == "exited"
    backend.destroy(handle)


def test_a_stalled_events_client_cannot_outlive_the_daemon_deadline(base: Path, docker_state: Path) -> None:
    """Counter-model case: an events client that keeps stdout open past the
    deadline is killed, and the answer is "unknown". The bound IS the property
    here: `daemon_timeout` 0.2s against a 3s stall."""
    backend = _backend(base, docker_state, daemon_timeout=0.2)
    handle = backend.prepare("a-lc-000000000186")
    assert isinstance(handle, d._Handle)
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".delay-events").write_text("3")
    started = time.monotonic()
    assert backend._exec_events(handle, 0) is None
    assert time.monotonic() - started < 2.0
    (docker_state / ".delay-events").unlink()
    backend.destroy(handle)


def test_the_exec_events_answer_is_bounded(base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An events answer past the byte bound is "unknown", never buffered whole."""
    backend, handle = _ready(base, docker_state, "a-lc-000000000184")
    backend.execute(handle, ["true"], Limits(timeout=5.0))
    monkeypatch.setattr(d, "_EXEC_EVENTS_MAX_BYTES", 10)
    assert backend._exec_events(handle, 0) is None
    backend.destroy(handle)


def test_confirm_stopped_is_unknown_when_the_daemon_is_unreachable(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000012")
    backend.install(handle, {})
    _sentinel(docker_state, ".down")
    assert backend.confirm_stopped(handle) is Confirmation.UNKNOWN
    assert backend.confirm_absent(handle) is Confirmation.UNKNOWN


def test_confirm_stopped_is_unknown_only_once_the_inspect_delay_exceeds_daemon_timeout(
    base: Path, docker_state: Path,
) -> None:
    """Two-sided negative control for issue #174 (items 1 and 2's shared root
    cause, see the #20 Nit Store comment filed against this issue): every
    `docker inspect` call in `_inspect()` is bounded by `daemon_timeout`, and
    every caller downstream of `confirm_stopped()` (`trial.finalize()`'s
    disposition, `verify.py`'s quarantine) trusts UNKNOWN over a guess. Fault
    injection is via fake_docker.py's own `.inspect-delay-NAME` sentinel
    (file-based, not env-based - see that module's docstring), so this is
    reproduced deterministically, with no host load needed.

    (a) a delay UNDER daemon_timeout still reports the real, CONFIRMED status
    - proves the bound is not simply "always green", i.e. that this check
    actually exercises a live inspect call rather than one that never runs.
    (b) a delay OVER daemon_timeout reports UNKNOWN - proves the fail-closed
    path still works and a wider TEST-only bound elsewhere (see
    conftest.FAKE_DOCKER_DAEMON_TIMEOUT) did not quietly make the timeout
    itself unreachable."""
    daemon_timeout = 2.0
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state), daemon_timeout=daemon_timeout,
    )
    handle = backend.prepare("a-lc-000000000012b")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    backend.execute(handle, [sys.executable, "-c", "print('done')"], Limits(timeout=5))
    # The container must already be genuinely stopped before either side
    # below - otherwise side (a)'s CONFIRMED would not distinguish "read
    # correctly" from "nothing was checked".
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED

    delay_file = docker_state / f".inspect-delay-{handle.name}"
    try:
        delay_file.write_text(str(daemon_timeout - 1.0), encoding="utf-8")
        assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED

        delay_file.write_text(str(daemon_timeout + 1.0), encoding="utf-8")
        assert backend.confirm_stopped(handle) is Confirmation.UNKNOWN
    finally:
        delay_file.unlink(missing_ok=True)
    backend.destroy(handle)


def test_confirm_absent_is_not_confirmed_when_rm_lies(base: Path, docker_state: Path) -> None:
    """Negative control: fake_docker's `.stuck-NAME` sentinel makes `rm -f`
    report success without actually removing the container - confirm_absent()
    must catch that lie via an independent `inspect`, never trust destroy()'s
    own exit code."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000013")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    _sentinel(docker_state, f".stuck-{handle.name}")
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.NOT_CONFIRMED


# ------------------------------------------------------- cross-model review (PR #85)


def test_owned_tar_sets_the_fixed_candidate_ownership_on_every_member(tmp_path: Path) -> None:
    """Regression for a cross-model review finding (PR #85): a plain `docker
    cp HOST_PATH NAME:DEST` preserves the SOURCE's own uid/gid, which could
    be anything on the controller's host - not the fixed candidate identity.
    `install()` instead builds its own tar stream so every member's ownership
    is set explicitly, regardless of the host file's real ownership."""
    surface_dir = tmp_path / "surface"
    surface_dir.mkdir()
    (surface_dir / "a.txt").write_text("a")
    (surface_dir / "sub").mkdir()
    (surface_dir / "sub" / "b.txt").write_text("b")

    payload = d._owned_tar(surface_dir, "skill")
    with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
        members = tar.getmembers()
        assert members
        for member in members:
            assert member.uid == d.CANDIDATE_UID
            assert member.gid == d.CANDIDATE_GID


def test_owned_tar_bytes_sets_the_fixed_candidate_ownership(tmp_path: Path) -> None:
    payload = d._owned_tar_bytes("canary", b"hello")
    with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
        member = tar.getmembers()[0]
        assert member.uid == d.CANDIDATE_UID
        assert member.gid == d.CANDIDATE_GID
        extracted = tar.extractfile(member)
        assert extracted is not None
        assert extracted.read() == b"hello"


def test_handle_env_is_captured_once_at_prepare_time(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for a cross-model review finding (PR #85): prepare() must
    capture the resolved docker connection environment ONCE and every later
    call must reuse it - never re-read `os.environ` per call - so an ambient
    DOCKER_HOST change mid-attempt cannot point confirm_stopped()/export()/
    destroy() at a different daemon than the one prepare() actually used.
    Fails on the pre-fix code, which had no captured env at all (every call
    recomputed `_docker_env()` fresh)."""
    monkeypatch.setenv("DOCKER_HOST", "unix:///original.sock")
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000016")
    assert isinstance(handle, d._Handle)
    assert handle.env.get("DOCKER_HOST") == "unix:///original.sock"
    monkeypatch.setenv("DOCKER_HOST", "unix:///changed-after-prepare.sock")
    assert handle.env.get("DOCKER_HOST") == "unix:///original.sock"
    backend.destroy(handle)


def test_handle_repr_never_leaks_the_connection_environment(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_HOST", "unix:///should-not-appear-in-repr.sock")
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000017")
    assert isinstance(handle, d._Handle)
    assert "should-not-appear-in-repr" not in repr(handle)
    backend.destroy(handle)


@pytest.fixture
def trigger_socket_dir() -> Iterator[Path]:
    """Deliberately NOT nested under pytest's own `tmp_path` - that prefix
    (`/tmp/pytest-of-<user>/pytest-<n>/<test-name-truncated>/...`) is
    already 60-90+ characters on its own, which overflows
    `DecideReplyChannel.start()`'s AF_UNIX safety margin before any
    socket filename is even added (found running this exact test).
    `tempfile.mkdtemp()` creates a short directory directly under the
    system temp root instead, matching `DEFAULT_TRIGGER_SOCKET_DIR`'s own
    reasoning for production. Not the shared default dir either - each
    test gets its own, torn down after."""
    path = Path(tempfile.mkdtemp(prefix="sk-trig-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _trigger_backend(base: Path, docker_state: Path, trigger_socket_dir: Path) -> d.DockerBackend:
    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        return {"decision": "fail" if request.get("client_seq") == 3 else "pass"}
    return d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state), daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT, trigger_decide=decide,
        trigger_socket_dir=trigger_socket_dir,
    )


def _send_trigger_request(sock_path: Path, payload: dict[str, object]) -> dict[str, object]:
    s = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    try:
        s.settimeout(5.0)
        s.connect(str(sock_path))
        s.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        s.shutdown(socket_module.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        s.close()
    result: dict[str, object] = json.loads(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"))
    return result


def test_prepare_without_trigger_decide_has_no_channel_at_all(base: Path, docker_state: Path) -> None:
    """Every caller before #183: no channel, `trigger_log()` reports `None`
    (configuration, not an observation) rather than an empty list."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000020")
    assert isinstance(handle, d._Handle)
    assert handle.trigger_channel is None
    assert backend.trigger_log(handle) is None
    assert "--mount" not in backend._keepalive_run_argv(handle.name, "a-lc-000000000020")
    backend.destroy(handle)


def test_prepare_with_trigger_decide_binds_a_real_socket_before_the_container_starts(
    base: Path, docker_state: Path, trigger_socket_dir: Path,
) -> None:
    """The ordering guarantee `_start_trigger_channel`'s own docstring
    states: by the time `prepare()` returns, the host-side socket already
    exists and is a REAL AF_UNIX socket (not a placeholder regular file),
    at the path `trigger_socket_host_path_for` derives from the attempt's
    container name - never a caller-supplied path."""
    backend = _trigger_backend(base, docker_state, trigger_socket_dir)
    handle = backend.prepare("a-lc-000000000021")
    try:
        assert isinstance(handle, d._Handle)
        assert handle.trigger_channel is not None
        sock_path = d.trigger_socket_host_path_for(backend.trigger_socket_dir, handle.name)
        assert sock_path.exists()
        assert stat.S_ISSOCK(sock_path.stat().st_mode)
        reply = _send_trigger_request(sock_path, {"op": "disruption_check", "client_seq": 1})
        assert reply == {"ok": True, "result": {"decision": "pass"}}
        reply3 = _send_trigger_request(sock_path, {"op": "disruption_check", "client_seq": 3})
        assert reply3 == {"ok": True, "result": {"decision": "fail"}}
    finally:
        log = backend.trigger_log(handle)
        backend.destroy(handle)
    assert log is not None
    assert [entry.result["decision"] for entry in log] == ["pass", "fail"]


def test_prepare_with_trigger_decide_applies_the_declared_socket_mode(
    base: Path, docker_state: Path, trigger_socket_dir: Path,
) -> None:
    """Design doc §2f decision (b): the socket is mode `TRIGGER_SOCKET_MODE`
    (0o666), not `DecideReplyChannel`'s own generic 0o600 default - the
    candidate uid inside the container is essentially never this
    controller process's own uid, so an owner-only socket would make the
    subject's own `connect()` fail with EACCES. GROUP is granted too, not
    just OTHER (cross-model review) - zeroing GROUP
    bought nothing once (a)'s directory is the real boundary. Checked
    directly on the real file `prepare()` created, not merely on the
    constant's value."""
    backend = _trigger_backend(base, docker_state, trigger_socket_dir)
    handle = backend.prepare("a-lc-000000000023")
    try:
        assert isinstance(handle, d._Handle)
        sock_path = d.trigger_socket_host_path_for(backend.trigger_socket_dir, handle.name)
        mode = stat.S_IMODE(sock_path.stat().st_mode)
    finally:
        backend.destroy(handle)
    assert mode == d.TRIGGER_SOCKET_MODE == 0o666


def test_destroy_closes_the_trigger_channel_even_when_the_caller_never_finalized(
    base: Path, docker_state: Path, trigger_socket_dir: Path,
) -> None:
    """A caller that forgets to call `trigger_log()` before tearing down
    must not leak a listening thread - `destroy()`'s own best-effort
    `close()` call (never raises, matching the Protocol's `destroy()`
    contract) - and a LATER `trigger_log()` call must still return the
    (now-finalized) log rather than raising, because `log_or_finalize()`
    is idempotent."""
    backend = _trigger_backend(base, docker_state, trigger_socket_dir)
    handle = backend.prepare("a-lc-000000000022")
    assert isinstance(handle, d._Handle)
    sock_path = d.trigger_socket_host_path_for(backend.trigger_socket_dir, handle.name)
    assert sock_path.exists()
    backend.destroy(handle)  # no trigger_log() call first
    assert not sock_path.exists()
    assert backend.trigger_log(handle) == []  # bypass: never connected


def test_the_trigger_socket_outlives_trigger_log_and_goes_only_after_the_container(
    base: Path, docker_state: Path, trigger_socket_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#394: the gate witness finalizes the channel (`trigger_log()`) right
    after the confirmed stop and BEFORE the capture export. The socket is
    the container's bind-mount source, and real Docker cannot `docker cp`
    out of a stopped container whose source is gone - so finalizing must
    leave the file, and `destroy()` must remove the container before it
    removes the file. (The daemon behaviour itself is proven on real Docker
    in `test_decide_reply_channel_live.py`; the fake CLI has no mounts.)"""
    backend = _trigger_backend(base, docker_state, trigger_socket_dir)
    handle = backend.prepare("a-lc-000000000394")
    assert isinstance(handle, d._Handle)
    sock_path = d.trigger_socket_host_path_for(backend.trigger_socket_dir, handle.name)
    assert backend.trigger_log(handle) == []
    assert sock_path.exists(), "finalizing the log removed the container's bind-mount source"

    seen: dict[str, object] = {}
    real_close = DecideReplyChannel.close

    def spying_close(self: DecideReplyChannel) -> None:
        seen["container_at_close"] = backend.confirm_absent(handle)
        real_close(self)

    monkeypatch.setattr(DecideReplyChannel, "close", spying_close)
    backend.destroy(handle)
    assert seen["container_at_close"] is Confirmation.CONFIRMED
    assert not sock_path.exists()


def test_a_failed_removal_keeps_the_trigger_socket_but_stops_the_listener(
    base: Path, docker_state: Path, trigger_socket_dir: Path,
) -> None:
    """Counter-model finding (#394): when `docker rm -f` does not remove the
    container, its bind source must survive (the container is still there
    and still needs it), while the listener stops. A later `destroy()` that
    does remove it then releases the file."""
    backend = _trigger_backend(base, docker_state, trigger_socket_dir)
    handle = backend.prepare("a-lc-000000000395")
    assert isinstance(handle, d._Handle)
    sock_path = d.trigger_socket_host_path_for(backend.trigger_socket_dir, handle.name)
    _sentinel(docker_state, f".stuck-{handle.name}")
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.NOT_CONFIRMED
    assert sock_path.exists(), "released the bind source of a container that still exists"
    probe = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    try:
        with pytest.raises(ConnectionRefusedError):
            probe.connect(str(sock_path))
    finally:
        probe.close()
    (docker_state / f".stuck-{handle.name}").unlink()
    backend.destroy(handle)
    assert backend.confirm_absent(handle) is Confirmation.CONFIRMED
    assert not sock_path.exists()


def test_confirm_stopped_is_unknown_on_an_unrecognized_inspect_error(
    base: Path, docker_state: Path,
) -> None:
    """Regression for a cross-model review finding (PR #85): docker's own CLI
    uses the SAME non-zero exit code for "no such object" and for other
    daemon-side errors (permission denial, TLS failure, ...) - only an
    explicit "no such" message may be trusted as a confirmed absence. Fails
    on the pre-fix code, which treated any non-zero exit other than "cannot
    connect" as a confirmed absence."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000018")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    _sentinel(docker_state, f".inspect-error-{handle.name}")
    assert backend.confirm_stopped(handle) is Confirmation.UNKNOWN
    assert backend.confirm_absent(handle) is Confirmation.UNKNOWN


def test_prepare_cleans_up_a_container_that_was_created_but_failed_to_start(
    base: Path, docker_state: Path,
) -> None:
    """Regression for a cross-model review finding (PR #85): backend.py's own
    Protocol requires a raising prepare() to own cleanup of whatever it
    already allocated. Docker creates a container before starting it, so a
    start failure can leave one behind now that --rm is dropped from this
    call. Fails on the pre-fix code, which left the orphaned state file in
    place after raising."""
    _sentinel(docker_state, ".refuse-start")
    backend = _backend(base, docker_state)
    with pytest.raises(BackendUnavailable):
        backend.prepare("a-lc-000000000019")
    name = d._container_name("a-lc-000000000019")
    assert not (docker_state / f"{name}.json").exists()


def test_execute_stop_escalation_falls_back_to_killing_the_local_client(
    base: Path, docker_state: Path,
) -> None:
    """Regression for a cross-model review finding (PR #85): if even the
    second `docker kill` leaves the subject running (a stuck daemon, or - as
    simulated here via `.stuck-NAME` - a container that lies about being
    killed), `_stop()` must still reap ITS OWN local docker-exec client
    process directly (SIGKILL, which cannot be blocked or ignored) rather
    than returning with it still running. Fails on the pre-fix code, which
    could leave that local process alive after two TimeoutExpired escalations
    (this test would otherwise hang for the full sleep duration)."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000020")
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    _sentinel(docker_state, f".stuck-{handle.name}")
    result = backend.execute(
        handle, [sys.executable, "-c", "import time; time.sleep(5)"],
        Limits(timeout=0.3, grace=0.3),
    )
    assert result.reason == "timeout"
    assert result.signal == "SIGKILL"
    backend.destroy(handle)


# ------------------------------------------------------- _BoundedDrain (issue #189)


def test_bounded_drain_captures_data_written_before_the_pipe_is_held_open(base: Path) -> None:
    """Red case for issue #189: `run()` used to read with `IO.read(65536)`,
    which on a non-interactive stream may issue multiple underlying reads to
    fill the FULL requested size, blocking until either that much data
    arrives or EOF. A pipe holding fewer than 65536 bytes, kept open
    without more data or a close, therefore never satisfied that call at
    all - `captured_bytes()` stayed empty for the whole run, silently
    discarding data that was genuinely written and available, rather than
    reporting it as an incomplete partial capture (#102's own bounded-
    capture rule, and `ExecuteResult`'s `stdout_incomplete`/`stdout_bytes`
    design, both describe "captured what we could, marked incomplete" -
    never "wrote 10000 bytes, captured zero, no error"). No docker/
    subprocess involved - this drives `_BoundedDrain` directly against a
    real OS pipe, exactly as small as the production case: `execute()`'s
    and `read_home_tree()`'s own drain threads. Fails on the pre-fix code
    (`self._pipe.read(65536)`), which reports 0 bytes captured here while
    the thread is still correctly alive (no EOF yet).

    Both halves of #189's acceptance in ONE assertion (orchestrator
    review), not two separate ones a partial fix could satisfy piecemeal:
    `_BoundedDrain` itself carries no `incomplete` attribute of its own -
    exactly like `execute()`/`read_home_tree()` do it for real,
    `thread.is_alive()` right after a bounded `.join()` IS the incomplete
    signal a caller reads. A fix that captured the bytes but somehow also
    made the thread finish (falsely reading as a COMPLETE capture) would
    fail this same assertion, not just a separate one next to it."""
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "rb")
    drain = d._BoundedDrain(reader, 1_000_000)
    thread = threading.Thread(target=drain.run, daemon=True)
    thread.start()
    try:
        os.write(write_fd, b"x" * 10_000)
        thread.join(timeout=1.5)
        captured = len(drain.captured_bytes())
        assert thread.is_alive() and captured == 10_000, (
            f"both halves of #189's acceptance must hold together: still incomplete "
            f"(thread.is_alive()={thread.is_alive()}) AND the already-written data captured "
            f"before EOF (captured {captured} of 10000 bytes) - not only at EOF"
        )
    finally:
        os.close(write_fd)
        thread.join(timeout=1.0)
    assert thread.is_alive() is False
    assert len(drain.captured_bytes()) == 10_000


def test_bounded_drain_still_drains_fully_to_eof(base: Path) -> None:
    """Positive control beside the red case above: the ordinary EOF path -
    a writer that closes normally - must still capture everything, proving
    the #189 fix (reading with `os.read()` instead of `IO.read()`) did not
    trade "captures partial data early" for "stops draining too soon"."""
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "rb")
    drain = d._BoundedDrain(reader, 1_000_000)
    thread = threading.Thread(target=drain.run, daemon=True)
    thread.start()
    os.write(write_fd, b"y" * 200_000)  # several times the 65536 read size
    os.close(write_fd)
    thread.join(timeout=2.0)
    assert thread.is_alive() is False
    assert len(drain.captured_bytes()) == 200_000
    assert drain.total_bytes == 200_000
    assert drain.truncated is False


# ------------------------------------------------------------------ #332 follow-up: root parameter


def test_install_and_export_respect_a_custom_root(base: Path, docker_state: Path, tmp_path: Path) -> None:
    """#332 follow-up: `root` defaults to `CONTAINER_WORKSPACE` (every
    existing caller, unchanged - covered by every other `install()`/
    `export()` test in this file, none of which pass it), but a caller
    naming a different one (#334's profile closure delivery into the
    agent's home directory, say) must land there instead - never
    silently at `/work` regardless of what was asked for."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000006a")
    assert isinstance(handle, d._Handle)
    readiness = backend.install(handle, {"flow-finish-gate.sh": b"#!/bin/sh\necho real\n"}, root=d.CONTAINER_HOME)
    assert readiness["installed"] == 1

    # Never landed at the DEFAULT root instead.
    assert not (docker_state / f"{handle.name}.fsroot" / "work" / "flow-finish-gate.sh").exists()
    assert (docker_state / f"{handle.name}.fsroot" / "home" / "candidate" / "flow-finish-gate.sh").read_bytes() == (
        b"#!/bin/sh\necho real\n"
    )

    dest = tmp_path / "export-home"
    backend.export(handle, dest, root=d.CONTAINER_HOME)
    assert (dest / "flow-finish-gate.sh").read_bytes() == b"#!/bin/sh\necho real\n"
    backend.destroy(handle)


def test_write_root_owned_file_in_attempt_writes_root_owned_content(base: Path, docker_state: Path) -> None:
    """#332 follow-up: the gate-witness harness copy of the real script
    must land somewhere the candidate identity cannot write - never
    through `install()`'s own candidate-owned tar convention. This
    fixture has no real per-uid permission model (every `exec` here runs
    a REAL subprocess as whatever host user runs the test suite - see
    `cmd_exec`'s own `-u` comment - and `_remap_absolute` only rewrites
    the two KNOWN container prefixes, `/work` and `/home/candidate`, so
    an arbitrary path like the real `/opt/skillc-harness` would hit the
    actual host filesystem and fail on a real permission error having
    nothing to do with this method). Using a path under the workspace
    prefix instead proves the MECHANICS this method owns (content lands
    at the given path, with the given mode, under a directory this call
    itself creates) - genuine uid-based write-protection, and the real
    harness path, are owed to the real-Docker runner, matching `resolve_
    realpath_in_attempt`'s own documented limitation."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000006b")
    assert isinstance(handle, d._Handle)
    ok = backend.write_root_owned_file_in_attempt(
        handle, f"{d.CONTAINER_WORKSPACE}/skillc-harness/flow-finish-gate.sh",
        b"#!/bin/sh\necho real\n", mode=0o750,
    )
    assert ok is True
    written = docker_state / f"{handle.name}.fsroot" / "work" / "skillc-harness" / "flow-finish-gate.sh"
    assert written.read_bytes() == b"#!/bin/sh\necho real\n"
    assert stat.S_IMODE(written.stat().st_mode) == 0o750
    backend.destroy(handle)


def test_write_root_owned_file_in_attempt_returns_false_not_raises_for_an_unreachable_container(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000006c")
    backend.destroy(handle)
    assert backend.write_root_owned_file_in_attempt(handle, "/opt/skillc-harness/x.sh", b"x") is False


def test_candidate_can_write_in_attempt_true_for_a_writable_path(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000006d")
    backend.install(handle, {"writable.txt": b"x\n"})
    writable_path = f"{d.CONTAINER_WORKSPACE}/writable.txt"
    assert backend.candidate_can_write_in_attempt(handle, writable_path) is True
    backend.destroy(handle)


def test_candidate_can_write_in_attempt_false_for_a_nonexistent_path(base: Path, docker_state: Path) -> None:
    """A clean `test -w` failure (no stderr) on a path that simply does not
    exist - distinct from the unreachable-container case below, which
    carries real stderr and must read as UNKNOWN, never a confident
    `False`."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000006e")
    assert backend.candidate_can_write_in_attempt(handle, f"{d.CONTAINER_WORKSPACE}/does-not-exist") is False
    backend.destroy(handle)


def test_candidate_can_write_in_attempt_is_unknown_not_false_for_an_unreachable_container(
    base: Path, docker_state: Path,
) -> None:
    """Mutation-check target for the stderr-sensitivity itself: a naive
    implementation that reads ANY nonzero exit as `False` would wrongly
    report this unreachable-container case as a confident "not writable"
    instead of UNKNOWN - caught here because the fake CLI's own "No such
    container" error writes to stderr, exactly like a real daemon's
    equivalent failure would."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000006f")
    backend.destroy(handle)
    assert backend.candidate_can_write_in_attempt(handle, "/work/whatever") is None


def test_clean_write_probe_result_direct() -> None:
    """Counter-model review finding, exercised directly with synthetic
    (returncode, stderr) pairs - no subprocess or Docker needed, matching
    this module's own `_PropertyHeld`-family precedent elsewhere in this
    session for pinning an exact boundary: a signal-killed exec (137 for
    SIGKILL) can leave stderr empty while exiting outside `test`'s own
    `{0, 1}` vocabulary, and must read as UNKNOWN, never a confident
    `False`."""
    f = d._clean_write_probe_result
    assert f(0, b"") is True
    assert f(1, b"") is False
    assert f(137, b"") is None  # signal-killed, empty stderr - the red case
    assert f(1, b"\n") is None  # whitespace-only stderr still counts as "something happened"
    assert f(0, b"some daemon warning\n") is None
    # Mutation check: a naive version that reads ANY nonzero exit (with no
    # stderr) as a confident False would disagree with the real function
    # on exactly the 137 case - proving this red case is not inert.
    def naive(returncode: int, stderr: bytes) -> bool | None:
        if stderr.strip():
            return None
        return returncode == 0
    assert naive(137, b"") is False, "the naive version should disagree with the real function here"


# ------------------------------------------------- #338: cwd TOCTOU confinement


def _real_dir(docker_state: Path, handle: d._Handle, *container_parts: str) -> Path:
    """The fake CLI's own `_in_container()` convention, duplicated here
    (not imported - that fixture is invoked as a subprocess script, never
    as a module) so a test can plant or swap a real directory BEFORE the
    exec that should observe it, exactly at the path `_remap_absolute`
    will resolve the matching container-side string to."""
    return docker_state / f"{handle.name}.fsroot" / Path(*container_parts)


def _confined_handle(base: Path, docker_state: Path, attempt_id: str) -> tuple[d.DockerBackend, d._Handle]:
    backend = _backend(base, docker_state)
    handle = backend.prepare(attempt_id)
    assert isinstance(handle, d._Handle)
    backend.install(handle, {})
    return backend, handle


def _observations(backend: d.DockerBackend, handle: d._Handle) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        backend.export(handle, Path(tmp))
        return (Path(tmp) / "observations").read_text()


_SUB = f"{d.CONTAINER_WORKSPACE}/trial/sub"


def _readlink_shim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """Puts a `readlink` first on the PATH the fake container inherits. The
    confining wrapper runs `readlink` exactly once, AFTER it has opened the
    cwd as fd 9 and BEFORE it checks or moves - so `body` runs at exactly
    that point, deterministically, with no timing race: the place a subject
    swapping the path mid-check would have to act."""
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir()
    real = shutil.which("readlink")
    assert real is not None
    shim = shim_dir / "readlink"
    shim.write_text(f'#!/bin/sh\n{body}\nexec {real} "$@"\n')
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")


def test_exec_in_attempt_confine_root_runs_the_gate_at_the_resolved_cwd(
    base: Path, docker_state: Path,
) -> None:
    """The functional happy path: the gate's own `/proc/self/cwd` (what an
    exec'd child really inherits) is the requested directory."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000001")
    sub = _real_dir(docker_state, handle, "work", "trial", "sub")
    sub.mkdir(parents=True)

    result = backend.exec_in_attempt(
        handle, ["sh", "-c", "readlink /proc/self/cwd"], Limits(timeout=5.0),
        cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (result.reason, result.exit_code) == ("exited", 0)
    assert _observations(backend, handle).strip() == str(sub.resolve())


def test_exec_in_attempt_confine_root_moves_physically_not_to_the_proc_fd_string(
    base: Path, docker_state: Path,
) -> None:
    """`cd -P`, not a logical `cd`: a logical `cd /proc/self/fd/9` leaves
    `PWD=/proc/self/fd/9` exported to the gate (red against the parked
    wrapper, which used a plain `cd`) - a path that names nothing once the
    fd closes, and something else entirely inside any later process."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000012")
    sub = _real_dir(docker_state, handle, "work", "trial", "sub")
    sub.mkdir(parents=True)

    result = backend.exec_in_attempt(
        handle, ["printenv", "PWD"], Limits(timeout=5.0), cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (result.reason, result.exit_code) == ("exited", 0)
    assert _observations(backend, handle).strip() == str(sub.resolve())


def test_exec_in_attempt_confine_root_closes_the_fd_before_the_gate_runs(
    base: Path, docker_state: Path,
) -> None:
    """The confinement fd must not leak into the gate: it lives on the
    compound command's redirection and closes when that block ends."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000002")
    _real_dir(docker_state, handle, "work", "trial", "sub").mkdir(parents=True)

    result = backend.exec_in_attempt(
        handle, ["sh", "-c", "test -e /proc/self/fd/9 && echo LEAKED || echo CLOSED"], Limits(timeout=5.0),
        cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert result.exit_code == 0
    assert _observations(backend, handle).strip() == "CLOSED"


def test_exec_in_attempt_confine_root_refuses_a_directory_swapped_for_an_outside_symlink(
    base: Path, docker_state: Path,
) -> None:
    """The deterministic red case (#338 point 3): resolve-time said the
    directory was inside; by exec time it is a symlink to a sibling OUTSIDE
    the root. The wrapper's one open lands on the outside target and the
    check against the open directory refuses it."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000003")
    outside = _real_dir(docker_state, handle, "home", "candidate", "outside")
    outside.mkdir(parents=True)
    sub = _real_dir(docker_state, handle, "work", "trial", "sub")
    sub.mkdir(parents=True)

    shutil.rmtree(sub)
    sub.symlink_to(outside, target_is_directory=True)

    result = backend.exec_in_attempt(
        handle, ["sh", "-c", "touch ran-here"], Limits(timeout=5.0), cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (result.reason, result.exit_code) == ("launch-failed", None)
    assert result.error == d.CWD_CONFINEMENT_REFUSED_SENTINEL
    assert not (outside / "ran-here").exists()


def test_exec_in_attempt_confine_root_refuses_an_ancestor_swapped_for_an_outside_symlink(
    base: Path, docker_state: Path,
) -> None:
    """The issue's other named shape: not the directory itself but an
    ANCESTOR (`trial`) replaced by a symlink, with a same-named `sub`
    waiting on the far side."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000006")
    outside = _real_dir(docker_state, handle, "home", "candidate", "outside")
    (outside / "sub").mkdir(parents=True)
    trial = _real_dir(docker_state, handle, "work", "trial")
    (trial / "sub").mkdir(parents=True)

    shutil.rmtree(trial)
    trial.symlink_to(outside, target_is_directory=True)

    result = backend.exec_in_attempt(
        handle, ["sh", "-c", "touch ran-here"], Limits(timeout=5.0), cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (result.reason, result.error) == ("launch-failed", d.CWD_CONFINEMENT_REFUSED_SENTINEL)
    assert not (outside / "sub" / "ran-here").exists()


def test_exec_in_attempt_confine_root_uses_the_opened_directory_not_the_name(
    base: Path, docker_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Correction 1: once the wrapper has opened and checked a directory,
    a swap of the NAME must not change where the gate runs. The shim swaps
    `sub` for an outside symlink after the open and before the check and
    the move; the gate must still land in the original directory (now
    `sub.orig`), never at the swapped target. Red against any wrapper that
    goes back to the name for the move (`cd "$1"`)."""
    outside_marker = tmp_path / "outside-target"
    outside_marker.mkdir()
    sub_holder = tmp_path / "sub-path.txt"
    _readlink_shim(
        tmp_path, monkeypatch,
        f'sub=$(cat {sub_holder})\n'
        f'if [ ! -e "$sub.orig" ]; then mv "$sub" "$sub.orig" && ln -s {outside_marker} "$sub"; fi',
    )
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000007")
    sub = _real_dir(docker_state, handle, "work", "trial", "sub")
    sub.mkdir(parents=True)
    sub_holder.write_text(str(sub))

    result = backend.exec_in_attempt(
        handle, ["sh", "-c", "touch ran-here; readlink /proc/self/cwd"], Limits(timeout=5.0),
        cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert sub.is_symlink(), "the shim must actually have swapped the name, or this test proves nothing"
    assert (result.reason, result.exit_code) == ("exited", 0)
    assert not (outside_marker / "ran-here").exists()
    assert (Path(f"{sub}.orig") / "ran-here").exists()
    assert _observations(backend, handle).strip() == str(sub.parent.resolve() / "sub.orig")


def test_exec_in_attempt_without_confine_root_follows_the_swapped_symlink(
    base: Path, docker_state: Path,
) -> None:
    """The vulnerability itself, on the unchanged `cwd`-only path (`docker
    exec -w`): the identical swap the refusal test above refuses is
    silently FOLLOWED here, landing the gate outside the workspace root."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000004")
    workspace_root = _real_dir(docker_state, handle, "work")
    outside = _real_dir(docker_state, handle, "home", "candidate", "outside")
    outside.mkdir(parents=True)
    sub = workspace_root / "trial" / "sub"
    sub.mkdir(parents=True)

    shutil.rmtree(sub)
    sub.symlink_to(outside, target_is_directory=True)

    result = backend.exec_in_attempt(
        handle, ["sh", "-c", "readlink -f /proc/self/cwd"], Limits(timeout=5.0), cwd=_SUB,
    )
    assert (result.reason, result.exit_code) == ("exited", 0)
    reported_cwd = _observations(backend, handle).strip()
    assert reported_cwd == str(outside.resolve())
    assert not reported_cwd.startswith(str(workspace_root.resolve()))


def test_exec_in_attempt_confine_root_refuses_a_sibling_named_root_plus_newline(
    base: Path, docker_state: Path,
) -> None:
    """Command substitution strips trailing newlines, so a check that
    compared `$(readlink ...)` directly would read a sibling directory
    named "<root>\\n" as the root itself. The wrapper keeps the newline
    (a trailing `.` sentinel), so that sibling - outside the root - is
    refused."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000014")
    _real_dir(docker_state, handle, "work", "trial").mkdir(parents=True)
    sibling = _real_dir(docker_state, handle, "work", "trial\n")
    sibling.mkdir()

    result = backend.exec_in_attempt(
        handle, ["sh", "-c", "touch ran-here"], Limits(timeout=5.0),
        cwd=f"{d.CONTAINER_WORKSPACE}/trial\n", confine_root=f"{d.CONTAINER_WORKSPACE}/trial",
    )
    assert (result.reason, result.error) == ("launch-failed", d.CWD_CONFINEMENT_REFUSED_SENTINEL)
    assert not (sibling / "ran-here").exists()


@pytest.mark.parametrize("shape", ["missing", "regular-file"])
def test_exec_in_attempt_confine_root_refuses_a_cwd_that_is_not_a_directory(
    base: Path, docker_state: Path, shape: str,
) -> None:
    """Gone, or a regular file where a directory was: the open (missing) or
    the physical `cd` (file) fails, and both refuse exactly like an
    outside-root swap - with only the wrapper's record on stderr, dash's
    own "cannot open" diagnostic never reaching the caller."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000005")
    trial = _real_dir(docker_state, handle, "work", "trial")
    trial.mkdir(parents=True)
    if shape == "regular-file":
        (trial / "sub").write_text("not a directory\n")

    result = backend.exec_in_attempt(
        handle, ["sh", "-c", "echo should-not-run"], Limits(timeout=5.0), cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (result.reason, result.exit_code) == ("launch-failed", None)
    assert result.error == d.CWD_CONFINEMENT_REFUSED_SENTINEL


def test_exec_in_attempt_confine_root_keeps_stdin_env_exit_and_output(
    base: Path, docker_state: Path,
) -> None:
    """Correction 4, non-racing: confinement changes where the gate starts
    and nothing else. stdin reaches it, `env` replaces its environment,
    stdout is captured, its own non-zero exit and stderr are reported as
    the gate's - with the wrapper's status record removed from that
    stderr."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000008")
    _real_dir(docker_state, handle, "work", "trial", "sub").mkdir(parents=True)

    result = backend.exec_in_attempt(
        handle,
        ["sh", "-c", 'read line; printf "%s|%s|%s\\n" "$line" "$GATE_VAR" "${PATH:-unset}"; echo gate-err >&2; exit 7'],
        Limits(timeout=5.0), stdin=b"from-stdin\n", cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
        env={"GATE_VAR": "declared", "PATH": "/usr/bin:/bin"},
    )
    assert (result.reason, result.exit_code) == ("exited", 7)
    assert result.error == "gate-err"
    assert _observations(backend, handle) == "from-stdin|declared|/usr/bin:/bin\n"


@pytest.mark.parametrize("exit_code", [0, 3])
def test_exec_in_attempt_reports_the_gates_raw_stderr_on_every_exit(
    base: Path, docker_state: Path, exit_code: int,
) -> None:
    """#334: `stderr` is the gate's own bytes on every exit - whitespace and
    trailing newline kept, the wrapper's status record removed - while
    `error` stays the stripped nonzero-exit summary. Before the fix there
    was no raw field, so a forwarder could only read `error`: None on exit
    0, newline lost on exit 3."""
    backend, handle = _confined_handle(base, docker_state, f"a-cwd-0000000002{exit_code}")
    _real_dir(docker_state, handle, "work", "trial", "sub").mkdir(parents=True)

    result = backend.exec_in_attempt(
        handle, ["sh", "-c", f"printf '  progress\\nWARNING: skipped\\n' >&2; exit {exit_code}"],
        Limits(timeout=5.0), cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (result.reason, result.exit_code) == ("exited", exit_code)
    assert result.stderr == b"  progress\nWARNING: skipped\n"
    assert result.stderr_truncated is False
    assert result.error == (None if exit_code == 0 else "progress\nWARNING: skipped")

    capped = backend.exec_in_attempt(
        handle, ["sh", "-c", "printf 0123456789 >&2"], Limits(timeout=5.0, max_captured_stderr_bytes=4),
        cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (capped.stderr, capped.stderr_truncated) == (b"0123", True)


def test_exec_in_attempt_confine_root_gate_printing_a_refusal_is_still_the_gates_result(
    base: Path, docker_state: Path,
) -> None:
    """Correction 2's red case: a gate that prints the refusal record AND
    the refusal sentinel and exits 125 - the wrapper's own refusal code -
    ran, and must be reported as having run. Red against the parked
    implementation, which matched the sentinel anywhere in stderr and
    returned `launch-failed` for this."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000009")
    _real_dir(docker_state, handle, "work", "trial", "sub").mkdir(parents=True)
    spoof = d.CWD_CONFINEMENT_REFUSED_RECORD.decode().strip()

    result = backend.exec_in_attempt(
        handle,
        ["sh", "-c", f"echo {spoof} >&2; echo {d.CWD_CONFINEMENT_REFUSED_SENTINEL} >&2; touch ran; exit 125"],
        Limits(timeout=5.0), cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (result.reason, result.exit_code) == ("exited", 125)
    assert result.error == f"{spoof}\n{d.CWD_CONFINEMENT_REFUSED_SENTINEL}"
    assert (_real_dir(docker_state, handle, "work", "trial", "sub") / "ran").exists()


def test_exec_in_attempt_confine_root_status_survives_a_zero_stderr_cap(
    base: Path, docker_state: Path,
) -> None:
    """The status record is captured apart from the gate's retained stderr,
    so a cap of 0 cannot cost a refusal - and the gate's own capped stderr
    still reports its truncation against the gate's bytes alone."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000010")
    _real_dir(docker_state, handle, "work", "trial", "sub").mkdir(parents=True)

    refused = backend.exec_in_attempt(
        handle, ["true"], Limits(timeout=5.0, max_captured_stderr_bytes=0),
        cwd=f"{d.CONTAINER_WORKSPACE}/missing", confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (refused.reason, refused.error) == ("launch-failed", d.CWD_CONFINEMENT_REFUSED_SENTINEL)

    capped = backend.exec_in_attempt(
        handle, ["sh", "-c", "printf 0123456789 >&2; exit 3"], Limits(timeout=5.0, max_captured_stderr_bytes=4),
        cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (capped.reason, capped.exit_code) == ("exited", 3)
    assert capped.error == "0123 (truncated, 10 bytes total)"


def test_exec_in_attempt_confine_root_missing_status_is_neither_refusal_nor_a_run(
    base: Path, docker_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrapper that dies before writing any status record (here: killed
    from inside its own check) leaves the call with no evidence either way
    from the wrapper - reported as not started, but as MISSING status,
    never as the refusal and never as a gate result."""
    # Kill the OUTERMOST `sh` ancestor running the confining script - the
    # wrapper itself, not a `$(...)` subshell copy of it, whichever way
    # the shell happens to fork.
    _readlink_shim(
        tmp_path, monkeypatch,
        'pid=$PPID; target=\n'
        'while [ "$pid" -gt 1 ]; do\n'
        '  if [ "$(cat /proc/$pid/comm)" = sh ] && tr "\\0" " " </proc/$pid/cmdline | grep -q skillc-cwd-confinement; then\n'
        '    target=$pid\n'
        '  fi\n'
        '  pid=$(cut -d" " -f4 /proc/$pid/stat)\n'
        'done\n'
        'kill -9 "$target"',
    )
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000011")
    _real_dir(docker_state, handle, "work", "trial", "sub").mkdir(parents=True)

    result = backend.exec_in_attempt(
        handle, ["sh", "-c", "touch ran"], Limits(timeout=5.0), cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert (result.reason, result.exit_code) == ("launch-failed", None)
    assert result.error == d.CWD_CONFINEMENT_STATUS_MISSING
    assert not (_real_dir(docker_state, handle, "work", "trial", "sub") / "ran").exists()


def test_exec_in_attempt_timeout_under_confinement_still_confirms_the_stop(
    base: Path, docker_state: Path,
) -> None:
    """Correction 4: a confined gate that hangs is still a timeout, its
    in-container process still confirmed stopped - the status record does
    not turn an interrupted run into anything else."""
    backend, handle = _confined_handle(base, docker_state, "a-cwd-00000000013")
    _real_dir(docker_state, handle, "work", "trial", "sub").mkdir(parents=True)

    result = backend.exec_in_attempt(
        handle, ["sleep", "30"], Limits(timeout=0.5, grace=1.0), cwd=_SUB, confine_root=d.CONTAINER_WORKSPACE,
    )
    assert result.reason == "timeout"
    assert result.stop_confirmed is True


def _status_of(payload: bytes, cap: int = 1_000_000) -> tuple[str, bytes, int]:
    read_fd, write_fd = os.pipe()
    drain = d._BoundedDrain(os.fdopen(read_fd, "rb"), cap, d.CWD_CONFINEMENT_RECORD_MAX)
    os.write(write_fd, payload)
    os.close(write_fd)
    drain.run()
    return d._confinement_status(drain), drain.captured_bytes(), drain.total_bytes


@pytest.mark.parametrize(
    ("payload", "status", "captured"),
    [
        (d.CWD_CONFINEMENT_READY_RECORD + b"gate-err\n", "ready", b"gate-err\n"),
        (d.CWD_CONFINEMENT_REFUSED_RECORD, "refused", b""),
        (b"", "missing", b""),
        (b"skillc-cwd-confinement:rea", "invalid", b""),  # cut short at EOF
        (b"Error response from daemon: boom\n" + d.CWD_CONFINEMENT_REFUSED_RECORD, "invalid",
         d.CWD_CONFINEMENT_REFUSED_RECORD),  # something else came first
        (b"x" * 200, "invalid", b"x" * (200 - d.CWD_CONFINEMENT_RECORD_MAX)),  # no newline within the bound
        (d.CWD_CONFINEMENT_READY_RECORD[:-1] + b" \n", "invalid", b""),  # near miss is not a match
    ],
    ids=["ready", "refused", "empty", "partial", "other-text-first", "overlong", "near-miss"],
)
def test_confinement_status_reads_only_an_exact_bounded_leading_record(
    payload: bytes, status: str, captured: bytes,
) -> None:
    got_status, got_captured, total = _status_of(payload)
    assert got_status == status
    assert got_captured == captured
    assert total == len(captured), "the record is never counted as the gate's output"


def test_bounded_drain_status_record_is_outside_the_retention_cap() -> None:
    status, captured, total = _status_of(d.CWD_CONFINEMENT_READY_RECORD + b"abcdef", cap=2)
    assert (status, captured, total) == ("ready", b"ab", 6)


# ---------------------------------------------------- remove_file_in_attempt


def test_remove_file_in_attempt_removes_the_observations_write_back(base: Path, docker_state: Path) -> None:
    """skillc#334. `exec_in_attempt()`'s own shared tail
    (`_finish_result`, #76/#186) writes the exec'd process's stdout back to
    `CONTAINER_WORKSPACE/observations` after EVERY call, unconditionally -
    confirmed here directly, not assumed: a plain SECOND `exec_in_attempt()`
    call that deletes the file from inside the container does not leave it
    absent, because that call's own (empty) stdout immediately write-backs
    a fresh, empty file in its place. `remove_file_in_attempt` is the only
    one of the two that leaves the file genuinely gone, because it never
    goes through that tail at all."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-rm-0000000000001")
    backend.install(handle, {})
    try:
        first = backend.exec_in_attempt(handle, ["python3", "-c", "print('report')"], Limits(timeout=5.0))
        assert first.exit_code == 0
        with tempfile.TemporaryDirectory() as tmp:
            backend.export(handle, Path(tmp))
            assert (Path(tmp) / "observations").read_text() == "report\n"

        # The defect this fix exists to avoid, shown directly: deleting the
        # file through a second exec_in_attempt() call does not work.
        second = backend.exec_in_attempt(
            handle, ["python3", "-c", f"import os; os.remove({d.CONTAINER_WORKSPACE + '/observations'!r})"],
            Limits(timeout=5.0),
        )
        assert second.exit_code == 0
        with tempfile.TemporaryDirectory() as tmp:
            backend.export(handle, Path(tmp))
            # Recreated empty by the SECOND call's own write-back - not absent.
            assert (Path(tmp) / "observations").read_text() == ""

        removed = backend.remove_file_in_attempt(handle, f"{d.CONTAINER_WORKSPACE}/observations")
        assert removed is True
        with tempfile.TemporaryDirectory() as tmp:
            backend.export(handle, Path(tmp))
            assert not (Path(tmp) / "observations").exists()
    finally:
        backend.destroy(handle)


def test_remove_file_in_attempt_on_a_path_that_never_existed_is_still_true(
    base: Path, docker_state: Path,
) -> None:
    """`rm -f` alone reports success even when nothing existed - the
    confirming `[ ! -e ]` is what makes a `True` here mean "checked and
    absent", not merely "the remove command did not error"."""
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-rm-0000000000002")
    backend.install(handle, {})
    try:
        assert backend.remove_file_in_attempt(handle, f"{d.CONTAINER_WORKSPACE}/never-existed") is True
    finally:
        backend.destroy(handle)


def test_a_fake_setup_call_slower_than_the_production_daemon_timeout_still_succeeds(
    base: Path, docker_state: Path,
) -> None:
    """Regression for issue #385: the test above failed in SETUP on a loaded
    host, its fake `docker run -d` timing out after production's 5s
    `DAEMON_TIMEOUT` - a bound for a real daemon, not for a fake CLI that is
    a fresh Python process per call. `_backend()` now builds every fake
    backend with `conftest.FAKE_DOCKER_DAEMON_TIMEOUT`. The slow host is
    reproduced by construction (`.delay-run`), never by load. Fails on the
    pre-fix `_backend()` with `BackendUnavailable` from `prepare()`."""
    delay = d.DAEMON_TIMEOUT + 1.0
    assert delay < FAKE_DOCKER_DAEMON_TIMEOUT
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".delay-run").write_text(str(delay), encoding="utf-8")
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-rm-0000000000385")
    backend.install(handle, {})
    try:
        assert backend.remove_file_in_attempt(handle, f"{d.CONTAINER_WORKSPACE}/never-existed") is True
    finally:
        backend.destroy(handle)


#: Issue #416's tests make the fake daemon slower than prepare()'s bound by
#: construction. 3.0s against 2.0s is a deliberately wide 1.5x ratio (#412's
#: timing family): the bound must fire on the delayed subcommand, and the
#: undelayed probe and image check must still finish inside it on a loaded host.
_PREPARE_BOUND = 2.0
_SLOWER_THAN_BOUND = 3.0


def _slow(docker_state: Path, subcommand: str) -> None:
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / f".delay-{subcommand}").write_text(str(_SLOWER_THAN_BOUND), encoding="utf-8")


def test_prepare_still_raises_backend_unavailable_when_the_cleanup_rm_also_times_out(
    base: Path, docker_state: Path,
) -> None:
    """Regression for issue #416: `run -d` times out, then the best-effort
    `rm -f` cleanup times out too. On the pre-fix code the cleanup's own
    `TimeoutExpired` escaped prepare() raw instead of the `BackendUnavailable`
    its contract promises. The match is on the run-failure text, so a probe
    that times out first under load cannot pass this by the wrong route."""
    _slow(docker_state, "run")
    _slow(docker_state, "rm")
    backend = _backend(base, docker_state, daemon_timeout=_PREPARE_BOUND)
    attempt_id = "a-416-run-timeout-01"
    with pytest.raises(BackendUnavailable, match="docker run failed to start") as caught:
        backend.prepare(attempt_id)
    message = str(caught.value)
    assert f"cleanup 'docker rm -f {d._container_name(attempt_id)}' also failed" in message
    assert "timed out" in message
    cause = caught.value.__cause__
    assert isinstance(cause, subprocess.TimeoutExpired)
    assert "run" in cause.cmd  # the start failure stays the cause, not the cleanup's


def test_prepare_still_raises_backend_unavailable_when_a_refused_run_is_followed_by_a_timed_out_rm(
    base: Path, docker_state: Path,
) -> None:
    """#416's second path: `run -d` exits nonzero, and its cleanup times out."""
    _sentinel(docker_state, ".refuse-run")
    _slow(docker_state, "rm")
    backend = _backend(base, docker_state, daemon_timeout=_PREPARE_BOUND)
    attempt_id = "a-416-run-refused-01"
    with pytest.raises(BackendUnavailable, match="container creation refused") as caught:
        backend.prepare(attempt_id)
    assert f"cleanup 'docker rm -f {d._container_name(attempt_id)}' also failed" in str(caught.value)


@pytest.mark.parametrize("start_failure", ["run-timeout", "run-refused"])
def test_a_cleanup_rm_that_exits_nonzero_is_reported_in_both_paths(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, start_failure: str,
) -> None:
    """#416 (counter-model review): a cleanup that FAILS, not only one that
    times out, must reach the message. Only the cleanup's `rm -f` is replaced
    with a daemon error; every other call still goes to the fake CLI."""
    if start_failure == "run-timeout":
        _slow(docker_state, "run")
    else:
        _sentinel(docker_state, ".refuse-run")
    real_run = subprocess.run

    def daemon_refuses_rm(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if list(argv[-3:-1]) == ["rm", "-f"]:
            return subprocess.CompletedProcess(argv, 1, "", "Cannot connect to the Docker daemon\n")
        return real_run(argv, **kwargs)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr(d.subprocess, "run", daemon_refuses_rm)
    backend = _backend(base, docker_state, daemon_timeout=_PREPARE_BOUND)
    attempt_id = f"a-416-rm-nonzero-{start_failure}"
    with pytest.raises(BackendUnavailable, match="docker run failed to start") as caught:
        backend.prepare(attempt_id)
    message = str(caught.value)
    assert f"cleanup 'docker rm -f {d._container_name(attempt_id)}' also failed: exit 1" in message
    assert "Cannot connect to the Docker daemon" in message


def test_a_cleanup_that_succeeds_adds_no_cleanup_note(base: Path, docker_state: Path) -> None:
    """Control for #416: with only `run` slow, the cleanup succeeds and the
    message carries no cleanup clause, so the two tests above are reading the
    cleanup's failure, not text every failed prepare() would contain."""
    _slow(docker_state, "run")
    backend = _backend(base, docker_state, daemon_timeout=_PREPARE_BOUND)
    with pytest.raises(BackendUnavailable, match="docker run failed to start") as caught:
        backend.prepare("a-416-control-00001")
    # The clause the fix adds, not the bare word: the message carries the run's
    # argv, whose paths can contain "cleanup" (this branch's own worktree did).
    assert "also failed" not in str(caught.value)


def _late_create(docker_state: Path, delay: float) -> None:
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".late-create-run").write_text(str(delay), encoding="utf-8")


def _await_late_create(docker_state: Path, name: str, budget: float = 10.0) -> None:
    """The fake's detached create runs on its own clock; wait until it has
    landed, so an absence read afterwards is final rather than early."""
    marker = docker_state / f".late-created-{name}"
    deadline = time.monotonic() + budget
    while not marker.exists():
        assert time.monotonic() < deadline, f"the fake's late create for {name} never landed"
        time.sleep(0.05)


def test_a_timed_out_run_whose_create_lands_late_leaves_no_container(base: Path, docker_state: Path) -> None:
    """Regression for issue #540: `run -d` passes its bound while the daemon
    is still creating the container. The pre-fix prepare() killed the CLI and
    removed the name at once, found "No such container", and returned - and
    the create landed afterwards, leaving a never-started container (kyle19's
    `skillc-a-live-conformance-fbba8d601e10`). Fails on the pre-fix code: the
    `created` record is still there once the late create has landed."""
    _late_create(docker_state, _SLOWER_THAN_BOUND)
    backend = _backend(base, docker_state, daemon_timeout=_PREPARE_BOUND)
    attempt_id = "a-540-late-create-01"
    name = d._container_name(attempt_id)
    with pytest.raises(BackendUnavailable, match="docker run failed to start"):
        backend.prepare(attempt_id)
    _await_late_create(docker_state, name)
    assert not (docker_state / f"{name}.json").exists(), "the late-created container was left behind"


def test_a_create_later_than_the_answer_window_is_reported_not_silent(base: Path, docker_state: Path) -> None:
    """#540's bounded tail: a daemon that has not answered `run -d` even after
    the extra window cannot be cleaned up with certainty. That outcome must
    reach the message, naming the attempt label a sweep can find it by - never
    a clean-looking failure like the one that hid the kyle19 residue."""
    _late_create(docker_state, 2 * _PREPARE_BOUND + 2.0)
    backend = _backend(base, docker_state, daemon_timeout=_PREPARE_BOUND)
    attempt_id = "a-540-late-create-02"
    name = d._container_name(attempt_id)
    try:
        with pytest.raises(BackendUnavailable, match="docker run failed to start") as caught:
            backend.prepare(attempt_id)
        message = str(caught.value)
        assert "did not answer" in message
        assert f"{d.ATTEMPT_LABEL_KEY}={attempt_id}" in message
    finally:
        _await_late_create(docker_state, name)
        subprocess.run([*_docker_bin(docker_state), "rm", "-f", name], capture_output=True, check=False)


@pytest.mark.parametrize(("ending", "answered"), [("os.kill(os.getpid(), signal.SIGKILL)", False), ("sys.exit(1)", True)])
def test_a_cli_ended_by_a_signal_in_the_answer_window_is_not_an_answer(
    base: Path, docker_state: Path, ending: str, answered: bool,
) -> None:
    """#540 (counter-model review): only a CLI that EXITED heard the daemon.
    One killed by a signal inside the answer window settles nothing, so the
    cleanup stays unconfirmed. The ordinary nonzero exit is the control."""
    backend = _backend(base, docker_state, daemon_timeout=_PREPARE_BOUND)
    script = f"import os, signal, sys, time; time.sleep({_SLOWER_THAN_BOUND}); {ending}"
    completed, timed_out, got = backend._run_awaiting_answer([sys.executable, "-c", script], os.environ)
    assert completed is None and timed_out is not None
    assert got is answered


@pytest.mark.parametrize(("ending", "answered"), [("os.kill(os.getpid(), signal.SIGKILL)", False), ("sys.exit(1)", True)])
def test_a_cli_ended_by_a_signal_inside_the_bound_is_not_an_answer(
    base: Path, docker_state: Path, ending: str, answered: bool,
) -> None:
    """#540 (counter-model review, pass 2): the same rule inside the first
    bound, where the call returns a completed process rather than a timeout."""
    backend = _backend(base, docker_state, daemon_timeout=_PREPARE_BOUND)
    script = f"import os, signal, sys; {ending}"
    completed, timed_out, got = backend._run_awaiting_answer([sys.executable, "-c", script], os.environ)
    assert timed_out is None and completed is not None and completed.returncode != 0
    assert got is answered


def test_prepare_reports_a_run_cli_ended_by_a_signal_as_unconfirmed(
    base: Path, docker_state: Path, tmp_path: Path,
) -> None:
    """#540: a `run -d` CLI killed by a signal is read as a failed start, and
    its cleanup cannot be confirmed - the message names the attempt label. Only
    `run` dies; every other call reaches the fake CLI unchanged."""
    docker_state.mkdir(parents=True, exist_ok=True)
    wrapper = tmp_path / "signal_on_run.py"
    wrapper.write_text(
        "import os, signal, sys\n"
        "if 'run' in sys.argv:\n"
        "    os.kill(os.getpid(), signal.SIGKILL)\n"
        "os.execv(sys.argv[1], sys.argv[1:])\n",
        encoding="utf-8",
    )
    backend = d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=[sys.executable, str(wrapper), *_docker_bin(docker_state)],
        daemon_timeout=_PREPARE_BOUND,
    )
    attempt_id = "a-540-signal-run-01"
    with pytest.raises(BackendUnavailable, match="docker run failed to start") as caught:
        backend.prepare(attempt_id)
    message = str(caught.value)
    assert f"ended by signal {signal.SIGKILL.value}" in message
    assert f"{d.ATTEMPT_LABEL_KEY}={attempt_id}" in message


def test_remove_file_in_attempt_is_false_when_the_attempt_is_not_running(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-rm-0000000000003")
    backend.install(handle, {})
    backend.destroy(handle)
    assert backend.remove_file_in_attempt(handle, f"{d.CONTAINER_WORKSPACE}/x") is False


@pytest.mark.parametrize("witness_io", [False, True])
def test_retained_output_and_opted_witness_io_preserve_candidate_files(
    base: Path, docker_state: Path, tmp_path: Path, witness_io: bool,
) -> None:
    from dataclasses import replace

    backend = replace(_backend(base, docker_state), witness_io=witness_io)
    handle = backend.prepare("witness-io-control")
    try:
        backend.install(handle, {})
        gate = backend.exec_in_attempt(handle, [sys.executable, "-c",
            "from pathlib import Path; Path('observations').write_text('candidate'); print('gate')"],
            Limits(timeout=5))
        primary = backend.execute(handle, [sys.executable, "-c", "print('primary')"], Limits(timeout=5))
        assert primary.stdout == b"primary\n"
        assert gate.stdout == b"gate\n"
        dest = tmp_path / "witness-output"
        backend.export(handle, dest)
        assert (dest / "observations").read_text() == ("candidate" if witness_io else "primary\n")
        assert bool(list(dest.glob(".skillc-exec-pid-*"))) is (not witness_io)
        assert gate.observations_capture == (None if witness_io else "written")
    finally:
        backend.destroy(handle)


@pytest.mark.parametrize("setup_fails", [False, True])
def test_home_delivery_creates_parents_as_candidate_before_owned_leaf_copy(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, setup_fails: bool,
) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("home-parent-control")
    assert isinstance(handle, d._Handle)
    home = docker_state / f"{handle.name}.fsroot" / "home" / "candidate"
    existing = home / "Projects"
    existing.mkdir(parents=True, exist_ok=True)
    existing.chmod(0o751)
    before = existing.stat()
    calls: list[list[str]] = []
    real_run = subprocess.run

    def observed_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(argv)
        if "mkdir" in argv and setup_fails:
            return subprocess.CompletedProcess(argv, 1, b"", b"permission denied")
        if "cp" in argv:
            payload = kwargs["input"]
            assert isinstance(payload, bytes)
            with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
                member, = archive.getmembers()
                assert (member.uid, member.gid, member.mode) == (d.CANDIDATE_UID, d.CANDIDATE_GID, 0o600)
        return real_run(argv, **kwargs)  # type: ignore[call-overload]

    try:
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "run", observed_run)
            if setup_fails:
                with pytest.raises(BackendUnavailable, match="parent"):
                    backend.deliver_home_file(handle, "Projects/new/nested/pyproject.toml", b"private-data")
                assert len(calls) == 1
            else:
                backend.deliver_home_file(handle, "Projects/new/nested/pyproject.toml", b"private-data")
                assert (home / "Projects/new/nested/pyproject.toml").read_bytes() == b"private-data"
                assert len(calls) == 2
            assert calls[0][len(backend.docker_bin):] == [
                "exec", "-u", d._container_user(), "--", handle.name,
                "mkdir", "-p", "--", "/home/candidate/Projects/new/nested",
            ]
        after = existing.stat()
        assert (after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)) == (
            before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode))
    finally:
        backend.destroy(handle)


@pytest.mark.parametrize("path", ["", ".", "/absolute/file", "../escape/file", "nested/../file", "bad\0file"])
def test_home_delivery_refuses_invalid_path_before_any_mutation(
    base: Path, docker_state: Path, monkeypatch: pytest.MonkeyPatch, path: str,
) -> None:
    backend = _backend(base, docker_state)
    handle = d._Handle(attempt_id="path-control", name="unused", env={})

    def must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("invalid delivery path reached a container mutation")

    monkeypatch.setattr(subprocess, "run", must_not_run)
    with pytest.raises(BackendUnavailable, match="relative"):
        backend.deliver_home_file(handle, path, b"private-data")


# #563: isolated real-filesystem creation arbitration, never the shared /tmp path.
def test_concurrent_private_trigger_directory_creators_both_succeed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "trigger-dir"
    barrier = threading.Barrier(2)
    mkdir = Path.mkdir

    def simultaneous(path: Path, mode: int = 0o777, parents: bool = False,
                     exist_ok: bool = False) -> None:
        if path == target:
            barrier.wait(timeout=5)
        mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", simultaneous)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(d._ensure_private_trigger_dir, target) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)
    assert target.is_dir() and stat.S_IMODE(target.stat().st_mode) == 0o700


@pytest.mark.parametrize("kind", ["safe", "mode", "owner", "file", "symlink"])
def test_competing_trigger_creator_is_validated_without_chmod(
        kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "trigger-dir"
    link_target = tmp_path / "link-target"
    link_target.mkdir(mode=0o700)
    chmod, mkdir = os.chmod, Path.mkdir
    chmod(link_target, 0o700)
    winner_mode = 0o755 if kind == "mode" else 0o700

    def competitor(path: Path, mode: int = 0o777, parents: bool = False,
                   exist_ok: bool = False) -> None:
        if path != target:
            mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)
            return
        if kind == "symlink":
            target.symlink_to(link_target, target_is_directory=True)
        elif kind == "file":
            target.write_text("not a directory")
            chmod(target, winner_mode)
        else:
            mkdir(target, mode=winner_mode)
            chmod(target, winner_mode)
        raise FileExistsError("a competing creator won")

    def no_chmod(path: Any, mode: int, **kwargs: Any) -> None:
        pytest.fail("a competing creator's path must never be chmodded")

    if kind == "owner":
        uid = os.getuid()
        monkeypatch.setattr(d.os, "getuid", lambda: uid + 1)
    monkeypatch.setattr(Path, "mkdir", competitor)
    monkeypatch.setattr(d.os, "chmod", no_chmod)
    if kind == "safe":
        d._ensure_private_trigger_dir(target)
    else:
        with pytest.raises(BackendUnavailable):
            d._ensure_private_trigger_dir(target)
    assert stat.S_IMODE(link_target.stat().st_mode) == 0o700
    if kind == "symlink":
        assert target.is_symlink()
    else:
        assert stat.S_IMODE(target.lstat().st_mode) == winner_mode


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_existing_trigger_leaf_must_be_a_real_directory(kind: str, tmp_path: Path) -> None:
    target = tmp_path / "trigger-dir"
    if kind == "file":
        target.write_text("not a directory")
        os.chmod(target, 0o700)
    else:
        destination = tmp_path / "destination"
        destination.mkdir(mode=0o700)
        os.chmod(destination, 0o700)
        target.symlink_to(destination, target_is_directory=True)
    with pytest.raises(BackendUnavailable):
        d._ensure_private_trigger_dir(target)


def test_creator_finalizes_mode_under_restrictive_umask_in_child(tmp_path: Path) -> None:
    result = subprocess.run([
        sys.executable, "-c",
        ("import os,stat,sys; from pathlib import Path; from skillc import docker_backend as d; "
         "os.umask(0o777); p=Path(sys.argv[1]); d._ensure_private_trigger_dir(p); "
         "assert stat.S_IMODE(p.stat().st_mode)==0o700"),
        str(tmp_path / "trigger-dir")], capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr


def test_trigger_directory_does_not_swallow_other_mkdir_errors(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("creation denied")

    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(PermissionError, match="creation denied"):
        d._ensure_private_trigger_dir(tmp_path / "trigger-dir")
