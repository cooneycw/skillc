"""Content-bound honesty beside-columns, through the existing report APIs (#544)."""
from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from conftest import stamp_approval
from test_calibration_discrimination_run import _approved, _intact
from test_calibration_outcome_endpoint import _data

from skillc import calibration, records, trial, verify
from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import matched_pilot as mp

ROOT = Path(__file__).resolve().parents[1]
TASKS = {
    "slugkit-pipeline": ("evals/level3/slugkit-pipeline", "pipeline-honest"),
    "gate-stops-early-auto6": ("evals/level3/gate-stops-early-auto6", "gate-report-honest"),
    "gate-stops-early": ("evals/level3/gate-stops-early", "flow-check-honest"),
    "gate-stops-early-public-gate": ("evals/level3/gate-stops-early-public-gate", "flow-check-honest"),
    "slug-small-fix": ("evals/level1/slug-small-fix", None),
}


def _plan(tmp: Path, kind: str, task: str = "slugkit-pipeline", *,
          root: Path = ROOT, identity: str | None = None, legacy: bool = False) -> tuple[Any, ...]:
    tmp.mkdir(parents=True, exist_ok=True)
    path, role = TASKS[task]
    grader = verify.GraderDef.load(root / path)
    fixture = "fixture" if task in ("slugkit-pipeline", "slug-small-fix") else "discrimination/fixture"
    data = _approved(tmp, attempts=1) if kind == "discrimination" else _data()
    data["task"] = {"path": path, "fixture": fixture, "grader_id": grader.id, "grader_revision": grader.revision}
    endpoint = {"version": 1, "name": "discrimination-obligation" if kind == "discrimination"
                else "common-task-outcome", "criteria": [grader.criteria[0]]}
    if kind == "discrimination":
        if not legacy:
            data["discrimination_endpoint"] = endpoint
    else:
        data["outcome_endpoint"] = endpoint
        data["task_content"] = cr.task_content_identity(
            (root / path / "goal.md").read_bytes(), grader,
            cc.task_surface(root / path / fixture), cc.project_gate_bytes(root / path))
        data["approval"]["task_fixture"] = fixture
    stamp_approval(data)
    store = trial.open_store(tmp / "store", forbidden=[])
    real_plan = trial.plan

    def adjusted(spec: dict[str, Any], destination: Path) -> trial.Experiment:
        # Valid pre-publication plan variants, not edits to an existing ledger.
        if identity:
            for planned in spec["trials"]:
                planned["grader"] = dict(planned["grader"])
            targets = spec["trials"][1:] if identity == "mixed" else spec["trials"]
            for planned in targets:
                if identity == "missing":
                    planned["grader"].pop("digest")
                else:
                    planned["grader"]["digest"] = "sha256:" + "0" * 64
        return real_plan(spec, destination)

    declaration: calibration.DiscriminationDeclaration | calibration.CalibrationDeclaration
    with patch.object(trial, "plan", adjusted):
        if kind == "discrimination":
            declaration = calibration.parse_discrimination_declaration(data)
            intact = _intact()
            experiment, schedule = cr.plan_discrimination(
                declaration, store, root=root,
                treatments={"intact": intact, "degraded": cr.degraded_treatment(intact, declaration)},
                image_digest=data["shared"]["image"]["digest"])
        else:
            declaration = calibration.parse_declaration(data)
            experiment, schedule = cr.plan_calibration(
                declaration, store, root=root, treatment_digest="sha256:" + "e" * 64,
                image_digest=data["shared"]["image"]["digest"], skill_digests=_intact().skill_digests)
    return experiment, schedule, declaration, grader, role


def _records(grader: verify.GraderDef, role: str | None, honest: str, functional: str) -> list[dict[str, Any]]:
    rows = [{"id": cid, "mandatory": True, "outcome": honest if cid == role else functional,
             "evidence": ["controlled witness"], "missing": "controlled missing witness"}
            for cid in grader.criteria]
    return rows


def _report(plan: tuple[Any, ...], kind: str, rows: object, *, graded: bool = True) -> dict[str, Any]:
    experiment, schedule, declaration, _grader, _role = plan
    status = records.derive_status(records.Record(Path("<controlled-grade>"), {"criteria": rows}))
    record: dict[str, Any] = {"disposition": "captured", "graded": {"status": status, "criteria": rows}}
    if not graded:
        record["graded"] = None
    outcomes = [mp.AttemptOutcome(s, copy.deepcopy(record), None) for s in schedule]
    if kind == "discrimination":
        return cr.build_discrimination_report(experiment, outcomes, declaration)
    return cr.build_report(experiment, outcomes, declared_model="gpt-6-astra", declared_effort="high")


@pytest.mark.parametrize("kind", ["discrimination", "outcome"])
@pytest.mark.parametrize("task", [name for name, (_, role) in TASKS.items() if role is not None])
@pytest.mark.parametrize(("honest", "functional", "primary"), [
    ("VIOLATED", "SATISFIED", "PASS"), ("SATISFIED", "VIOLATED", "FAIL"),
    ("UNKNOWN", "SATISFIED", "PASS"),
])
def test_honesty_is_the_bound_role_not_the_functional_endpoint(
        tmp_path: Path, kind: str, task: str, honest: str, functional: str, primary: str) -> None:
    plan = _plan(tmp_path, kind, task)
    report = _report(plan, kind, _records(plan[3], plan[4], honest, functional))
    for entry in report["attempts"]:
        assert entry["primary_endpoint"]["status"] == primary
        assert entry["process_honesty_beside"]["status"] == honest
        assert [r["id"] for r in entry["process_honesty_beside"]["criteria"]] == [plan[4]]
    assert all(a["process_honesty"] == {honest: 1} for a in report["arms"].values())
    assert f"honesty={honest}" in cr.paste_back(report)


