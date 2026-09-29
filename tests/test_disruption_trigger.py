"""Tests for the ADVISORY L5 request-count observer (#14, runtime part c).

`DisruptionTrigger`'s output is never a `trusted_observation` - see the
module's own docstring for why a poll-based count of a subject-writable
file cannot honestly be one, unlike `AuthorityInterceptor`'s whole-tree
diff. These tests prove what an advisory counter can still honestly claim:
what it observed, including zero, and when it could not observe at all.

Driven against the same fake `docker` CLI `test_docker_backend.py` and
`test_authority_interceptor.py` use (`tests/fixtures/docker-backend/
fake_docker.py`) - no real daemon is available in this session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import FAKE_DOCKER_DAEMON_TIMEOUT

from skillc import docker_backend as d
from skillc.backend import Confirmation, Limits
from skillc.disruption_trigger import DEFAULT_REQUEST_LOG, DisruptionTrigger

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


def _backend(base: Path, docker_state: Path) -> d.DockerBackend:
    # issue #174: this file polls export() repeatedly per test - a wider
    # TEST-only daemon_timeout against the fake docker CLI, not production's
    # own DAEMON_TIMEOUT. See conftest.FAKE_DOCKER_DAEMON_TIMEOUT.
    return d.DockerBackend(
        image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state),
        daemon_timeout=FAKE_DOCKER_DAEMON_TIMEOUT,
    )


def _prepared(backend: d.DockerBackend, attempt_id: str) -> object:
    return backend.prepare(attempt_id)


def _run_and_stop(backend: d.DockerBackend, handle: object, script: str, timeout: float = 10) -> None:
    result = backend.execute(handle, [sys.executable, "-c", script], Limits(timeout=timeout))
    assert result.reason == "exited", result.error
    assert result.exit_code == 0
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED


def _append_n_requests(n: int) -> str:
    return (
        "import os\n"
        "os.makedirs('.disruption', exist_ok=True)\n"
        f"with open({DEFAULT_REQUEST_LOG!r}, 'a') as f:\n"
        f"    for _ in range({n}):\n"
        "        f.write('request\\n')\n"
    )


def test_a_count_is_reported_and_fail_after_is_only_echoed(base: Path, docker_state: Path) -> None:
    """`fail_after` is context for a reader, never a bound this class
    computes from - unlike the removed `failed_after_step` framing, a
    count past `fail_after` is reported exactly as observed, not clamped."""
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000001")
    observer = DisruptionTrigger(backend, handle, fail_after=3, interval=0.05)
    observer.start()
    _run_and_stop(backend, handle, _append_n_requests(5))
    advisory = observer.stop_and_finalize()
    assert advisory is not None
    data = json.loads(advisory)
    assert data["requests_received"] == 5
    assert data["fail_after"] == 3  # echoed, not applied as a bound
    backend.destroy(handle)


def test_zero_observed_requests_is_a_valid_advisory_value(base: Path, docker_state: Path) -> None:
    """Unlike a trusted_observation (where zero had to become a hard
    refusal to avoid a false PASS - see the module docstring), an advisory
    count has no verdict to falsify: zero is just an honest, reportable
    observation, not a refusal."""
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000003")
    observer = DisruptionTrigger(backend, handle, fail_after=3, interval=0.05)
    observer.start()
    _run_and_stop(backend, handle, "pass")  # the subject never touches the request log at all
    advisory = observer.stop_and_finalize()
    assert advisory is not None
    assert json.loads(advisory)["requests_received"] == 0


def test_the_mandatory_final_snapshot_alone_catches_late_requests(base: Path, docker_state: Path) -> None:
    """Proof that the final snapshot, not the polling loop, is what the
    mandatory-observation guarantee rests on: interval is longer than the
    whole attempt, so the loop thread never wakes even once."""
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000004")
    observer = DisruptionTrigger(backend, handle, fail_after=3, interval=60.0)
    observer.start()
    _run_and_stop(backend, handle, _append_n_requests(3))
    advisory = observer.stop_and_finalize()
    assert advisory is not None
    assert json.loads(advisory)["requests_received"] == 3
    backend.destroy(handle)


def test_a_later_truncation_does_not_erase_an_earlier_higher_count(base: Path, docker_state: Path) -> None:
    """`_max_requests_seen` only ever grows: a subject that inflates the log
    then shrinks it back down does not erase what an earlier poll already
    observed. This defeats SHRINKING the count after the fact - it does
    nothing against INFLATING it in the first place, which is exactly why
    this count stays advisory (see the module docstring)."""
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000005")
    observer = DisruptionTrigger(backend, handle, fail_after=5, interval=0.05)
    observer.start()
    script = (
        _append_n_requests(4)
        + "import time; time.sleep(0.2)\n"
        + f"open({DEFAULT_REQUEST_LOG!r}, 'w').close()\n"  # truncate back to empty
    )
    _run_and_stop(backend, handle, script, timeout=10)
    advisory = observer.stop_and_finalize()
    assert advisory is not None
    assert json.loads(advisory)["requests_received"] == 4
    backend.destroy(handle)


def test_finalize_returns_none_only_when_the_final_export_itself_fails(
    base: Path, docker_state: Path,
) -> None:
    """The only case this module refuses to report anything at all: it
    could not observe the final state, not even an advisory count."""
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000006")
    observer = DisruptionTrigger(backend, handle, fail_after=3, interval=60.0)
    observer.start()
    _run_and_stop(backend, handle, _append_n_requests(2))
    backend.destroy(handle)  # gone before finalize can export from it
    advisory = observer.stop_and_finalize()
    assert advisory is None


def test_start_raises_when_no_baseline_can_be_captured(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000007")
    backend.destroy(handle)
    observer = DisruptionTrigger(backend, handle, fail_after=3, interval=0.05)
    with pytest.raises(RuntimeError, match="baseline"):
        observer.start()


def test_a_negative_fail_after_is_refused(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000008")
    with pytest.raises(ValueError, match="fail_after"):
        DisruptionTrigger(backend, handle, fail_after=-1, interval=0.05)
    backend.destroy(handle)


def test_a_nonpositive_interval_is_refused(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000009")
    with pytest.raises(ValueError, match="interval"):
        DisruptionTrigger(backend, handle, fail_after=3, interval=0.0)
    backend.destroy(handle)


def test_double_start_is_refused(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000010")
    observer = DisruptionTrigger(backend, handle, fail_after=3, interval=0.05)
    observer.start()
    with pytest.raises(RuntimeError, match="already been started"):
        observer.start()
    _run_and_stop(backend, handle, _append_n_requests(1))
    observer.stop_and_finalize()
    backend.destroy(handle)


def test_double_finalize_is_refused(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000011")
    observer = DisruptionTrigger(backend, handle, fail_after=3, interval=0.05)
    observer.start()
    _run_and_stop(backend, handle, _append_n_requests(1))
    observer.stop_and_finalize()
    with pytest.raises(RuntimeError, match="already been finalized"):
        observer.stop_and_finalize()
    backend.destroy(handle)


class _FlakyExport:
    """Wraps a real backend's `export`, succeeding `succeed_first` calls,
    then failing the next `then_fail` calls, then succeeding forever after -
    fully deterministic, unlike relying on wall-clock timing to land a poll
    mid-flake (issue #174: no new load-sensitive test in this repo)."""

    def __init__(self, real_export: Any, succeed_first: int, then_fail: int) -> None:
        self._real_export = real_export
        self._succeed_first = succeed_first
        self._then_fail = then_fail
        self.calls = 0

    def export(self, handle: object, dest: Path) -> None:
        self.calls += 1
        if self._succeed_first < self.calls <= self._succeed_first + self._then_fail:
            raise OSError("simulated transient export failure")
        self._real_export(handle, dest)


def test_mid_run_poll_failures_are_recorded_as_coverage_not_silently_skipped(
    base: Path, docker_state: Path,
) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-disruption-000000012")
    flaky = _FlakyExport(backend.export, succeed_first=1, then_fail=2)
    observer = DisruptionTrigger(flaky, handle, fail_after=3, interval=60.0)  # type: ignore[arg-type]
    observer.start()  # call 1: succeeds (baseline)
    assert observer._poll_once(record=True) is False  # call 2: fails
    assert observer._poll_once(record=True) is False  # call 3: fails
    _run_and_stop(backend, handle, _append_n_requests(1))
    advisory = observer.stop_and_finalize()  # call 4: succeeds (mandatory final)
    assert advisory is not None
    data = json.loads(advisory)
    assert data["coverage"] == {"polls_attempted": 3, "polls_failed": 2}
    assert data["requests_received"] == 1
    backend.destroy(handle)
