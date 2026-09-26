"""Tests for `skillc/reap.py` (#79): label-scoped reaping and resource
snapshots, against the fake `docker` CLI (`tests/fixtures/docker-backend/
fake_docker.py`) - the real daemon boundary is owed to the operator's live
run (#10), exactly as `docker_backend.py` itself states.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from skillc import reap
from skillc.docker_backend import ATTEMPT_LABEL_KEY, OWNER_LABEL_KEY, OWNER_LABEL_VALUE

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


@pytest.fixture
def docker_state(tmp_path: Path) -> Path:
    return tmp_path / "docker-state"


def _run(docker_state: Path, name: str, labels: dict[str, str]) -> None:
    argv = [*_docker_bin(docker_state), "run", "--rm", "-d", "--name", name]
    for key, value in labels.items():
        argv += ["--label", f"{key}={value}"]
    argv += ["--", "fake-image:1", "sleep", "infinity"]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def _owned_labels(attempt_id: str) -> dict[str, str]:
    return {OWNER_LABEL_KEY: OWNER_LABEL_VALUE, ATTEMPT_LABEL_KEY: attempt_id}


# --------------------------------------------------------------- snapshot()

def test_snapshot_partitions_owned_from_foreign(docker_state: Path) -> None:
    _run(docker_state, "ours", _owned_labels("att-1"))
    _run(docker_state, "foreign-lookalike", {"some.other.label": "x"})
    snap = reap.snapshot(_docker_bin(docker_state))
    assert snap.reachable is True
    assert snap.owned == frozenset({"ours"})
    assert snap.foreign == frozenset({"foreign-lookalike"})


def test_snapshot_is_unreachable_never_empty_when_the_daemon_is_down(docker_state: Path) -> None:
    docker_state.mkdir(parents=True)
    (docker_state / ".down").touch()
    snap = reap.snapshot(_docker_bin(docker_state))
    assert snap.reachable is False
    assert snap.owned == frozenset()
    assert snap.foreign == frozenset()


# ------------------------------------------------------------------ diff()

def test_diff_flags_a_leak_in_one_direction(docker_state: Path) -> None:
    before = reap.snapshot(_docker_bin(docker_state))
    _run(docker_state, "left-running", _owned_labels("att-1"))
    after = reap.snapshot(_docker_bin(docker_state))
    result = reap.diff(before, after)
    assert result.comparable is True
    assert result.leaked == frozenset({"left-running"})
    assert result.foreign_vanished == frozenset()


def test_diff_flags_a_foreign_disappearance_in_the_other_direction(docker_state: Path) -> None:
    _run(docker_state, "foreign-1", {"some.other.label": "x"})
    before = reap.snapshot(_docker_bin(docker_state))
    subprocess.run([*_docker_bin(docker_state), "rm", "-f", "foreign-1"], check=True, capture_output=True)
    after = reap.snapshot(_docker_bin(docker_state))
    result = reap.diff(before, after)
    assert result.comparable is True
    assert result.foreign_vanished == frozenset({"foreign-1"})
    assert result.leaked == frozenset()


def test_diff_is_not_comparable_across_an_unreachable_snapshot(docker_state: Path) -> None:
    before = reap.snapshot(_docker_bin(docker_state))
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".down").touch()
    after = reap.snapshot(_docker_bin(docker_state))
    result = reap.diff(before, after)
    assert result.comparable is False
    assert result.leaked == frozenset()
    assert result.foreign_vanished == frozenset()


# ------------------------------------------------------------------ reap()

def test_a_container_left_running_on_purpose_is_detected_and_reaped(docker_state: Path) -> None:
    """Control #1 (#79's own wording): a container left running is detected,
    and reaping removes it."""
    _run(docker_state, "orphan", _owned_labels("att-1"))
    before = reap.snapshot(_docker_bin(docker_state))
    assert "orphan" in before.owned

    report = reap.reap(_docker_bin(docker_state), ["att-1"])
    assert report.daemon_reachable is True
    assert report.outcome_for("att-1") == "reaped"
    assert report.reaped == ("att-1",)

    after = reap.snapshot(_docker_bin(docker_state))
    assert "orphan" not in after.owned


def test_a_foreign_lookalike_is_never_touched(docker_state: Path) -> None:
    """Control #2: a foreign container carrying a similar name but not our
    label is never touched - proven both by the snapshot and by the fake
    CLI's own state (rm was never issued against it)."""
    _run(docker_state, "skillc-att-1", {"some.other.label": "x"})  # looks like ours, is not
    _run(docker_state, "att-1-orphan", _owned_labels("att-1"))

    report = reap.reap(_docker_bin(docker_state), ["att-1"])
    assert report.outcome_for("att-1") == "reaped"

    after = reap.snapshot(_docker_bin(docker_state))
    assert "skillc-att-1" in after.foreign  # untouched: still exists
    assert "att-1-orphan" not in after.owned  # the real one is gone