@pytest.mark.parametrize("kind", ["discrimination", "outcome"])
@pytest.mark.parametrize("change", ["duplicate", "conflict", "optional", "invalid", "missing", "renamed", "nonlist", "row"])
def test_ambiguous_or_malformed_honesty_never_passes(tmp_path: Path, kind: str, change: str) -> None:
    plan = _plan(tmp_path, kind, "gate-stops-early")  # existing positive role
    rows: Any = _records(plan[3], plan[4], "SATISFIED", "SATISFIED")
    honest = next(r for r in rows if r["id"] == plan[4])
    if change == "duplicate":
        rows.append(copy.deepcopy(honest))
    elif change == "conflict":
        rows.append({**honest, "id": "pipeline-honest", "outcome": "VIOLATED"})
    elif change == "optional":
        honest["mandatory"] = False
    elif change == "invalid":
        honest["outcome"] = "PASS"
    elif change == "missing":
        rows.remove(honest)
    elif change == "renamed":
        honest["id"] = "renamed-honesty-role"
    elif change == "row":
        rows.append(None)
    else:
        rows = None
    beside = _report(plan, kind, rows)["attempts"][0]["process_honesty_beside"]
    assert beside["status"] == ("MISSING" if change in ("missing", "renamed") else "MALFORMED")
    assert beside["reason"]


@pytest.mark.parametrize("identity", ["missing", "different", "mixed"])
def test_every_attempt_uses_its_own_full_grader_identity(tmp_path: Path, identity: str) -> None:
    plan = _plan(tmp_path, "discrimination", identity=identity)
    report = _report(plan, "discrimination", _records(plan[3], plan[4], "SATISFIED", "SATISFIED"))
    expected = ["SATISFIED", "MISSING"] if identity == "mixed" else ["MISSING", "MISSING"]
    assert [e["process_honesty_beside"]["status"] for e in report["attempts"]] == expected
    assert all("unmapped" in e["process_honesty_beside"]["reason"].lower()
               for e in report["attempts"] if e["process_honesty_beside"]["status"] == "MISSING")


@pytest.mark.parametrize("kind", ["discrimination", "outcome"])
def test_same_id_and_revision_do_not_recognize_changed_grader_bytes(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "root"
    path = TASKS["slugkit-pipeline"][0]
    shutil.copytree(ROOT / path, root / path)
    original = verify.GraderDef.load(root / path)
    original_digest = original.digest()
    judge = original.judge
    judge.write_bytes(judge.read_bytes() + b"\n# different grader bytes, unchanged labels\n")
    plan = _plan(tmp_path / "run", kind, root=root)
    assert (plan[3].id, plan[3].revision) == (original.id, original.revision)
    assert plan[3].digest() != original_digest
    report = _report(plan, kind, _records(plan[3], plan[4], "SATISFIED", "SATISFIED"))
    assert all(e["process_honesty_beside"]["status"] == "MISSING" for e in report["attempts"])


@pytest.mark.parametrize("kind", ["discrimination", "outcome"])
def test_known_no_honesty_is_explicit_not_a_functional_success(tmp_path: Path, kind: str) -> None:
    plan = _plan(tmp_path, kind, "slug-small-fix")
    report = _report(plan, kind, _records(plan[3], None, "SATISFIED", "SATISFIED"))
    beside = report["attempts"][0]["process_honesty_beside"]
    assert beside["status"] == "MISSING" and "no process-honesty role" in beside["reason"]


@pytest.mark.parametrize("kind", ["discrimination", "outcome"])
def test_benign_functional_rows_and_deleted_source_do_not_change_projection(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "root"
    path = TASKS["slugkit-pipeline"][0]
    shutil.copytree(ROOT / path, root / path)
    plan = _plan(tmp_path / "run", kind, root=root)
    store = plan[0].root
    stored = {p.relative_to(store): p.read_bytes() for p in store.rglob("*") if p.is_file()}
    rows = _records(plan[3], plan[4], "SATISFIED", "SATISFIED")
    before = _report(plan, kind, rows)
    rows.append({"id": "truthful-functional-example", "mandatory": True, "outcome": "VIOLATED", "evidence": ["x"]})
    after = _report(plan, kind, rows)
    assert [e["process_honesty_beside"] for e in after["attempts"]] == [e["process_honesty_beside"] for e in before["attempts"]]
    assert after["attempts"][0]["process_honesty_beside"]["status"] == "SATISFIED"
    shutil.rmtree(root)
    assert _report(plan, kind, rows) == after
    assert {p.relative_to(store): p.read_bytes() for p in store.rglob("*") if p.is_file()} == stored


def test_legacy_endpoint_shape_and_ungraded_attempts_are_preserved(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "discrimination", "gate-stops-early", legacy=True)
    assert plan[2].endpoint is None
    rows = _records(plan[3], plan[4], "VIOLATED", "SATISFIED")
    report = _report(plan, "discrimination", rows)
    assert report["version"] == 1 and "discrimination_endpoint" not in report
    assert all(e["process_honesty_beside"]["status"] == "VIOLATED" for e in report["attempts"])
    ungraded = _report(plan, "discrimination", None, graded=False)
    assert all(e["process_honesty_beside"]["status"] == "NOT_GRADED" for e in ungraded["attempts"])


def test_a_changed_caller_declaration_cannot_select_another_role(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "discrimination")
    changed = copy.deepcopy(plan[2])
    changed.data["task"]["grader_id"] = "gate-stops-early"
    with pytest.raises(cr.CalibrationRefused, match="differs from the one this run launched"):
        _report((*plan[:2], changed, *plan[3:]), "discrimination", [])
