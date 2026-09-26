"""Tests for controller-owned trial accounting and capture (#8).

Each controller refusal is shown firing on the input it exists for, beside the
input it must accept: a refusal nobody has seen fire is not evidence (ADR 0001).
The subject is `fixtures/trial-subject/fake_subject.py`, a deterministic stand-in
that can behave well, crash, hang, leave a child running, or forge records.

The end-to-end case (`test_a_complete_attempt_yields_a_bundle_check_records_accepts`)
is the green that the other cases make meaningful: the same bundle machinery that
accepts it refuses each broken variant below.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from skillc import cli, records
from skillc import trial as t

FAKE = Path(__file__).resolve().parent / "fixtures" / "trial-subject" / "fake_subject.py"

CONFIG = {"model": "fake-1", "reasoning": "low", "sandbox": "workspace-write"}


def _spec(attempts: int = 1, **extra: object) -> dict[str, object]:
    trial: dict[str, object] = {
        "label": "fake",
        "case": {"id": "slug-fix", "revision": "r1"},
        "grader": {"id": "slug-grader", "revision": "g1"},
        "subject": {"digest": "sha256:5a"},
        "client": {"name": "fake", "version": "1"},
        "image": {"digest": "sha256:1a"},
        "config": CONFIG,
        "attempts": attempts,
        **extra,
    }
    return {"experiment": "pilot", "trials": [trial]}


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return t.open_store(tmp_path / "store", forbidden=[])


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


def _only(experiment: t.Experiment) -> str:
    [(_trial, attempt)] = list(experiment.attempts())
    return str(attempt["attempt_id"])


RECEIPT = json.loads(
    (Path(__file__).resolve().parent.parent / "controls" / "installation-receipt" / "good" / "receipt.json")
    .read_text(encoding="utf-8")
)


def _run(experiment: t.Experiment, attempt_id: str, base: Path, mode: str,
         timeout: float = 20, **kwargs: object) -> tuple[Path, dict[str, object]]:
    """Install (a receipt, as #7's producer would write it), then run the subject."""
    t.add_receipt(experiment, {
        **RECEIPT, "attempt_id": attempt_id, "trial_id": experiment.trial_of(attempt_id)["trial_id"],
        "client": {"name": "fake", "version": "1"},
    })
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    stop = t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), mode],
                         cwd=workspace, timeout=timeout, grace=0.5, **kwargs)  # type: ignore[arg-type]
    return workspace, stop


def _result(experiment: t.Experiment, attempt_id: str, digests: list[str], **extra: object) -> dict[str, object]:
    return {
        "version": 2, "kind": "verified-result", "producer": "assembler",
        "attempt_id": attempt_id, "trial_id": experiment.trial_of(attempt_id)["trial_id"],
        "result_id": f"res-{attempt_id}", "grader": {"id": "slug-grader", "revision": "g1"},
        "graded_digests": digests,
        "criteria": [{"id": "c1", "mandatory": True, "outcome": "SATISFIED", "evidence": ["grader:c1"]}],
        "status": "PASS", **extra,
    }


