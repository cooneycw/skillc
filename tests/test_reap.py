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
    removed and the attempt is reported `unknown` - never `left-running`
    (which asserts the daemon CONFIRMS something is still there, a fact this
    call could not establish), never `already-absent`, never `reaped`."""
    _run(docker_state, "orphan", _owned_labels("att-1"))
    (docker_state / ".down").touch()

    report = reap.reap(_docker_bin(docker_state), ["att-1"])
    assert report.daemon_reachable is False
    assert report.outcome_for("att-1") == "unknown"
    assert report.unknown == ("att-1",)
    assert report.reaped == ()
    assert report.left_running == ()

    (docker_state / ".down").unlink()
    still = reap.snapshot(_docker_bin(docker_state))
    assert "orphan" in still.owned  # nothing was actually removed


def test_unknown_and_left_running_are_kept_distinct_in_one_call(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orchestrator review of this PR: reporting `left-running` for BOTH
    "the daemon confirms something is still there" and "the daemon could
    not be asked" made the two indistinguishable per attempt - a caller
    processing a mixed batch could not tell "known to be running" from
    "unknown" for any individual attempt id, even though the report-level
    `daemon_reachable` flag went false. This drives one `reap()` call over
    two attempts at once: one whose container genuinely cannot be removed
    (confirmed `left-running`) and one whose OWN listing call times out
    (`unknown`), and asserts both outcomes land correctly in the SAME
    report. Confirmed red on the pre-fix code (2495473): that build has no
    `unknown` outcome at all, so `report.outcome_for("att-unreachable")`
    returned `"left-running"` there instead.
    """
    _run(docker_state, "stuck-one", _owned_labels("att-stuck"))
    (docker_state / ".stuck-stuck-one").touch()
    real_run = subprocess.run

    def _flaky_run(
        argv: list[str], *, capture_output: bool = False, env: dict[str, str] | None = None,
        check: bool = False, timeout: float | None = None, text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if any("label=skillc.attempt-id=att-unreachable" in str(a) for a in argv):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout or 0)
        return real_run(
            argv, capture_output=capture_output, env=env, check=check, timeout=timeout, text=text,
        )

    monkeypatch.setattr(reap.subprocess, "run", _flaky_run)
    report = reap.reap(_docker_bin(docker_state), ["att-stuck", "att-unreachable"])

    assert report.outcome_for("att-stuck") == "left-running"
    assert report.outcome_for("att-unreachable") == "unknown"
    assert report.left_running == ("att-stuck",)
    assert report.unknown == ("att-unreachable",)


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


def test_reap_refuses_an_empty_attempt_population(docker_state: Path) -> None:
    """Codex review, MEDIUM: an empty `attempt_ids` used to report
    `daemon_reachable=True` having checked nothing at all - refused now,
    the same rule this codebase applies to an empty record population."""
    with pytest.raises(ValueError, match="empty"):
        reap.reap(_docker_bin(docker_state), [])


