"""Tests for the calibration endpoint and declaration (#204).

SYMMETRIC ELIGIBILITY, end to end through the real verifier: two attempts
produce the same correct candidate. One is graded the way a CPP arm with a
real installation receipt is (`verify._grade_and_store`, the receipt path
`agent_trial.run_one_attempt` takes); the other the way a baseline arm that
installs nothing is (`verify.grade_agent_attempt`, the #139 stand-in). Their
stored verified statuses differ - PASS against INCONCLUSIVE - purely because of
`installation-ready`. The primary endpoint must read PASS for both.

The red case: `test_the_stored_verified_status_is_the_trap` asserts the
asymmetry the endpoint exists to step around, so a future change that makes
the stored status symmetric shows up here too.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from skillc import calibration, verify
from skillc import trial as t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FAKE = HERE / "fixtures" / "trial-subject" / "fake_subject.py"
TASK = ROOT / "evals" / "level1" / "slug-small-fix"
REFERENCE = TASK / "reference" / "src" / "slugify.py"
WRONG = TASK / "wrong" / "no-collapse" / "src" / "slugify.py"
GRADER = verify.GraderDef.load(TASK)
RECEIPT = json.loads((ROOT / "controls" / "installation-receipt" / "good" / "receipt.json")
                     .read_text(encoding="utf-8"))
CONFIRMED = {"status": "observed", "prompt_delivered": True, "canary_satisfied": True, "grading_eligible": True}
MANIFEST = ROOT / "evals" / "calibration-204" / "run-manifest.json"


@pytest.fixture(autouse=True)
def _no_quarantine_leaks() -> object:
    verify.clear_quarantine()
    yield
    verify.clear_quarantine()


def _captured(tmp_path: Path, name: str, source: Path, *, receipt: bool) -> tuple[t.Experiment, str]:
    store = t.open_store(tmp_path / f"store-{name}", forbidden=[])
    experiment = t.plan({"experiment": f"calibration-{name}", "trials": [{
        "label": "slug", "case": {"id": "slug-small-fix", "revision": "1"},
        "grader": GRADER.identity(), "subject": {"digest": "sha256:5a"},
        "client": {"name": "fake", "version": "1"}, "image": {"digest": "sha256:1a"},
        "config": {"model": "fake-1"}, "attempts": 1,
    }]}, store)
    [(_trial, attempt)] = list(experiment.attempts())
    attempt_id = str(attempt["attempt_id"])
    if receipt:
        t.add_receipt(experiment, {**RECEIPT, "attempt_id": attempt_id,
                                   "trial_id": experiment.trial_of(attempt_id)["trial_id"],
                                   "client": {"name": "fake", "version": "1"}})
    base = tmp_path / f"work-{name}"
    base.mkdir()
    workspace = t.allocate_workspace(experiment, attempt_id, base, forbidden=[])
    stop = t.run_attempt(experiment, attempt_id, [sys.executable, str(FAKE), "slug-from", str(source)],
                         cwd=workspace, timeout=20, grace=0.5)
    assert stop["confirmed"] is True
    t.capture(experiment, attempt_id, workspace)
    t.cleanup_workspace(experiment, attempt_id)
    assert t.finalize(experiment, attempt_id)["disposition"] == "captured"
    return experiment, attempt_id


def _attempt(tmp_path: Path, name: str, source: Path, *, arm: str) -> tuple[dict[str, object], dict[str, object]]:
    """(run_one_attempt-shaped record, stored verified result) for one arm."""
    experiment, attempt_id = _captured(tmp_path, name, source, receipt=arm == "treatment")
    grading = tmp_path / f"grade-{name}"
    grading.mkdir()
    if arm == "treatment":
        stored, graded = verify._grade_and_store(experiment, attempt_id, GRADER, grading)
    else:
        stored, graded = verify.grade_agent_attempt(experiment, attempt_id, GRADER, grading, CONFIRMED)
    # The same `graded` shape agent_trial.run_one_attempt builds.
    record: dict[str, object] = {"disposition": "captured", "graded": {
        "status": graded.status, "category": graded.category, "detail": graded.detail,
        "criteria": graded.criteria, "result_id": stored["result_id"], "result_status": stored["status"],
    }}
    return record, stored


def test_a_baseline_attempt_meeting_the_task_criteria_reaches_primary_pass(tmp_path: Path) -> None:
    treatment, treatment_result = _attempt(tmp_path, "t", REFERENCE, arm="treatment")
    baseline, baseline_result = _attempt(tmp_path, "b", REFERENCE, arm="baseline")
    assert calibration.primary_endpoint(baseline)["status"] == "PASS"
    assert calibration.primary_endpoint(treatment)["status"] == "PASS"
    # Readiness is still reported - beside the endpoint, not inside it.
    assert calibration.readiness_beside(baseline_result)["installation_ready"] == "UNKNOWN"
    assert calibration.readiness_beside(baseline_result)["readiness_source"] == verify.AGENT_OBSERVATION_READINESS
    assert calibration.readiness_beside(treatment_result)["installation_ready"] == "SATISFIED"


def test_the_stored_verified_status_is_the_trap(tmp_path: Path) -> None:
    """Red case for the comparison the endpoint replaces: the same correct
    output is PASS for the arm with a receipt and INCONCLUSIVE for the
    baseline. Comparing these statuses manufactures a treatment advantage."""
    treatment, _ = _attempt(tmp_path, "t", REFERENCE, arm="treatment")
    baseline, _ = _attempt(tmp_path, "b", REFERENCE, arm="baseline")
    assert treatment["graded"]["result_status"] == "PASS"  # type: ignore[index]
    assert baseline["graded"]["result_status"] == "INCONCLUSIVE"  # type: ignore[index]


def test_a_baseline_attempt_that_fails_the_task_is_primary_fail(tmp_path: Path) -> None:
    baseline, _ = _attempt(tmp_path, "b", WRONG, arm="baseline")
    assert calibration.primary_endpoint(baseline)["status"] == "FAIL"


def test_a_readiness_criterion_in_the_graded_list_is_excluded_and_named() -> None:
    record = {"graded": {"criteria": [
        {"id": "task", "mandatory": True, "outcome": "SATISFIED"},
        {"id": verify.READINESS_CRITERION, "mandatory": True, "outcome": "UNKNOWN"},
    ]}}
    endpoint = calibration.primary_endpoint(record)
    assert endpoint["status"] == "PASS"
    assert endpoint["excluded"] == [verify.READINESS_CRITERION]


def test_an_ungraded_attempt_is_reported_not_dropped() -> None:
    endpoint = calibration.primary_endpoint({"disposition": "inconclusive", "graded": None,
                                             "grading_blocked_reason": "attempt disposition is 'inconclusive'"})
    assert endpoint["status"] == calibration.NOT_GRADED
    assert "inconclusive" in str(endpoint["reason"])


def test_no_criteria_is_inconclusive_never_pass() -> None:
    assert calibration.primary_endpoint({"graded": {"criteria": []}})["status"] == "INCONCLUSIVE"


def test_readiness_beside_with_no_result_is_unknown() -> None:
    assert calibration.readiness_beside(None)["installation_ready"] == "UNKNOWN"


# ------------------------------------------------------------- declaration


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_the_committed_declaration_validates() -> None:
    declaration = calibration.load_declaration(MANIFEST)
    assert declaration.arms == ("full-cpp", "baseline")
    assert declaration.attempts_per_arm == 4
    assert sorted(declaration.arm_order) == sorted(["full-cpp", "baseline"] * 4)
    assert (ROOT / declaration.task_path / "grader.json").is_file()


def test_the_committed_declaration_is_not_an_authorization() -> None:
    with pytest.raises(calibration.DeclarationRefused, match="not approved"):
        calibration.require_approved(calibration.load_declaration(MANIFEST), ROOT)


def _mutated(**changes: object) -> dict[str, object]:
    data = copy.deepcopy(_manifest())
    data.update(changes)
    return data


def _arms(**treatment_extra: object) -> list[object]:
    arms = copy.deepcopy(_manifest()["arms"])
    assert isinstance(arms, list)
    arms[0].update(treatment_extra)
    return arms


@pytest.mark.parametrize(("change", "match"), [
    ({"arms": _arms() + [{"name": "ablation", "subject": {"name": "x"}}]}, "exactly two arms"),
    ({"arms": _arms(model="another-model")}, "arms may differ only"),
    ({"attempts_per_arm": 6}, "3-5"),
    ({"attempts_per_arm": 2}, "3-5"),
    ({"arm_order": {"seed": 20260930, "sequence": ["full-cpp", "baseline"] * 4}}, "chosen by hand"),
    ({"arm_order": {"seed": 1, "sequence": _manifest()["arm_order"]["sequence"]}},  # type: ignore[index]
     "chosen by hand"),
    ({"retain_transcripts": False}, "retain_transcripts"),
])
def test_a_declaration_that_breaks_the_design_is_refused(change: dict[str, object], match: str) -> None:
    with pytest.raises(calibration.DeclarationRefused, match=match):
        calibration.parse_declaration(_mutated(**change))


def test_a_baseline_that_installs_something_is_refused() -> None:
    arms = copy.deepcopy(_manifest()["arms"])
    assert isinstance(arms, list)
    arms[1]["subject"] = {"name": "cpp-codex"}
    with pytest.raises(calibration.DeclarationRefused, match="installs nothing"):
        calibration.parse_declaration(_mutated(arms=arms))


def test_a_total_cap_that_cannot_cover_the_schedule_is_refused() -> None:
    data = _mutated()
    data["shared"]["total_seconds"] = 1200  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="cannot cover"):
        calibration.parse_declaration(data)


def _approved() -> dict[str, object]:
    data = _mutated(approval={"by": "owner", "at": "2026-10-01"})
    data["shared"]["image"]["digest"] = "sha256:" + "ab" * 32  # type: ignore[index]
    return data


def test_an_approved_declaration_with_every_identity_recorded_is_authorized() -> None:
    calibration.require_approved(calibration.parse_declaration(_approved()), ROOT)


def test_approval_with_an_identity_still_unknown_is_refused() -> None:
    data = _approved()
    data["shared"]["image"]["digest"] = "UNKNOWN"  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match=r"shared\.image\.digest"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


def test_approval_of_another_grader_revision_is_refused() -> None:
    data = _approved()
    data["task"]["grader_revision"] = "2"  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="not the declared"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("cap", ["per_attempt_seconds", "total_seconds"])
def test_a_non_finite_cap_is_refused(cap: str, value: float) -> None:
    """Counter-model review, red before the fix: `json` accepts NaN and
    Infinity, and a NaN total also slipped past the schedule-coverage check."""
    data = _mutated()
    data["shared"][cap] = value  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="finite"):
        calibration.parse_declaration(data)


@pytest.mark.parametrize(("where", "value"), [
    (("shared", "client"), {}),
    (("shared", "image"), {}),
    (("shared", "model"), None),
    (("shared", "reasoning_effort"), ""),
])
def test_approval_with_an_identity_absent_rather_than_unknown_is_refused(
        where: tuple[str, str], value: object) -> None:
    """Counter-model review, red before the fix: only the literal UNKNOWN was
    refused, so an empty object or a null - no identity at all - passed."""
    data = _approved()
    data[where[0]][where[1]] = value  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="not recorded"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


def test_approval_with_an_empty_treatment_subject_is_refused() -> None:
    data = _approved()
    data["arms"][0]["subject"] = {}  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match="treatment.subject"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)
