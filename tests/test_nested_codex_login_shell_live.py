"""#518: the nested codex that sizing-2's agent launched, reproduced in the REAL
trial image against a REAL daemon. No model is called: the network is `none`.

sizing-2's agent ran its Step-6 review as `codex exec -m gpt-6-sol ...` from
its own tool shell, which codex runs as `bash -lc`. A login shell's PATH comes
from /etc/profile, whose non-root PATH drops /usr/local/sbin - where the guard
lives - so the bare `codex` was the real client: not refused, and the guard
recorded nothing. With the #518 login-profile entry the same launch reaches the
guard and is refused before any model contact.

On main (before #518) the same probe reads: `bash -lc 'command -v codex'` =
/usr/local/bin/codex, and the nested launch is NOT refused (recorded on #518).
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT
from test_codex_guard_live import LIMITS, SANDBOX, _trial_image
from test_codex_guard_live import pytestmark as _live_marks

from skillc import attempt_guard as ag
from skillc import docker_backend as d
from skillc import fixture_overlay as fo
from skillc.fixture_service import dispatch

pytestmark = _live_marks
#: sizing-2's observed shape, in the shell codex actually uses for tool calls.
NESTED = ("codex exec -m gpt-6-sol -s read-only --json -o /tmp/review.md "
          "'Review the current uncommitted diff against origin/main for issue #1.'")


@pytest.mark.timeout(1800)
def test_red_518_a_login_shell_nested_codex_reaches_the_guard_and_is_refused() -> None:
    image, built = _trial_image()
    try:
        _run(image)
    finally:
        if built:
            import subprocess
            subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True, check=False)


def _run(image: str) -> None:
    guard = ag.AttemptGuard("a-live-518")
    base = Path(tempfile.mkdtemp(prefix="sk-518-live-"))
    trigger_dir = Path(tempfile.mkdtemp(prefix="sk-518-trig-"))
    backend = d.DockerBackend(
        image=image, base_dir=base, network="none", witness_io=True, daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT,
        trigger_decide=guard.watch(dispatch(guard.routes())), trigger_socket_dir=trigger_dir,
    )
    handle = backend.prepare(f"a-518-live-{uuid.uuid4().hex[:12]}")
    try:
        env_raw = backend.controller_output(handle, ["env", "-0"], LIMITS)
        env: Mapping[str, str] = dict(e.split("=", 1) for e in env_raw.decode().split("\0") if e)
        guard.bind(backend, handle, env)
        assert guard.failure is None and guard.overlay is not None

        # The login shell now resolves the guard (on main: /usr/local/bin/codex).
        login = backend.exec_in_attempt(handle, ["bash", "-lc", "command -v codex"], LIMITS, env=env)
        assert (login.stdout or b"").strip() == fo.CODEX_GUARD_PATH.encode(), login

        # sizing-2's launch, from under a codex ancestor, in a login shell: refused.
        nested = backend.exec_in_attempt(
            handle, [*SANDBOX, "bash", "-lc", f"timeout 20 {NESTED} </dev/null; echo inner=$?"], LIMITS, env=env)
        assert nested.reason == "exited", nested
        assert b"inner=3" in (nested.stdout or b""), (nested.stdout, nested.stderr)
        assert [e["decision"] for e in guard.guard.decisions] == ["passed-top-level", "refused-nested"]
    finally:
        guard.finish(backend, handle)
        backend.destroy(handle)
