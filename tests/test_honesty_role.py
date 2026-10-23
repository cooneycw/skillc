"""#529 D3 (orchestrator ruling): the live summary keys the honest-report
counts and `flagged_honest_report_violated` on each task's honest-report ROLE.
A fixed `honest-report` lookup read every flow-check-route attempt UNKNOWN,
because that grader names the criterion `report-honest`, so a VIOLATED report
could never be flagged."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from skillc import fixture_live as fl
from skillc import matched_pilot as mp
from skillc import trial, verify

ROOT = Path(__file__).resolve().parent.parent
ROUTE = ROOT / "evals" / "level3" / "flow-check-route-live" / "declaration-draft.json"
ROUTE_ENDPOINT = ("report-honest", "no-commit", "gate-definition-unmodified")


def _helpers() -> Any:
    path = Path(__file__).resolve().parent / "test_fixture_live.py"
    spec = importlib.util.spec_from_file_location("fixture_live_tests_for_honesty_role", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H = _helpers()


def _graded(**outcomes: str) -> dict[str, Any]:
    criteria = {c: "SATISFIED" for c in ROUTE_ENDPOINT}
    criteria.update(outcomes)
    status = "FAIL" if "VIOLATED" in criteria.values() else "PASS"
    return {"status": status, "criteria": [{"id": k, "outcome": v} for k, v in criteria.items()]}


def _route_report(tmp_path: Path, graded: list[dict[str, Any]], data: dict[str, Any] | None = None) -> dict[str, Any]:
    declaration = fl.parse_declaration(data or json.loads(ROUTE.read_text(encoding="utf-8")))
    store = trial.open_store(tmp_path / "store", forbidden=[])
    experiment, schedule = fl.plan_live(declaration, store, root=ROOT, treatment=H._treatment(), image_digest=None)
    outcomes = [mp.AttemptOutcome(s, H._clean_record(graded=g), 10.0) for s, g in zip(schedule, graded, strict=True)]
    return fl.build_report(declaration, experiment, outcomes, fl.Stop(), rehearse=None, approved=True)


def test_red_a_violated_report_honest_on_the_route_task_is_flagged_first(tmp_path: Path) -> None:
    """Red on ab2fa36: the summary read UNKNOWN and the head list stayed empty."""
    report = _route_report(tmp_path, [_graded(**{"report-honest": "VIOLATED"}), _graded()])
    first = report["attempts"][0]
    assert first["endpoint_status"] == "FAIL"
    assert next(iter(report)) == "flagged_honest_report_violated"
    assert report["flagged_honest_report_violated"] == [
        {"attempt_id": first["attempt_id"], "case": "rangekit-green", "endpoint_status": "FAIL"}]
    counts = report["cases"]["rangekit-green"]
    assert counts["honest_report_criterion"] == "report-honest"
    assert counts["honest_report"] == {"SATISFIED": 1, "VIOLATED": 1, "UNKNOWN": 0, "not_graded": 0}
    assert counts["honest_report_violated"] == 1


def test_the_d3_shape_counts_satisfied_not_unknown(tmp_path: Path) -> None:
    counts = _route_report(tmp_path, [_graded(), _graded()])["cases"]["rangekit-green"]
    assert counts["honest_report"] == {"SATISFIED": 2, "VIOLATED": 0, "UNKNOWN": 0, "not_graded": 0}


def test_red_a_renamed_honesty_criterion_refuses_the_summary(tmp_path: Path) -> None:
    """A grader that renamed its honesty criterion must not read UNKNOWN again."""
    renamed = {"status": "PASS", "criteria": [{"id": c, "outcome": "SATISFIED"}
                                              for c in ("honest-claims", "no-commit", "gate-definition-unmodified")]}
    with pytest.raises(fl.LiveRefused, match=r"honesty-shaped criteria \['honest-claims'\]"):
        _route_report(tmp_path, [renamed, renamed])


@pytest.mark.parametrize("task_path", sorted(fl.TASKS))
def test_every_task_maps_its_honest_report_role_against_its_own_grader(task_path: str) -> None:
    criteria = [str(c) for c in verify.GraderDef.load(ROOT / task_path).criteria]
    role = fl.honesty_criterion(task_path, criteria)
    assert role is None or role in criteria


def test_red_an_unmapped_task_or_an_unmapped_honesty_criterion_is_refused() -> None:
    with pytest.raises(fl.LiveRefused, match="no honest-report role"):
        fl.honesty_criterion("evals/level3/not-a-task", ["honest-report"])
    with pytest.raises(fl.LiveRefused, match=r"honesty-shaped criteria \['truthful-summary'\]"):
        fl.honesty_criterion(fl.STEP6_TASK_PATH, ["gate-ran", "truthful-summary"])
    with pytest.raises(fl.LiveRefused, match="do not contain"):
        fl.honesty_criterion(fl.FLOW_CHECK_TASK_PATH, ["honest-report", "no-commit"])
