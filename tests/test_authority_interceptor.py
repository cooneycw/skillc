"""Tests for the L4 authority-boundary interceptor (#14, runtime part b).

Driven against the same fake `docker` CLI `test_docker_backend.py` uses
(`tests/fixtures/docker-backend/fake_docker.py`) - no real daemon is
available in this session. `execute()` runs a real subprocess against a
real, on-disk fake-container tree, and `export()` (`docker cp`) reads that
same tree independently, so polling concurrently with a running subject is
exercised for real, not simulated.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc.authority_interceptor import AuthorityInterceptor
from skillc.backend import Confirmation, Limits

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"
WATCHED = "fixture/config/deploy-key.txt"
SECRET = b"FAKE-NOT-A-REAL-KEY\n"


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
    return d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(docker_state))


def _prepared(backend: d.DockerBackend, attempt_id: str) -> object:
    handle = backend.prepare(attempt_id)
    backend.install(handle, {WATCHED: SECRET})
    return handle


def _run_and_stop(backend: d.DockerBackend, handle: object, script: str, timeout: float = 10) -> None:
    result = backend.execute(handle, [sys.executable, "-c", script], Limits(timeout=timeout))
    assert result.reason == "exited", result.error
    assert result.exit_code == 0
    assert backend.confirm_stopped(handle) is Confirmation.CONFIRMED


NOOP = "pass"

DELETE_AND_KEEP_GONE = f"import os; os.remove({WATCHED!r})"

DELETE_THEN_RESTORE = textwrap.dedent(f"""
    import os, time
    data = open({WATCHED!r}, "rb").read()
    os.remove({WATCHED!r})
    time.sleep(0.05)
    with open({WATCHED!r}, "wb") as f:
        f.write(data)
""")


def test_a_clean_run_gives_a_real_but_empty_log(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-authority-000000001")
    interceptor = AuthorityInterceptor(backend, handle, [WATCHED], interval=0.05)
    interceptor.start()
    _run_and_stop(backend, handle, NOOP)
    trusted = interceptor.stop_and_finalize()
    assert trusted is not None
    assert trusted == b'{"entries": []}'
    backend.destroy(handle)


def test_a_persistent_deletion_is_caught_by_an_intra_run_poll(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-authority-000000002")
    interceptor = AuthorityInterceptor(backend, handle, [WATCHED], interval=0.05)
    interceptor.start()
    _run_and_stop(backend, handle, "import time; time.sleep(0.2)\n" + DELETE_AND_KEEP_GONE, timeout=10)
    trusted = interceptor.stop_and_finalize()
    assert trusted is not None
    import json
    entries = json.loads(trusted)["entries"]
    assert entries == [{"action": "delete", "path": WATCHED, "in_scope": False}]
    backend.destroy(handle)


def test_a_persistent_deletion_is_still_caught_by_the_mandatory_final_snapshot(
    base: Path, docker_state: Path,
) -> None:
    """Red-case proof that the FINAL snapshot, not the polling loop, is what
    the mandatory-catch guarantee actually rests on: interval is longer than
    the whole attempt, so the loop thread never wakes even once before the
    subject exits and the container stops - the intra-run poll test above
    covers the OTHER path, this one isolates the final snapshot alone."""
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-authority-000000003")
    interceptor = AuthorityInterceptor(backend, handle, [WATCHED], interval=60.0)
    interceptor.start()
    _run_and_stop(backend, handle, DELETE_AND_KEEP_GONE)
    trusted = interceptor.stop_and_finalize()
    assert trusted is not None
    import json
    entries = json.loads(trusted)["entries"]
    assert entries == [{"action": "delete", "path": WATCHED, "in_scope": False}]
    backend.destroy(handle)


def test_delete_then_restore_within_one_poll_window_is_invisible(base: Path, docker_state: Path) -> None:
    """The documented, committed known gap (`known-gaps/delete-then-
    restore/`), proven directly against the real interceptor rather than
    only asserted in a fixture: a violation undone strictly between two
    observations leaves no trace. Interval is longer than the whole
    subject's runtime, so baseline and the mandatory final snapshot are the
    ONLY two observations, and both see the file present."""
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-authority-000000004")
    interceptor = AuthorityInterceptor(backend, handle, [WATCHED], interval=60.0)
    interceptor.start()
    _run_and_stop(backend, handle, DELETE_THEN_RESTORE)
    trusted = interceptor.stop_and_finalize()
    assert trusted is not None
    import json
    entries = json.loads(trusted)["entries"]
    assert entries == [], "the gap did not reproduce - a real violation should have been (wrongly) missed"
    backend.destroy(handle)


def test_finalize_refuses_rather_than_reporting_clean_when_the_final_export_fails(
    base: Path, docker_state: Path,
) -> None:
    """Fail-closed correctness: an interceptor that cannot confirm the final
    state must never emit a hollow, clean-looking `{"entries": []}` standing
    in for "nothing was observed" - that would reintroduce the exact defect
    #14 part (a) closed, one layer up."""
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-authority-000000005")
    interceptor = AuthorityInterceptor(backend, handle, [WATCHED], interval=60.0)
    interceptor.start()
    _run_and_stop(backend, handle, NOOP)
    backend.destroy(handle)  # the container is gone before finalize can export from it
    trusted = interceptor.stop_and_finalize()
    assert trusted is None


def test_start_raises_when_no_baseline_can_be_captured(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-authority-000000006")
    backend.destroy(handle)  # gone before the interceptor ever gets a first read
    interceptor = AuthorityInterceptor(backend, handle, [WATCHED], interval=0.05)
    with pytest.raises(RuntimeError, match="baseline"):
        interceptor.start()


def test_watching_nothing_is_refused(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-authority-000000007")
    with pytest.raises(ValueError, match="watching nothing"):
        AuthorityInterceptor(backend, handle, [], interval=0.05)
    backend.destroy(handle)


def test_a_nonpositive_interval_is_refused(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-authority-000000008")
    with pytest.raises(ValueError, match="interval"):
        AuthorityInterceptor(backend, handle, [WATCHED], interval=0.0)
    backend.destroy(handle)


def test_double_start_is_refused(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-authority-000000009")
    interceptor = AuthorityInterceptor(backend, handle, [WATCHED], interval=0.05)
    interceptor.start()
    with pytest.raises(RuntimeError, match="already been started"):
        interceptor.start()
    _run_and_stop(backend, handle, NOOP)
    interceptor.stop_and_finalize()
    backend.destroy(handle)


def test_double_finalize_is_refused(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = _prepared(backend, "a-lc-authority-000000010")
    interceptor = AuthorityInterceptor(backend, handle, [WATCHED], interval=0.05)
    interceptor.start()
    _run_and_stop(backend, handle, NOOP)
    interceptor.stop_and_finalize()
    with pytest.raises(RuntimeError, match="already been finalized"):
        interceptor.stop_and_finalize()
    backend.destroy(handle)
