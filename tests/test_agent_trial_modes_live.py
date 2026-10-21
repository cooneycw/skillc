"""#505 against a REAL daemon and the REAL trial image: an installed helper
delivered at its source mode RUNS in the container, a non-executable source
does not, and the 0600 delivery every live trial used before #505 reproduces
the campaigns' `Permission denied` (exit 126) - the control.

No model is called: the container's network is `none`, and the only commands
run are the delivered file itself and `stat`.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT
from test_codex_guard_live import LIMITS, _trial_image
from test_codex_guard_live import pytestmark as _live_marks

from skillc import agent_trial as at
from skillc import docker_backend as d

#: The same marks as the guard's own live test: real_docker, and skipped only
#: where no Docker daemon is reachable (the PR CI runner has none).
pytestmark = _live_marks

HELPER = ".claude/scripts/flow-start-resolve.sh"
DOC = ".claude/scripts/notes.sh"
LEGACY = ".claude/scripts/legacy-0600.sh"
SCRIPT = b"#!/bin/sh\necho resolved\n"


@pytest.mark.timeout(1800)
def test_a_delivered_helper_runs_in_a_real_container_and_a_non_executable_source_does_not() -> None:
    image, built = _trial_image()
    try:
        _run(image)
    finally:
        if built:
            import subprocess
            subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True, check=False)


def _run(image: str) -> None:
    base = Path(tempfile.mkdtemp(prefix="sk-modes-live-"))
    backend = d.DockerBackend(image=image, base_dir=base, network="none", witness_io=True,
                              daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT)
    handle = backend.prepare(f"a-modes-live-{uuid.uuid4().hex[:12]}")
    modes = {HELPER: "100755", DOC: "100644"}
    try:
        for relpath in (HELPER, DOC):
            backend.deliver_home_file(handle, relpath, SCRIPT, mode=at.delivery_mode(relpath, modes))
        backend.deliver_home_file(handle, LEGACY, SCRIPT)  # the pre-#505 delivery: the default 0600

        def run(relpath: str) -> tuple[int | None, bytes]:
            result = backend.exec_in_attempt(handle, ["sh", "-c", f'"$HOME/{relpath}"; echo rc=$?'], LIMITS)
            assert result.reason == "exited", result
            return result.exit_code, (result.stdout or b"") + (result.stderr or b"")

        _, out = run(HELPER)
        assert b"resolved" in out and b"rc=0" in out, out           # red (a): the helper runs
        _, out = run(DOC)
        assert b"rc=126" in out and b"resolved" not in out, out     # red (b): a non-executable source stays so
        _, out = run(LEGACY)
        assert b"rc=126" in out, out                                # control: what every campaign attempt met
        modes_seen = backend.exec_in_attempt(
            handle, ["sh", "-c", f'stat -c "%a %n" "$HOME/{HELPER}" "$HOME/{DOC}" "$HOME/{LEGACY}"'], LIMITS)
        lines = (modes_seen.stdout or b"").decode().split("\n")
        assert lines[0].startswith("700 ") and lines[1].startswith("600 ") and lines[2].startswith("600 "), lines
    finally:
        backend.destroy(handle)