def test_an_already_absent_attempt_is_idempotent_not_an_error(docker_state: Path) -> None:
    report = reap.reap(_docker_bin(docker_state), ["never-existed"])
    assert report.daemon_reachable is True
    assert report.outcome_for("never-existed") == "already-absent"

    # Calling it again changes nothing.
    report2 = reap.reap(_docker_bin(docker_state), ["never-existed"])
    assert report2.outcome_for("never-existed") == "already-absent"


def test_reaping_two_attempts_only_removes_the_named_ones(docker_state: Path) -> None:
    _run(docker_state, "keep-me", _owned_labels("att-keep"))
    _run(docker_state, "reap-me", _owned_labels("att-reap"))

    report = reap.reap(_docker_bin(docker_state), ["att-reap"])
    assert report.outcome_for("att-reap") == "reaped"
    assert report.outcome_for("att-keep") is None  # never asked about

    after = reap.snapshot(_docker_bin(docker_state))
    assert after.owned == frozenset({"keep-me"})


def test_unknown_never_reaps_when_the_daemon_is_unreachable(docker_state: Path) -> None:
    """UNKNOWN never reaps: the daemon cannot even be asked, so nothing is
    removed and the attempt is reported left-running, never already-absent
    and never reaped - the two are different facts."""
    _run(docker_state, "orphan", _owned_labels("att-1"))
    (docker_state / ".down").touch()

    report = reap.reap(_docker_bin(docker_state), ["att-1"])
    assert report.daemon_reachable is False
    assert report.outcome_for("att-1") == "left-running"
    assert report.reaped == ()

    (docker_state / ".down").unlink()
    still = reap.snapshot(_docker_bin(docker_state))
    assert "orphan" in still.owned  # nothing was actually removed


def test_a_container_that_cannot_be_confirmed_removed_is_left_running(docker_state: Path) -> None:
    """`rm -f` reporting success is not trusted alone (the same rule
    `DockerBackend.confirm_absent` already applies to a single attempt):
    the fake CLI's `.stuck-NAME` sentinel makes `rm` lie about success, and
    the follow-up list must catch that the container is still there."""
    _run(docker_state, "stuck-one", _owned_labels("att-1"))
    (docker_state / ".stuck-stuck-one").touch()

    report = reap.reap(_docker_bin(docker_state), ["att-1"])
    assert report.outcome_for("att-1") == "left-running"
    assert report.reaped == ()


# --------------------------------------------------- declared host paths

def test_an_unmodified_declared_host_path_reports_no_change(tmp_path: Path) -> None:
    watched = tmp_path / "watched.txt"
    watched.write_text("original\n")
    before = reap.snapshot_host_paths([watched])
    after = reap.snapshot_host_paths([watched])
    assert reap.diff_host_paths(before, after).changed == ()


def test_a_deliberately_modified_declared_host_path_is_reported(tmp_path: Path) -> None:
    """Control #3 (#79's own wording): a deliberately modified declared host
    path is reported."""
    watched = tmp_path / "watched.txt"
    watched.write_text("original\n")
    before = reap.snapshot_host_paths([watched])

    watched.write_text("tampered\n")
    after = reap.snapshot_host_paths([watched])

    result = reap.diff_host_paths(before, after)
    assert result.changed == (str(watched),)


def test_a_declared_path_that_appears_or_disappears_is_reported(tmp_path: Path) -> None:
    appears = tmp_path / "appears.txt"
    before = reap.snapshot_host_paths([appears])
    appears.write_text("new\n")
    after = reap.snapshot_host_paths([appears])
    assert reap.diff_host_paths(before, after).changed == (str(appears),)


def test_an_unrelated_undeclared_host_path_is_never_examined(tmp_path: Path) -> None:
    """States the limitation directly: only declared paths are ever hashed -
    a change elsewhere on the host is invisible to this check by design."""
    watched = tmp_path / "watched.txt"
    watched.write_text("original\n")
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("original\n")

    before = reap.snapshot_host_paths([watched])
    unrelated.write_text("tampered\n")  # never declared, never checked
    after = reap.snapshot_host_paths([watched])

    assert reap.diff_host_paths(before, after).changed == ()
