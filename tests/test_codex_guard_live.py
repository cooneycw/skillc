"""The nested-codex guard against a REAL daemon and the REAL trial image
(#434 PR 2b, D3). `tests/test_codex_guard.py` drives the guard over a
synthetic `/proc`; this file is the evidence that the real `/proc` walk, in a
real container, under the real launch, decides correctly.

It needs the locally built `skillc-trial` image (it carries the pinned codex
that the guard matches against) and skips without it. No model is ever
called: the container's network is `none`, and the only codex subcommands run
are `--version` and `sandbox`, which start no turn.

What it shows, in one attempt container, in order:

1. the overlay places the guard and its config root-owned and verified, and
   `codex` resolves to the guard under the measured environment;
2. a REAL nested codex: `codex sandbox` (the native binary) runs a shell that
   calls bare `codex` again; the inner call exits 3 with the unavailable line
   and is recorded `refused-nested`;
3. an ancestor that only MENTIONS codex (`sh -c "... grep codex ..."`), or is
   NAMED like it (a copy of sh called `codex-something`), does not count;
4. pass-through is byte for byte: the node process a guarded launch starts
   has the same cmdline and environ as an unguarded launch of the real
   symlink;
5. the harness's own launch passes as top-level, both through skillc-wrap
   (the chain the ruling names; the image does not ship it yet, so the
   tracked script is placed where #158's held image change puts it) and
   through `execute()` itself (the production chain today: `sh -c 'exec
   "$@"'`, with no supervisor running, so skillc-wrap is not prefixed).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT

from skillc import codex_guard as cg
from skillc import docker_backend as d
from skillc import fixture_overlay as fo
from skillc.backend import Limits
from skillc.fixture_service import dispatch

IMAGE = os.environ.get("SKILLC_TRIAL_IMAGE", "skillc-trial:latest")
_DOCKER = shutil.which("docker") is not None
pytestmark = [
    pytest.mark.real_docker,
    pytest.mark.skipif(not _DOCKER or d.probe_daemon(["docker"]) is None,
                       reason="no reachable Docker daemon; real-daemon evidence is owed to the real-Docker runner"),
]
LIMITS = Limits(timeout=60.0)
SANDBOX = ["codex", "sandbox", "-c", 'sandbox_mode="danger-full-access"', "--"]
#: Prints the node codex process's cmdline and environ: the shell's parent is
#: the native binary, whose parent is node.
_DUMP = ('n=$(awk \'{print $4}\' /proc/$PPID/stat); '
         'od -An -tx1 -v /proc/$n/cmdline | tr -d " \\n"; echo; '
         'od -An -tx1 -v /proc/$n/environ | tr -d " \\n"; echo')


def _image_present() -> bool:
    return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=20,
                          check=False).returncode == 0


def _ok(result: Any) -> bytes:
    assert result.reason == "exited", result
    return result.stdout or b""


def test_the_guard_decides_correctly_in_a_real_trial_container() -> None:
    if not _image_present():
        pytest.skip(f"{IMAGE!r} is not built locally")
    session = cg.CodexGuardSession("live")
    base = Path(tempfile.mkdtemp(prefix="sk-codex-guard-live-"))
    trigger_dir = Path(tempfile.mkdtemp(prefix="sk-cg-trig-"))
    backend = d.DockerBackend(
        image=IMAGE, base_dir=base, network="none", witness_io=True, daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT,
        trigger_decide=dispatch({"codex_guard": (session.decide, cg.REQUEST_KEYS)}),
        trigger_socket_dir=trigger_dir,
    )
    handle = backend.prepare(f"a-codex-guard-live-{uuid.uuid4().hex[:12]}")
    try:
        assert isinstance(handle, d._Handle)
        env_raw = backend.controller_output(handle, ["env", "-0"], LIMITS)
        env: Mapping[str, str] = dict(e.split("=", 1) for e in env_raw.decode().split("\0") if e)

        # 1. placement, verified
        placed = fo.install_codex_guard(backend, handle, env)
        assert placed["resolved"]["codex_js"].endswith("/@openai/codex/bin/codex.js")  # type: ignore[index]

        # 2. a REAL nested codex is refused
        nested = backend.exec_in_attempt(handle, [*SANDBOX, "sh", "-c", "codex --version; echo inner=$?"], LIMITS,
                                         env=env)
        out = _ok(nested)
        assert b"inner=3" in out, (out, nested.stderr)
        assert b"CODEX_REVIEW: unavailable" in (nested.stderr or b"")
        decisions = [entry["decision"] for entry in session.decisions]
        assert decisions == ["passed-top-level", "refused-nested"], decisions

        # 3. mentioning or resembling codex is not being codex
        mention = backend.exec_in_attempt(handle, ["sh", "-c", "codex --version; : grep codex"], LIMITS, env=env)
        assert _ok(mention).startswith(b"codex-cli "), mention
        rename = "cp /bin/sh /tmp/codex-something && /tmp/codex-something -c 'codex --version'"
        named = backend.exec_in_attempt(handle, ["sh", "-c", rename], LIMITS, env=env)
        assert _ok(named).startswith(b"codex-cli "), named
        assert [e["decision"] for e in session.decisions][2:] == ["passed-top-level", "passed-top-level"]

        # 4. pass-through is byte for byte against an unguarded launch
        guarded = _ok(backend.exec_in_attempt(handle, [*SANDBOX, "sh", "-c", _DUMP], LIMITS, env=env))
        unguarded = _ok(backend.exec_in_attempt(
            handle, ["/usr/local/bin/codex", *SANDBOX[1:], "sh", "-c", _DUMP], LIMITS, env=env))
        assert guarded.count(b"\n") == 2 and guarded == unguarded, (guarded, unguarded)

        # 5a. the harness launch through skillc-wrap passes as top-level. The
        # trial image does not ship skillc-wrap yet (#158's image change is
        # held), so the tracked script is placed where that change puts it.
        # It is started from a shell child, not exec'd directly: a `docker
        # exec` process is its own session leader, so skillc-wrap's
        # os.setsid() fails with EPERM when exec'd in place (a #158 finding,
        # nit store), before codex is ever reached.
        wrap = Path(__file__).resolve().parent.parent / "docker" / "trial" / "skillc-wrap.py"
        assert backend.write_root_owned_file_in_attempt(handle, d.SKILLC_WRAP_PATH, wrap.read_bytes(), mode=0o755)
        before = len(session.decisions)
        wrapped = backend.exec_in_attempt(handle, ["sh", "-c", f"{d.SKILLC_WRAP_PATH} codex --version"], LIMITS,
                                          env=env)
        assert _ok(wrapped).startswith(b"codex-cli "), (wrapped.error, wrapped.stderr)
        assert [e["decision"] for e in session.decisions][before:] == ["passed-top-level"]

        # 5b. and through execute(), the production chain (it stops the
        # container, so it runs last)
        before = len(session.decisions)
        launched = backend.execute(handle, ["codex", "--version"], LIMITS)
        assert launched.reason == "exited" and launched.exit_code == 0, launched
        assert [e["decision"] for e in session.decisions][before:] == ["passed-top-level"]
        assert "refused-ancestry-unknown" not in [e["decision"] for e in session.decisions]
    finally:
        backend.destroy(handle)
