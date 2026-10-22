"""#518 A: the credential steward against a REAL daemon, in the REAL trial image,
through the real `AttemptGuard` and its trigger socket. No model is called:
the network is `none`, and the credential is a dummy.

1. bound, the steward arms; the "client" (the candidate reading auth.json the
   four times codex-cli 0.157.1 does) then goes quiet, and the file is
   withdrawn into the root-only vault; the candidate can read neither;
2. a nested launch afterwards finds no credential;
3. a re-creation while withdrawn is captured and reported - the record reads
   `refreshed`, which blocks credit and stops the schedule;
4. a resume: the steward restores the file itself (candidate-owned, 0600),
   re-arms, and withdraws again after the client's reads;
5. the attempt's last turn runs through lifecycle's real turn path, whose
   `before_stop` stops the steward while the container still runs - and,
   the red, a stop sent only after the container was killed never arrives.
"""

from __future__ import annotations

import tempfile
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT
from test_codex_guard_live import LIMITS, _trial_image
from test_codex_guard_live import pytestmark as _live_marks

from skillc import attempt_guard as ag
from skillc import credential_steward as cs
from skillc import docker_backend as d
from skillc import lifecycle
from skillc.fixture_service import dispatch

pytestmark = _live_marks
DUMMY = b'{"auth_mode": "chatgpt", "tokens": {"refresh_token": "rt-DUMMY"}}\n'
FOUR_READS = "for i in 1 2 3 4; do cat ~/.codex/auth.json >/dev/null; done"


@pytest.mark.timeout(1800)
def test_red_518_the_steward_withdraws_captures_and_restores_in_a_real_container() -> None:
    image, built = _trial_image()
    try:
        _run(image)
    finally:
        if built:
            import subprocess
            subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True, check=False)


def _sh(backend: d.DockerBackend, handle: object, env: Mapping[str, str], script: str) -> tuple[int | None, bytes]:
    result = backend.exec_in_attempt(handle, ["sh", "-c", script], LIMITS, env=env)
    return result.exit_code, (result.stdout or b"")


def _wait_for(guard: ag.AttemptGuard, event: str, after: int, seconds: float = 15.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if any(e["event"] == event for e in guard.steward.events[after:]):
            return True
        time.sleep(0.1)
    return False


def _run(image: str) -> None:
    guard = ag.AttemptGuard("a-live-518-steward")
    backend = d.DockerBackend(
        image=image, base_dir=Path(tempfile.mkdtemp(prefix="sk-518s-")), network="none", witness_io=True,
        daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT, trigger_decide=guard.watch(dispatch(guard.routes())),
        trigger_socket_dir=Path(tempfile.mkdtemp(prefix="sk-518s-t-")),
    )
    handle = backend.prepare(f"a-518-steward-{uuid.uuid4().hex[:12]}")
    try:
        backend.deliver_home_file(handle, ".codex/auth.json", DUMMY)
        env_raw = backend.controller_output(handle, ["env", "-0"], LIMITS)
        env: Mapping[str, str] = dict(e.split("=", 1) for e in env_raw.decode().split("\0") if e)
        guard.bind(backend, handle, env)
        assert guard.failure is None and guard.steward_driver is not None

        # 1. the client's four reads, then quiet: withdrawn into the vault.
        before = len(guard.steward.events)
        assert _sh(backend, handle, env, FOUR_READS)[0] == 0
        assert _wait_for(guard, "withdrawn", before), guard.steward.events
        assert _sh(backend, handle, env, "test -e ~/.codex/auth.json; echo $?")[1].strip() == b"1"
        assert _sh(backend, handle, env, f"cat {cs.VAULT}/auth.json 2>&1; echo rc=$?")[1].endswith(b"rc=1\n")
        assert guard.steward_driver.vault_bytes(backend, handle) == DUMMY

        # 2. a nested launch now finds no credential to authenticate with.
        assert _sh(backend, handle, env, "cat ~/.codex/auth.json >/dev/null 2>&1; echo $?")[1].strip() == b"1"

        # 4. a resume: restored BY THE STEWARD for the client, withdrawn again.
        guard.steward_driver.restore_for_turn(backend, handle)
        assert _sh(backend, handle, env, "cat ~/.codex/auth.json")[1] == DUMMY
        assert _sh(backend, handle, env, "stat -c '%U %a' ~/.codex/auth.json")[1].strip() == b"candidate 600"
        before = len(guard.steward.events)
        assert _sh(backend, handle, env, FOUR_READS)[0] == 0
        assert _wait_for(guard, "withdrawn", before)

        # 3. a re-creation while withdrawn is captured and reported.
        before = len(guard.steward.events)
        _sh(backend, handle, env, "printf '%s' '{\"tokens\": {\"refresh_token\": \"rt-ROTATED\"}}' > ~/.codex/auth.json")
        assert _wait_for(guard, "refreshed-captured", before), guard.steward.events
        assert _sh(backend, handle, env, "test -e ~/.codex/auth.json; echo $?")[1].strip() == b"1"
        assert b"rt-ROTATED" in (guard.steward_driver.vault_bytes(backend, handle) or b"")

        # 5. the last turn, through lifecycle's turn path: the steward stops
        # before the container does.
        driver = guard.steward_driver
        lifecycle._run_turns(backend, handle, None, "a-518-steward", ["sh", "-c", "true"], LIMITS,  # type: ignore[arg-type]
                             None, lambda *_: None, before_stop=driver.stop)  # type: ignore[arg-type]
        assert backend.confirm_stopped(handle) is d.Confirmation.CONFIRMED
    finally:
        guard.finish(backend, handle)
        backend.destroy(handle)
    record = guard.steward_record()
    assert record["arms"] == 2 and record["stopped"] is True and record["status"] == "refreshed"
    assert b"rt-ROTATED" in (driver.final_vault or b"")
    assert cs.credit_block(record) is not None and cs.stop_reason(record) is not None


@pytest.mark.timeout(900)
def test_red_518_a_stop_sent_after_the_container_is_killed_never_arrives() -> None:
    """The order `finish()` alone had at fab5cc4: the container is stopped, then
    the steward is asked to stop. It cannot answer, and the record reads
    unknown - which is why lifecycle's `before_stop` exists."""
    image, built = _trial_image()
    try:
        guard = ag.AttemptGuard("a-live-518-late-stop")
        backend = d.DockerBackend(
            image=image, base_dir=Path(tempfile.mkdtemp(prefix="sk-518l-")), network="none", witness_io=True,
            daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT, trigger_decide=guard.watch(dispatch(guard.routes())),
            trigger_socket_dir=Path(tempfile.mkdtemp(prefix="sk-518l-t-")),
        )
        handle = backend.prepare(f"a-518-late-{uuid.uuid4().hex[:12]}")
        try:
            backend.deliver_home_file(handle, ".codex/auth.json", DUMMY)
            env_raw = backend.controller_output(handle, ["env", "-0"], LIMITS)
            guard.bind(backend, handle, dict(e.split("=", 1) for e in env_raw.decode().split("\0") if e))
            assert guard.steward_driver is not None
            guard.steward_driver.wait_s = 3.0
            backend.end_attempt(handle)
            guard.finish(backend, handle)
        finally:
            backend.destroy(handle)
        record = guard.steward_record()
        assert record["stopped"] is False and record["status"] == "unknown"
    finally:
        if built:
            import subprocess
            subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True, check=False)
