"""#500: the calibration path's nested-codex guard against a REAL daemon and
the REAL trial image. No model is ever called: the container's network is
`none`, and every nested launch is refused before it starts a turn.

`tests/test_attempt_guard.py` covers the composition with a fake docker; this
file is the evidence that `AttemptGuard` - the guard half of the fixture
session, with no fixture service behind it - places the same overlay, records
the same decisions over the attempt's one socket, and closes its record from
the real channel, in a real container:

1. `AttemptGuard.bind` places the guard, and `codex` resolves to it;
2. the pilot's own shape, `codex exec --ephemeral --model <another model>`,
   launched from under a codex ancestor, exits 3 before any model contact and
   is recorded `refused-nested`; the record is refusals-only, which the
   calibration policy credits and does not stop on;
3. the same launch by ABSOLUTE path never reaches the guard - no decision is
   recorded - and the transcript backstop (`attempt_guard.assess`) is what
   names it: credit blocked, schedule stopped.
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
from skillc import codex_guard as cg
from skillc import docker_backend as d
from skillc.fixture_service import dispatch

#: The same marks as the guard's own live test: real_docker, and skipped only
#: where no Docker daemon is reachable (the PR CI runner has none).
pytestmark = _live_marks
NESTED = "codex exec --skip-git-repo-check --ephemeral --sandbox read-only --model gpt-6-sol 'Review the one-line change.'"
#: The same launch by the REAL binary's absolute path, past the guard.
BY_PATH = f"/usr/local/bin/{NESTED}"


@pytest.mark.timeout(1800)
def test_the_calibration_guard_refuses_the_pilot_s_nested_launch_in_a_real_container() -> None:
    image, built = _trial_image()
    try:
        _run(image)
    finally:
        if built:
            import subprocess
            subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True, check=False)


def _run(image: str) -> None:
    guard = ag.AttemptGuard("a-live")
    base = Path(tempfile.mkdtemp(prefix="sk-attempt-guard-live-"))
    trigger_dir = Path(tempfile.mkdtemp(prefix="sk-ag-trig-"))
    backend = d.DockerBackend(
        image=image, base_dir=base, network="none", witness_io=True, daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT,
        trigger_decide=guard.watch(dispatch(guard.routes())), trigger_socket_dir=trigger_dir,
    )
    handle = backend.prepare(f"a-attempt-guard-live-{uuid.uuid4().hex[:12]}")
    try:
        env_raw = backend.controller_output(handle, ["env", "-0"], LIMITS)
        env: Mapping[str, str] = dict(e.split("=", 1) for e in env_raw.decode().split("\0") if e)

        # 1. placement through AttemptGuard itself
        guard.bind(backend, handle, env)
        assert guard.failure is None and guard.overlay is not None

        # 2. the pilot's nested shape is refused before any model contact
        nested = backend.exec_in_attempt(handle, [*SANDBOX, "sh", "-c", f"{NESTED}; echo inner=$?"], LIMITS, env=env)
        assert nested.reason == "exited", nested
        assert b"inner=3" in (nested.stdout or b""), (nested.stdout, nested.stderr)
        assert [e["decision"] for e in guard.guard.decisions] == ["passed-top-level", "refused-nested"]

        # 3. by absolute path the guard never sees it (network none: it reaches nothing)
        before = len(guard.guard.decisions)
        bypass = backend.exec_in_attempt(
            # network none: the real client starts, finds no provider and retries,
            # so it is bounded here; the guard would have exited 3 at once.
            handle, [*SANDBOX, "sh", "-c", f"timeout 15 {BY_PATH} </dev/null 2>&1; echo inner=$?"], LIMITS, env=env)
        assert bypass.reason == "exited", bypass
        out = (bypass.stdout or b"") + (bypass.stderr or b"")
        # The real client started (its banner names the other model), and the
        # guard's own refusal never happened: this launch went past it.
        assert b"model: gpt-6-sol" in out and b"inner=3" not in out, out[-2000:]
        assert [e["decision"] for e in guard.guard.decisions][before:] == ["passed-top-level"]  # only the sandbox
    finally:
        guard.finish(backend, handle)
        backend.destroy(handle)

    # The two `codex sandbox` launches are this test's own top-level calls.
    guard.expected_top_level = 2
    nested_record = guard.record()["nested"]
    assert nested_record["confirmed"] == 1 and nested_record["channel_unavailable"] is False
    assert cg.refusals_only(nested_record)
    # The guard alone reads clean; the transcript backstop names the bypass.
    refused_only = ag.assess(nested_record, ag.scan_command(NESTED), "gpt-6-astra")
    assert refused_only["stop"] is None and refused_only["other_models"] == ["gpt-6-sol"]
    hits = ag.scan_command(NESTED) + ag.scan_command(BY_PATH)
    assert [h["guarded"] for h in hits] == [True, False]
    with_bypass = ag.assess(nested_record, hits, "gpt-6-astra")
    assert with_bypass["stop"] and "past the guard" in with_bypass["stop"] and with_bypass["block"]