def test_reap_removes_by_container_id_never_by_name(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex review, HIGH: `reap()` used to list, remove (`rm -f NAME`) and
    confirm by NAME - three separate round trips to a daemon nothing
    prevents from changing between them. A NAME can be taken by a brand-new,
    DIFFERENT container the instant the original is removed; an ID cannot,
    since it is unique to one container's lifetime. This asserts the actual
    `rm` invocation targets the container's ID, not its declared name -
    the property that makes the race impossible, not merely a scenario that
    happens not to trigger it."""
    _run(docker_state, "att-1-container", _owned_labels("att-1"))
    calls: list[list[str]] = []
    real_run = subprocess.run  # captured BEFORE patching - `subprocess` is one shared
    # module object, so `reap.subprocess` IS `subprocess` here; referring to
    # `subprocess.run` again inside `_spy` would resolve the PATCHED attribute
    # and recurse forever.

    def _spy(
        argv: list[str], *, capture_output: bool = False, env: dict[str, str] | None = None,
        check: bool = False, timeout: float | None = None, text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return real_run(
            argv, capture_output=capture_output, env=env, check=check, timeout=timeout, text=text,
        )

    monkeypatch.setattr(reap.subprocess, "run", _spy)
    report = reap.reap(_docker_bin(docker_state), ["att-1"])
    assert report.outcome_for("att-1") == "reaped"

    rm_calls = [c for c in calls if "rm" in c]
    assert len(rm_calls) == 1
    target = rm_calls[0][-1]
    assert target != "att-1-container"  # never the declared name
    assert len(target) == 12 and all(ch in "0123456789abcdef" for ch in target)  # the fake's own id shape


# --------------------------------------------------- reap_all_owned() (issue #118)


def test_reap_all_owned_removes_every_owned_container_regardless_of_attempt_id(docker_state: Path) -> None:
    """`reap()`'s broader sibling: no `attempt_ids` to pass at all - this
    demo.py's own `KeyboardInterrupt` handler needs it precisely because it
    cannot know which attempt ids were in flight when interrupted."""
    _run(docker_state, "att-1-container", _owned_labels("att-1"))
    _run(docker_state, "att-2-container", _owned_labels("att-2"))
    report = reap.reap_all_owned(_docker_bin(docker_state))
    assert report.daemon_reachable is True
    assert len(report.outcomes) == 2
    assert all(o.outcome == "reaped" for o in report.outcomes)


def test_reap_all_owned_never_touches_a_foreign_container(docker_state: Path) -> None:
    """The same label-scoping guarantee `snapshot()`/`reap()` already give -
    a container with no `OWNER_LABEL` at all is structurally unreachable to
    this sweep, not merely unlikely to be hit."""
    _run(docker_state, "att-1-container", _owned_labels("att-1"))
    _run(docker_state, "foreign-container", {"some.other.label": "x"})
    report = reap.reap_all_owned(_docker_bin(docker_state))
    assert len(report.outcomes) == 1

    still_running = subprocess.run(
        [*_docker_bin(docker_state), "ps", "-a", "--filter", "name=foreign-container", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=False,
    )
    assert "foreign-container" in still_running.stdout


def test_reap_all_owned_reports_nothing_owned_as_a_clean_empty_sweep(docker_state: Path) -> None:
    report = reap.reap_all_owned(_docker_bin(docker_state))
    assert report.daemon_reachable is True
    assert report.outcomes == ()


def test_reap_all_owned_reports_unreachable_never_a_guessed_clean_sweep(docker_state: Path) -> None:
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".down").touch()
    report = reap.reap_all_owned(_docker_bin(docker_state))
    assert report.daemon_reachable is False
    assert report.outcomes == ()


def test_reap_all_owned_removes_by_container_id_never_by_name(
    docker_state: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same ID-not-name discipline as `reap()` itself (codex review, HIGH,
    on that function) - this sibling reuses the identical act-then-confirm
    shape and must not silently regress it."""
    _run(docker_state, "att-1-container", _owned_labels("att-1"))
    calls: list[list[str]] = []
    real_run = subprocess.run

    def _spy(
        argv: list[str], *, capture_output: bool = False, env: dict[str, str] | None = None,
        check: bool = False, timeout: float | None = None, text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return real_run(
            argv, capture_output=capture_output, env=env, check=check, timeout=timeout, text=text,
        )

    monkeypatch.setattr(reap.subprocess, "run", _spy)
    report = reap.reap_all_owned(_docker_bin(docker_state))
    assert len(report.outcomes) == 1
    assert report.outcomes[0].outcome == "reaped"

    rm_calls = [c for c in calls if "rm" in c]
    assert len(rm_calls) == 1
    target = rm_calls[0][-1]
    assert target != "att-1-container"
    assert len(target) == 12 and all(ch in "0123456789abcdef" for ch in target)


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


def test_snapshot_host_paths_refuses_an_empty_declaration() -> None:
    """Codex review, MEDIUM: an empty declaration used to report `changed=()`
    indistinguishably from "checked and confirmed unchanged"."""
    with pytest.raises(ValueError, match="empty"):
        reap.snapshot_host_paths([])


def test_an_unreadable_declared_path_is_unresolved_not_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex review, MEDIUM: an `OSError` (permission denied) used to collapse
    into the same `None` as confirmed absence, so an unreadable file
    compared as "unchanged" against itself - a false claim of certainty this
    instrument does not have. It must be `unresolved`, never `changed` (we
    cannot confirm a difference) and never silently absent from both.

    Unreadability is forced by monkeypatching `Path.read_bytes`, not by
    `chmod(0o000)` (orchestrator review of PR #91, CI pipeline 138): CI's
    `python:3.12-slim` gate step runs as root, and root reads a chmod-000
    file anyway, so the permission-based version passed only for a non-root
    user - it never exercised the UNREADABLE path in CI at all. A forced
    `PermissionError` is deterministic identically as root or not.
    """
    watched = tmp_path / "watched.txt"
    watched.write_text("original\n")
    real_read_bytes = Path.read_bytes

    def _refuse_read(self: Path) -> bytes:
        if self == watched:
            raise PermissionError(f"forced unreadable for this test: {self}")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _refuse_read)
    before = reap.snapshot_host_paths([watched])
    after = reap.snapshot_host_paths([watched])

    assert before.digests[str(watched)] == reap.UNREADABLE
    result = reap.diff_host_paths(before, after)
    assert result.unresolved == (str(watched),)
    assert result.changed == ()


def test_a_declaration_added_between_snapshots_is_reported_not_ignored(tmp_path: Path) -> None:
    """Codex review, MEDIUM: `.get(key)` used to default a key missing from
    one snapshot's declarations to `None`, colliding with the legitimate
    "confirmed absent" `None` and making an added/removed declaration
    invisible even when the path itself never changed."""
    watched = tmp_path / "watched.txt"
    # `before` never declared this path at all (a genuinely different key
    # set, not merely a path that happened to be absent).
    before = reap.HostPathSnapshot(digests={})
    after = reap.snapshot_host_paths([watched])  # declared, and confirmed absent (None)

    result = reap.diff_host_paths(before, after)
    assert result.changed == (str(watched),)
    assert result.unresolved == ()