def _capture(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return t.capture(*args, **kwargs)


def _check_records(path: Path, rule: str | None = None) -> int:
    return cli.cmd_check_records(argparse.Namespace(path=str(path), rule=rule))


def _alive(pid: int) -> bool:
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


# ------------------------------------------------------------------ the plan


def test_the_plan_exists_before_dispatch_with_controller_identities(store: Path) -> None:
    experiment = t.plan(_spec(attempts=3), store)
    ledger = records.load(experiment.root / t.LEDGER)
    assert ledger.kind == "trial-ledger" and ledger.data["producer"] == "controller"
    ids = [str(a["attempt_id"]) for _t, a in experiment.attempts()]
    assert len(set(ids)) == 3 and all(records.ID_RE.fullmatch(i) for i in ids)
    assert experiment.id.startswith("pilot-") and experiment.id != "pilot"
    # Nothing has run, yet every attempt is already in the journal as planned.
    for attempt_id in ids:
        assert [e["event"] for e in experiment.events(attempt_id)] == ["planned"]
    assert t.account(experiment)["counts"] == {"captured": 0, "not-run": 0, "unavailable": 0, "inconclusive": 0, "open": 3}


def test_the_resolved_configuration_is_stored_and_bound_by_digest(store: Path) -> None:
    experiment = t.plan(_spec(), store)
    [(trial, _a)] = list(experiment.attempts())
    digest = trial["config"]["digest"]  # type: ignore[index]
    assert digest == t.sha256_bytes(t.canonical(CONFIG))
    assert json.loads(experiment.object_path(digest).read_bytes()) == CONFIG


@pytest.mark.parametrize("spec, why", [
    ({**_spec(), "notes": "x"}, "unknown fields"),
    ({"experiment": "pilot", "trials": [{**_spec()["trials"][0], "seed": 4}]}, "unknown fields"),  # type: ignore[index]
    (_spec(attempts=True), "positive integer"),  # type: ignore[arg-type]
    (_spec(attempts=0), "positive integer"),
    ({"experiment": "pilot", "trials": []}, "empty selection"),
    ({"experiment": "../x", "trials": _spec()["trials"]}, "label"),
    ({"experiment": "pilot", "trials": [{**_spec()["trials"][0], "client": {"name": "c", "version": "1", "x": 1}}]},  # type: ignore[index]
     "unknown fields"),
    ({"experiment": "pilot", "trials": [{**_spec()["trials"][0], "grader": {"id": "g"}}]}, "no revision"),  # type: ignore[index]
    ({"experiment": "pilot", "trials": _spec()["trials"] * 2}, "twice"),  # type: ignore[operator]
])
def test_a_loose_plan_is_refused(store: Path, spec: dict[str, object], why: str) -> None:
    with pytest.raises(t.Refused, match=why):
        t.plan(spec, store)


def test_the_store_is_refused_inside_a_git_work_tree(tmp_path: Path) -> None:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "repo" / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    with pytest.raises(t.Refused, match="git work tree"):
        t.open_store(tmp_path / "repo" / "evidence", forbidden=[])
    (tmp_path / "linked").mkdir()
    (tmp_path / "linked" / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
    with pytest.raises(t.Refused, match="git work tree"):
        t.open_store(tmp_path / "linked" / "evidence", forbidden=[])
    # An empty `.git` directory is a name, not a repository.
    (tmp_path / "hollow" / ".git").mkdir(parents=True)
    assert t.open_store(tmp_path / "hollow" / "evidence", forbidden=[]).is_dir()
    assert t.open_store(tmp_path / "elsewhere", forbidden=[]).is_dir()


def test_the_store_is_refused_inside_the_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(t.Refused, match="not trial-owned"):
        t.open_store(source / "evidence", forbidden=[source])


def test_a_non_empty_directory_is_not_adopted_as_a_store(tmp_path: Path) -> None:
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "file").write_text("x")
    with pytest.raises(t.Refused, match="not a skillc store"):
        t.open_store(tmp_path / "busy", forbidden=[])


def test_the_store_is_owner_only(store: Path) -> None:
    assert store.stat().st_mode & 0o777 == 0o700


# ------------------------------------------------------------ immutability


def test_an_edited_ledger_is_refused_on_open(store: Path) -> None:
    experiment = t.plan(_spec(), store)
    assert t.Experiment.open(experiment.root).id == experiment.id
    path = experiment.root / t.LEDGER
    os.chmod(path, 0o600)
    path.write_text(path.read_text().replace('"r1"', '"r2"'))
    with pytest.raises(t.Refused, match="changed outside the controller"):
        t.Experiment.open(experiment.root)


def test_a_modified_configuration_object_is_refused_on_open(store: Path) -> None:
    experiment = t.plan(_spec(), store)
    [(trial, _a)] = list(experiment.attempts())
    path = experiment.object_path(trial["config"]["digest"])  # type: ignore[index]
    os.chmod(path, 0o600)
    path.write_bytes(t.canonical({**CONFIG, "model": "other"}))
    with pytest.raises(t.Refused, match="modified"):
        t.Experiment.open(experiment.root)


def test_a_revision_that_rewrites_a_planned_attempt_is_refused(store: Path) -> None:
    """Retries append; a revision that REPLACES a planned attempt is history
    rewritten, even when it is recorded in the history like an honest one."""
    experiment = t.plan(_spec(), store)
    forged = json.loads(json.dumps(experiment.ledger))
    forged["trials"][0]["attempts"] = [{"attempt_id": "a-111111111111"}]
    t._commit_ledger(experiment.root, forged)
    with pytest.raises(t.Refused, match="rewrote history"):
        t.Experiment.open(experiment.root)


# ------------------------------------------------------------ lifecycle


def test_a_complete_attempt_yields_a_bundle_check_records_accepts(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, stop = _run(experiment, attempt_id, base, "work")
    assert stop == {"reason": "exited", "confirmed": True, "exit_code": 0}
    manifest = _capture(experiment, attempt_id, workspace)
    assert sorted(str(a["path"]) for a in manifest["artifacts"]) == ["out.txt", "src/app.py"]
    assert t.cleanup_workspace(experiment, attempt_id)["status"] == "removed"
    lifecycle = t.finalize(experiment, attempt_id)
    assert lifecycle["disposition"] == "captured"
    assert lifecycle["cleanup"] == {"status": "removed", "failures": []}
    digests = [str(a["digest"]) for a in t.frozen_artifacts(experiment, attempt_id)]
    t.add_result(experiment, _result(experiment, attempt_id, digests))
    assert _check_records(experiment.root) == 0


def test_a_captured_attempt_without_a_result_is_not_yet_accounted(store: Path, base: Path) -> None:
    """The negative control for the green above: identical, minus the result."""
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    t.capture(experiment, attempt_id, workspace)
    t.finalize(experiment, attempt_id)
    assert _check_records(experiment.root, "attempt-accounting") == 1


def test_a_crash_is_a_confirmed_stop_with_its_exit_code(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    _ws, stop = _run(experiment, _only(experiment), base, "crash")
    assert stop == {"reason": "exited", "confirmed": True, "exit_code": 3}


def test_a_timeout_stops_the_whole_group(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, stop = _run(experiment, attempt_id, base, "hang", timeout=1.0)
    assert stop["reason"] == "timeout" and stop["confirmed"] is True
    names = [e["event"] for e in experiment.events(attempt_id)]
    assert names[-3:] == ["stop-requested", "stopped", "stop-confirmed"]
    # A budget expiry is a failed completion, not an omitted attempt: it is captured.
    t.capture(experiment, attempt_id, workspace)
    assert t.finalize(experiment, attempt_id)["stop"]["reason"] == "timeout"  # type: ignore[index]


def test_an_operator_cancellation_is_recorded_as_such(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    started = time.monotonic()
    _ws, stop = _run(experiment, _only(experiment), base, "hang",
                     cancel=lambda: time.monotonic() - started > 0.5)
    assert stop["reason"] == "operator-cancelled" and stop["confirmed"] is True


def test_a_child_left_running_by_an_exited_leader_is_stopped(store: Path, base: Path) -> None:
    """A leader that exits while its child keeps writing has not stopped."""
    experiment = t.plan(_spec(), store)
    workspace, stop = _run(experiment, _only(experiment), base, "orphan")
    child = int((workspace / "child.pid").read_text())
    assert stop["confirmed"] is True
    assert not _alive(child)


def test_a_process_that_leaves_the_group_is_NOT_seen(store: Path, base: Path) -> None:
    """The documented limit, pinned so nobody reads a confirmed stop as more than it
    is: a child that calls setsid escapes the group, and the stop is still reported
    confirmed. Containment is the Docker lane (#10), not this."""
    experiment = t.plan(_spec(), store)
    workspace, stop = _run(experiment, _only(experiment), base, "escape")
    child = int((workspace / "child.pid").read_text())
    try:
        assert stop["confirmed"] is True
        assert _alive(child), "the escaped child was stopped; update capture.md's limit"
    finally:
        os.kill(child, signal.SIGKILL)


def test_a_subject_that_cannot_launch_is_unavailable(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    stop = t.run_attempt(experiment, attempt_id, [str(base / "no-such-client")], cwd=workspace, timeout=5)
    assert stop["reason"] == "launch-failed"
    with pytest.raises(t.Refused, match="never ran"):
        t.capture(experiment, attempt_id, workspace)
    t.cleanup_workspace(experiment, attempt_id)
    lifecycle = t.finalize(experiment, attempt_id)
    assert lifecycle["disposition"] == "unavailable" and "could not be launched" in str(lifecycle["reason"])


def test_an_attempt_is_dispatched_once(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    with pytest.raises(t.Refused, match="already dispatched"):
        t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), "work"], cwd=workspace, timeout=5)


def test_the_subject_is_never_told_its_attempt_identity(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "env")
    given = (workspace / "env.txt").read_text()
    assert attempt_id not in given and experiment.id not in given


# ------------------------------------------------------------ accounting


def test_no_planned_attempt_is_silently_dropped(store: Path, base: Path) -> None:
    """Three planned; one captured, one unavailable, one never dispatched. Closing
    the experiment accounts for all three - the undispatched one as not-run."""
    experiment = t.plan(_spec(attempts=3), store)
    ran, failed, idle = [str(a["attempt_id"]) for _t, a in experiment.attempts()]
    workspace, _stop = _run(experiment, ran, base, "work")
    t.capture(experiment, ran, workspace)
    t.run_attempt(experiment, failed, [str(base / "missing")], cwd=base, timeout=5)
    report = t.close(experiment, reason="experiment budget exhausted")
    assert report["population"] == 3
    assert report["counts"] == {"captured": 1, "not-run": 1, "unavailable": 1, "inconclusive": 0, "open": 0}
    idle_record = json.loads((experiment.root / f"lifecycle-{idle}.json").read_bytes())
    assert idle_record["reason"] == "experiment budget exhausted"
    digests = [str(a["digest"]) for a in t.frozen_artifacts(experiment, ran)]
    t.add_result(experiment, _result(experiment, ran, digests))
    assert _check_records(experiment.root) == 0


def test_capture_is_refused_before_a_confirmed_stop(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    with pytest.raises(t.Refused, match="no confirmed stop"):
        t.capture(experiment, attempt_id, base)
    experiment.record(attempt_id, "dispatched")
    experiment.record(attempt_id, "stopped", reason="timeout", confirmed=False)
    experiment.record(attempt_id, "stop-unconfirmed")
    with pytest.raises(t.Refused, match="no confirmed stop"):
        t.capture(experiment, attempt_id, base)
    lifecycle = t.finalize(experiment, attempt_id)
    assert lifecycle["disposition"] == "inconclusive"
    assert "never confirmed" in str(lifecycle["reason"])


def test_an_empty_capture_is_inconclusive_not_clean(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    with pytest.raises(t.Refused, match="empty capture"):
        t.capture(experiment, attempt_id, workspace, include=("nothing-matches",))
    lifecycle = t.finalize(experiment, attempt_id)
    assert lifecycle["disposition"] == "inconclusive" and "capture failed" in str(lifecycle["reason"])


def test_a_capture_is_frozen_once(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    t.capture(experiment, attempt_id, workspace)
    with pytest.raises(t.Refused, match="already captured"):
        t.capture(experiment, attempt_id, workspace)


def test_finalize_derives_captured_and_will_not_be_overruled(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(attempts=2), store)
    first, second = [str(a["attempt_id"]) for _t, a in experiment.attempts()]
    with pytest.raises(t.Refused, match="not 'captured'"):
        t.finalize(experiment, first, disposition="captured", reason="trust me")
    workspace, _stop = _run(experiment, first, base, "work")
    t.capture(experiment, first, workspace)
    with pytest.raises(t.Refused, match="not the caller's to change"):
        t.finalize(experiment, first, disposition="unavailable", reason="provider down")
    lifecycle = t.finalize(experiment, second, disposition="unavailable", reason="provider unreachable")
    assert lifecycle["disposition"] == "unavailable"
    with pytest.raises(t.Refused, match="already finalized"):
        t.finalize(experiment, second)


# ------------------------------------------------------------ what capture exports


def test_hostile_output_exports_nothing_it_must_not(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "hostile")
    manifest = _capture(experiment, attempt_id, workspace)
    exported = {str(a["path"]) for a in manifest["artifacts"]}
    assert exported == {"out.txt", "src/app.py", "task.json"}
    excluded = {str(x["path"]): str(x["reason"]) for x in manifest["exclusions"]}
    assert "symlink" in excluded["leak.txt"] and "symlink" in excluded["etc-link"]
    assert "never exported" in excluded[".env"] and "never exported" in excluded["id_rsa"]
    assert "AWS access key" in excluded["notes.txt"]
    assert ".git/" in excluded and "not a regular file" in excluded["pipe"]
    # The manifest names the exclusions but never carries the secret values.
    text = (experiment.root / f"manifest-{attempt_id}.json").read_text()
    assert "hunter2" not in text and "AKIAABCDEFGHIJKLMNOP" not in text
    # And no stored object holds them either.
    blobs = b"".join(p.read_bytes() for p in (experiment.root / t.OBJECTS).iterdir())
    assert b"hunter2" not in blobs and b"AKIAABCDEFGHIJKLMNOP" not in blobs


def test_a_forged_result_and_a_sentinel_are_only_bytes(store: Path, base: Path) -> None:
    """Coder Eval pitfalls 1-3: a subject-written result, an echoed config and a
    stdout sentinel. Each is captured with its origin; none becomes a verdict or a
    provenance claim, and the attempt remains owed a grade."""
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "hostile")
    manifest = _capture(experiment, attempt_id, workspace)
    t.finalize(experiment, attempt_id)
    assert not list(experiment.root.glob("result-*.json"))
    streams = {str(o["stream"]): o for o in manifest["observations"]}
    stdout = streams["client-events"]
    assert stdout["origin"] == "client-reported" and stdout["attempt_id"] == attempt_id
    assert b"skillc-result" in experiment.object_path(str(stdout["digest"])).read_bytes()
    assert streams["process-lifecycle"]["origin"] == "observed"
    assert _check_records(experiment.root, "attempt-accounting") == 1


def test_a_capture_over_its_bound_is_partial_and_says_so(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    manifest = _capture(experiment, attempt_id, workspace, limits=t.Limits(max_files=1))
    assert len(manifest["artifacts"]) == 1
    assert any("already holds 1 files" in f for f in manifest["capture_failures"])


def test_a_file_over_the_per_file_bound_is_not_truncated(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    manifest = _capture(experiment, attempt_id, workspace, limits=t.Limits(max_file_bytes=15))
    assert [a["path"] for a in manifest["artifacts"]] == ["out.txt"]
    assert any("larger than 15" in f for f in manifest["capture_failures"])


def test_an_output_root_that_is_a_link_is_refused(store: Path, base: Path, tmp_path: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    link = tmp_path / "link"
    link.symlink_to(workspace)
    with pytest.raises(t.Refused, match="not a directory"):
        t.capture(experiment, attempt_id, link)


# ------------------------------------------------------------ imported records


@pytest.fixture
def stopped(store: Path, base: Path) -> Iterator[tuple[t.Experiment, str, Path]]:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    yield experiment, attempt_id, workspace


def _offer(where: Path, payload: object, digest: str | None | bool = True) -> t.Import:
    data = json.dumps(payload).encode()
    where.write_bytes(data)
    reported = t.sha256_bytes(data) if digest is True else (digest or None)
    return t.Import(path=where, stream="client-session", origin="client-reported", digest=reported)  # type: ignore[arg-type]


def test_imported_records_are_bound_or_refused(stopped: tuple[t.Experiment, str, Path], tmp_path: Path) -> None:
    experiment, attempt_id, workspace = stopped
    good = _offer(tmp_path / "good.json", {"attempt_id": attempt_id, "events": 3})
    stale = _offer(tmp_path / "stale.json", {"attempt_id": "a-0123456789ab", "status": "PASS"})
    undigested = _offer(tmp_path / "nodigest.json", {"events": 1}, digest=None)
    altered = _offer(tmp_path / "altered.json", {"events": 1}, digest="sha256:" + "0" * 64)
    manifest = _capture(experiment, attempt_id, workspace, imports=(good, stale, undigested, altered))
    bound = [o for o in manifest["observations"] if o["stream"] == "client-session"]
    assert len(bound) == 1 and bound[0]["attempt_id"] == attempt_id and bound[0]["origin"] == "client-reported"
    failures = "\n".join(manifest["capture_failures"])
    assert "stale record" in failures and "a-0123456789ab" in failures
    assert "no transport digest" in failures
    assert "do not match the reported digest" in failures


def test_a_stale_line_in_a_jsonl_record_is_refused(stopped: tuple[t.Experiment, str, Path], tmp_path: Path) -> None:
    experiment, attempt_id, workspace = stopped
    path = tmp_path / "events.jsonl"
    data = (json.dumps({"attempt_id": attempt_id}) + "\n" + json.dumps({"attempt": "a-999999999999"}) + "\n").encode()
    path.write_bytes(data)
    item = t.Import(path=path, stream="client-session", origin="client-reported", digest=t.sha256_bytes(data))
    manifest = _capture(experiment, attempt_id, workspace, imports=(item,))
    assert any("stale record" in f for f in manifest["capture_failures"])


# ------------------------------------------------------------ frozen bytes and results


def _captured(store: Path, base: Path) -> tuple[t.Experiment, str, list[str]]:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    t.capture(experiment, attempt_id, workspace)
    t.cleanup_workspace(experiment, attempt_id)
    t.finalize(experiment, attempt_id)
    return experiment, attempt_id, [str(a["digest"]) for a in t.frozen_artifacts(experiment, attempt_id)]


def test_a_modified_artifact_cannot_become_a_verified_result(store: Path, base: Path) -> None:
    experiment, attempt_id, digests = _captured(store, base)
    target = experiment.object_path(digests[0])
    os.chmod(target, 0o600)
    target.write_bytes(b"tampered\n")
    with pytest.raises(t.Refused, match="modified"):
        t.frozen_artifacts(experiment, attempt_id)
    with pytest.raises(t.Refused, match="modified"):
        t.add_result(experiment, _result(experiment, attempt_id, digests))
    assert not list(experiment.root.glob("result-*.json"))


def test_a_result_for_bytes_nobody_captured_is_refused(store: Path, base: Path) -> None:
    experiment, attempt_id, _digests = _captured(store, base)
    with pytest.raises(t.Refused, match="does not hold"):
        t.add_result(experiment, _result(experiment, attempt_id, ["sha256:" + "f" * 64]))


def test_a_mismatched_manifest_is_refused(store: Path, base: Path) -> None:
    experiment, attempt_id, _digests = _captured(store, base)
    path = experiment.root / f"manifest-{attempt_id}.json"
    os.chmod(path, 0o600)
    path.write_text(path.read_text().replace(attempt_id, "a-aaaaaaaaaaaa"))
    with pytest.raises(t.Refused, match="stale or mismatched"):
        t.frozen_artifacts(experiment, attempt_id)


def test_a_result_for_an_uncaptured_attempt_is_refused(store: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    t.finalize(experiment, attempt_id)
    with pytest.raises(t.Refused, match="not a finalized capture"):
        t.add_result(experiment, _result(experiment, attempt_id, ["sha256:aa"]))


def test_a_result_is_never_overwritten(store: Path, base: Path) -> None:
    experiment, attempt_id, digests = _captured(store, base)
    t.add_result(experiment, _result(experiment, attempt_id, digests))
    stored = (experiment.root / f"result-res-{attempt_id}.json").read_bytes()
    # Admission refuses the conflicting verdict first; the write-once layer below
    # it refuses the same name even when nothing else would.
    with pytest.raises(t.Refused, match="conflicting verdict"):
        t.add_result(experiment, _result(experiment, attempt_id, digests, status="FAIL", criteria=[
            {"id": "c1", "mandatory": True, "outcome": "VIOLATED", "evidence": ["x"]}]))
    with pytest.raises(t.Refused, match="never overwrites"):
        t._write_new(experiment.root / f"result-res-{attempt_id}.json", b"{}")
    assert (experiment.root / f"result-res-{attempt_id}.json").read_bytes() == stored


def test_a_regrade_links_to_its_retained_original(store: Path, base: Path) -> None:
    experiment, attempt_id, digests = _captured(store, base)
    with pytest.raises(t.Refused, match="not retained"):
        t.add_result(experiment, _result(experiment, attempt_id, digests, result_id="res-2", regrade_of="res-x"))
    t.add_result(experiment, _result(experiment, attempt_id, digests))
    t.add_result(experiment, _result(experiment, attempt_id, digests, result_id="res-2",
                                     regrade_of=f"res-{attempt_id}", grader={"id": "slug-grader", "revision": "g2"}))
    assert len(list(experiment.root.glob("result-*.json"))) == 2
    assert _check_records(experiment.root) == 0


def test_a_retry_is_a_new_linked_attempt_and_erases_nothing(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    original = _only(experiment)
    with pytest.raises(t.Refused, match="not finalized"):
        t.retry(experiment, original)
    t.run_attempt(experiment, original, [str(base / "missing")], cwd=base, timeout=5)
    first = t.finalize(experiment, original)
    new = t.retry(experiment, original)
    assert new != original
    reopened = t.Experiment.open(experiment.root)
    attempts = [a for _t, a in reopened.attempts()]
    assert attempts == [{"attempt_id": original}, {"attempt_id": new, "retry_of": original}]
    assert json.loads((experiment.root / f"lifecycle-{original}.json").read_bytes()) == first
    workspace, _stop = _run(reopened, new, base, "work")
    t.capture(reopened, new, workspace)
    t.finalize(reopened, new)
    digests = [str(a["digest"]) for a in t.frozen_artifacts(reopened, new)]
    t.add_result(reopened, _result(reopened, new, digests))
    assert _check_records(experiment.root) == 0


# ------------------------------------------------------------ cleanup


def test_cleanup_removes_only_what_it_owns_and_is_safe_to_repeat(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    assert t.cleanup_workspace(experiment, attempt_id)["status"] == "removed"
    assert not workspace.parent.exists()
    assert t.cleanup_workspace(experiment, attempt_id)["status"] == "already-absent"


def test_cleanup_refuses_a_workspace_it_does_not_own(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    (workspace.parent / ".skillc-owned").write_text(json.dumps({"nonce": "someone-else"}))
    assert t.cleanup_workspace(experiment, attempt_id)["status"] == "refused-not-owned"
    assert workspace.exists()


def test_a_workspace_is_never_allocated_inside_the_store(store: Path) -> None:
    experiment = t.plan(_spec(), store)
    with pytest.raises(t.Refused, match="inside the evidence store"):
        t.allocate_workspace(experiment, _only(experiment), store / "scratch", forbidden=[])


def test_an_uncleaned_workspace_is_reported_not_hidden(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    workspace, _stop = _run(experiment, attempt_id, base, "work")
    t.capture(experiment, attempt_id, workspace)
    lifecycle = t.finalize(experiment, attempt_id)
    assert lifecycle["cleanup"] == {"status": "partial", "failures": ["the workspace was never cleaned up"]}


# ------------------------------------------------------------ counter-model review fixes


def test_capture_is_bound_to_the_attempts_own_workspace(store: Path, base: Path) -> None:
    """Attempt A may not freeze attempt B's workspace - possibly still running -
    under A's identity."""
    experiment = t.plan(_spec(attempts=2), store)
    first, second = [str(a["attempt_id"]) for _t, a in experiment.attempts()]
    _ws_a, _stop = _run(experiment, first, base, "work")
    ws_b, _stop = _run(experiment, second, base, "work")
    with pytest.raises(t.Refused, match="own workspace"):
        t.capture(experiment, first, ws_b)
    assert _capture(experiment, first)["attempt_id"] == first


def test_capture_is_refused_once_the_attempt_is_finalized(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    _run(experiment, attempt_id, base, "work")
    assert t.finalize(experiment, attempt_id)["disposition"] == "inconclusive"
    with pytest.raises(t.Refused, match="already finalized"):
        t.capture(experiment, attempt_id)


def test_an_interrupted_controller_still_stops_the_subject(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    started = time.monotonic()

    def interrupt() -> bool:
        if time.monotonic() - started > 0.5:
            raise KeyboardInterrupt
        return False

    with pytest.raises(KeyboardInterrupt):
        _run(experiment, attempt_id, base, "hang", cancel=interrupt)
    [pid] = [e["pid"] for e in experiment.events(attempt_id) if e["event"] == "started"]
    assert not _alive(int(str(pid)))
    names = [e["event"] for e in experiment.events(attempt_id)]
    assert names[-2:] == ["stopped", "stop-confirmed"]


def test_an_interrupted_ledger_commit_is_completed_not_refused(store: Path) -> None:
    """History is written before the ledger, so a crash between the two leaves a
    recorded revision to complete - not a legitimate ledger that reads as tampered."""
    experiment = t.plan(_spec(), store)
    extended = json.loads(json.dumps(experiment.ledger))
    extended["trials"][0]["attempts"].append({"attempt_id": "a-222222222222", "retry_of": _only(experiment)})
    digest = t._put_object(experiment.root, t._dump(extended))
    t._append(experiment.root / t.HISTORY, {"digest": digest, "at": "crash"})
    reopened = t.Experiment.open(experiment.root)
    assert len([a for _t, a in reopened.attempts()]) == 2


def test_frozen_artifacts_refuses_an_empty_manifest(store: Path, base: Path) -> None:
    experiment, attempt_id, _digests = _captured(store, base)
    path = experiment.root / f"manifest-{attempt_id}.json"
    manifest = json.loads(path.read_bytes())
    os.chmod(path, 0o600)
    path.write_text(json.dumps({**manifest, "artifacts": []}))
    with pytest.raises(t.Refused, match="not valid"):
        t.frozen_artifacts(experiment, attempt_id)


def test_a_stream_over_its_bound_is_partial(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    _run(experiment, attempt_id, base, "hostile")
    manifest = _capture(experiment, attempt_id, limits=t.Limits(max_stream_bytes=4))
    [stdout] = [o for o in manifest["observations"] if o["stream"] == "client-events"]
    assert stdout["coverage"] == "partial" and stdout["size"] == 4
    assert any("truncated to 4" in f for f in manifest["capture_failures"])


def test_a_stale_receipt_is_refused_at_admission(store: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    stale = {**RECEIPT, "attempt_id": attempt_id, "trial_id": experiment.trial_of(attempt_id)["trial_id"],
             "client": {"name": "fake", "version": "1"}, "subject": {**RECEIPT["subject"], "digest": "sha256:old"}}
    with pytest.raises(t.Refused, match="stale receipt"):
        t.add_receipt(experiment, stale)


def test_a_result_under_an_unplanned_grader_is_refused_at_admission(store: Path, base: Path) -> None:
    experiment, attempt_id, digests = _captured(store, base)
    with pytest.raises(t.Refused, match="contradicts"):
        t.add_result(experiment, _result(experiment, attempt_id, digests, grader={"id": "other", "revision": "g1"}))


def test_a_regrade_of_other_bytes_is_refused_at_admission(store: Path, base: Path) -> None:
    experiment = t.plan(_spec(), store)
    attempt_id = _only(experiment)
    _run(experiment, attempt_id, base, "work")
    manifest = _capture(experiment, attempt_id)
    t.cleanup_workspace(experiment, attempt_id)
    t.finalize(experiment, attempt_id)
    both = [str(a["digest"]) for a in manifest["artifacts"]]
    t.add_result(experiment, _result(experiment, attempt_id, both))
    with pytest.raises(t.Refused, match="different bytes"):
        t.add_result(experiment, _result(experiment, attempt_id, both[:1], result_id="res-2",
                                         regrade_of=f"res-{attempt_id}"))
