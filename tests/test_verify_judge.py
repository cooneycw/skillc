"""Integration tests: the judge seam wired into `verify.grade` (#69).

Reuses the same real experiment/subject/grader setup `tests/test_verify.py`
established for #9, so a judge-enabled grade is proven against a REAL
captured attempt, not a synthetic result dict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from skillc import cli, judge, verify
from skillc import trial as t

HERE = Path(__file__).resolve().parent
FAKE = HERE / "fixtures" / "trial-subject" / "fake_subject.py"
TASK = HERE.parent / "evals" / "level1" / "slug-small-fix"
REFERENCE = TASK / "reference" / "src" / "slugify.py"
GRADER = verify.GraderDef.load(TASK)
RECEIPT = json.loads((HERE.parent / "controls" / "installation-receipt" / "good" / "receipt.json")
                     .read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_quarantine_leaks() -> object:
    verify.clear_quarantine()
    yield
    verify.clear_quarantine()


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return t.open_store(tmp_path / "store", forbidden=[])


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def grading(tmp_path: Path) -> Path:
    path = tmp_path / "grade"
    path.mkdir()
    return path


def _plan(store: Path) -> tuple[t.Experiment, str]:
    spec: dict[str, object] = {"experiment": "verify", "trials": [{
        "label": "slug",
        "case": {"id": "slug-small-fix", "revision": "1"},
        "grader": GRADER.identity(),
        "subject": {"digest": "sha256:5a"},
        "client": {"name": "fake", "version": "1"},
        "image": {"digest": "sha256:1a"},
        "config": {"model": "fake-1"},
        "attempts": 1,
    }]}
    experiment = t.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    return experiment, str(attempt["attempt_id"])


def _captured(store: Path, base: Path, source: Path) -> tuple[t.Experiment, str]:
    experiment, attempt_id = _plan(store)
    t.add_receipt(experiment, {
        **RECEIPT, "attempt_id": attempt_id, "trial_id": experiment.trial_of(attempt_id)["trial_id"],
        "client": {"name": "fake", "version": "1"},
    })
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    stop = t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), "slug-from", str(source)],
                         cwd=workspace, timeout=20, grace=0.5)
    assert stop["confirmed"] is True
    t.capture(experiment, attempt_id, workspace)
    t.cleanup_workspace(experiment, attempt_id)
    assert t.finalize(experiment, attempt_id)["disposition"] == "captured"
    return experiment, attempt_id


def _check_records(path: Path) -> int:
    return cli.cmd_check_records(argparse.Namespace(path=str(path), rule=None))


def _dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def test_grade_with_no_judges_is_unchanged(store: Path, base: Path, grading: Path) -> None:
    experiment, attempt_id = _captured(store, base, REFERENCE)
    result = verify.grade(experiment, attempt_id, GRADER, grading)
    verification = _dict(result["verification"])
    assert verification["tiers_enabled"] == [verify.GRADING_TIER]
    assert set(_dict(verification["verdicts"])) == {verify.GRADING_TIER}
    assert verification["disagreement"] == {"available": False, "reason": verify.DISAGREEMENT_UNAVAILABLE_REASON}
    assert _check_records(experiment.root) == 0


def test_grade_with_two_judges_records_both_tiers_and_disagreement(store: Path, base: Path, grading: Path) -> None:
    experiment, attempt_id = _captured(store, base, REFERENCE)
    judges = {
        judge.SAME_MODEL_TIER: judge.FakeJudge(name="same", outcome="SATISFIED"),
        judge.INDEPENDENT_TIER: judge.FakeJudge(name="indep", outcome="VIOLATED"),
    }
    result = verify.grade(experiment, attempt_id, GRADER, grading, judges=judges, goal_text="fix the slug")
    verification = _dict(result["verification"])
    verdicts = _dict(verification["verdicts"])
    tiers_enabled = verification["tiers_enabled"]
    assert isinstance(tiers_enabled, list)
    assert set(tiers_enabled) == {verify.GRADING_TIER, judge.SAME_MODEL_TIER, judge.INDEPENDENT_TIER}
    assert _dict(verdicts[judge.SAME_MODEL_TIER])["status"] == "PASS"
    assert _dict(verdicts[judge.INDEPENDENT_TIER])["status"] == "FAIL"
    # The top-level status is the deterministic tier's own, never a blend
    # with the judge tiers (#69's own requirement).
    assert result["status"] == _dict(verdicts[verify.GRADING_TIER])["status"]
    disagreement = _dict(verification["disagreement"])
    assert disagreement["available"] is True
    disagreement_count = disagreement["disagreement_count"]
    assert isinstance(disagreement_count, int) and disagreement_count > 0
    # check-records accepts this shape - proves the seam produces a record
    # `verdict-tiers` (#88) actually certifies, not merely a shape this test
    # itself invented.
    assert _check_records(experiment.root) == 0


def test_grade_with_one_unavailable_judge_still_reports_the_other(store: Path, base: Path, grading: Path) -> None:
    """Per-tier availability: one judge unavailable gives that tier
    UNAVAILABLE while the other still reports, and the deterministic tier is
    entirely unaffected."""
    experiment, attempt_id = _captured(store, base, REFERENCE)
    judges = {
        judge.SAME_MODEL_TIER: judge.FakeJudge(name="same", outcome="SATISFIED"),
        judge.INDEPENDENT_TIER: judge.FakeJudge(name="indep", unavailable="server unreachable"),
    }
    result = verify.grade(experiment, attempt_id, GRADER, grading, judges=judges, goal_text="fix the slug")
    verification = _dict(result["verification"])
    verdicts = _dict(verification["verdicts"])
    assert _dict(verdicts[judge.SAME_MODEL_TIER])["status"] == "PASS"
    independent_verdict = _dict(verdicts[judge.INDEPENDENT_TIER])
    assert independent_verdict["status"] == "UNAVAILABLE"
    assert independent_verdict["reason"] == "server unreachable"
    assert _dict(verdicts[verify.GRADING_TIER])["status"] == "PASS"
    assert verification["disagreement"] == {"available": False, "reason": judge.DISAGREEMENT_UNAVAILABLE_REASON}
    assert _check_records(experiment.root) == 0


def test_grade_refuses_and_writes_nothing_when_goal_text_leaks(store: Path, base: Path, grading: Path) -> None:
    """A leak, unlike an unreachable judge, is a refusal: nothing is written,
    and the deterministic grade that would otherwise have succeeded never
    happens either - candidate-carried machine identity must never reach an
    external judge process."""
    experiment, attempt_id = _captured(store, base, REFERENCE)
    judges = {judge.SAME_MODEL_TIER: judge.FakeJudge(outcome="SATISFIED")}
    before = list((experiment.root / "objects").rglob("*"))
    with pytest.raises(verify.Refused, match="machine-identity"):
        verify.grade(experiment, attempt_id, GRADER, grading, judges=judges,
                     goal_text="see /home/alice/notes for context")
    # No result was written for this attempt.
    results = [p for p in experiment.root.glob("result-*.json")]
    assert results == []
    assert list((experiment.root / "objects").rglob("*")) == before


def test_grade_refuses_the_deterministic_tier_name_as_a_judge_key(store: Path, base: Path, grading: Path) -> None:
    """Red case from cross-model review: passing `judges={"deterministic":
    ...}` would silently overwrite `verdicts.deterministic` with a judge's
    fabricated verdict while the top-level status/criteria stayed the
    ORIGINAL deterministic ones - a caller could not detect the mismatch
    without comparing the two by hand. Refused before any grading work
    starts, for any key outside the real judge tiers."""
    experiment, attempt_id = _captured(store, base, REFERENCE)
    judges = {verify.GRADING_TIER: judge.FakeJudge(outcome="VIOLATED")}
    with pytest.raises(verify.Refused, match="deterministic"):
        verify.grade(experiment, attempt_id, GRADER, grading, judges=judges, goal_text="fix the slug")
    assert list(experiment.root.glob("result-*.json")) == []


def test_grade_refuses_an_unknown_judge_tier_name(store: Path, base: Path, grading: Path) -> None:
    experiment, attempt_id = _captured(store, base, REFERENCE)
    judges = {"tier-4": judge.FakeJudge(outcome="SATISFIED")}
    with pytest.raises(verify.Refused, match="not one of"):
        verify.grade(experiment, attempt_id, GRADER, grading, judges=judges, goal_text="fix the slug")
