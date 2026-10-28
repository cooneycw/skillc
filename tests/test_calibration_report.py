"""Recover calibration reports through the public CLI without launching agents."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from test_calibration_run import _IMAGE_DIGEST, _TEST_PINS, _declaration

from skillc import calibration, cli, trial
from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import matched_pilot as mp

ROOT = Path(__file__).resolve().parent.parent


def _invoke(*args: str) -> int:
    try:
        return cli.main(["calibration-report", *args])
    except SystemExit as exc:
        return int(exc.code or 0)


def _checkpoint(tmp_path: Path, completed: int = 1, *,
                declaration: calibration.CalibrationDeclaration | None = None) -> tuple[Path, Path, trial.Experiment]:
    declaration = declaration or _declaration(attempts=1)
    run = tmp_path / "run"
    run.mkdir()
    experiment, schedule = cr.plan_calibration(
        declaration, trial.open_store(run / "store", forbidden=[]), root=ROOT,
        treatment_digest="sha256:" + "a" * 64, image_digest=_IMAGE_DIGEST, skill_digests=_TEST_PINS,
    )
    outcomes = []
    model, effort = cr.declared_model(declaration)
    for index, scheduled in enumerate(schedule[:completed]):
        base = run / f"work-{index}"
        base.mkdir()
        workspace = trial.allocate_workspace(experiment, scheduled.attempt_id, base, forbidden=[])
        trial.run_attempt(
            experiment, scheduled.attempt_id,
            [sys.executable, "-c", "from pathlib import Path; Path('answer.txt').write_text('fixture')"],
            cwd=workspace, timeout=5, grace=0.1,
        )
        trial.capture(experiment, scheduled.attempt_id, workspace)
        trial.cleanup_workspace(experiment, scheduled.attempt_id)
        record = trial.finalize(experiment, scheduled.attempt_id)
        assert record["disposition"] == "captured"
        # Controlled observation data; the fixture process is not a real model.
        record["observation"] = {"run_metadata": {"model": model, "reasoning_effort": effort}}
        record["graded"] = {"status": "PASS", "criteria": [
            {"id": "fixture", "mandatory": True, "outcome": "SATISFIED"},
        ]}
        outcomes.append(mp.AttemptOutcome(scheduled, record, None))
    cr.write_outcomes(run, experiment, outcomes, declaration)
    original = tmp_path / "original-declaration.json"
    original.write_text(json.dumps(declaration.data))
    return run, original, experiment


@pytest.mark.parametrize("completed", [1, 2], ids=["partial", "complete"])
def test_cli_recovers_every_planned_slot_without_launching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, completed: int,
) -> None:
    run, original, _experiment = _checkpoint(tmp_path, completed)
    checkpoint = (run / cr.OUTCOMES_FILENAME).read_bytes()
    for name in ("acquire_collection", "agent_backends"):
        monkeypatch.setattr(cc, name, lambda *a, **kw: pytest.fail("recovery launched a dependency"))
    for name in ("run_calibration", "run_discrimination"):
        monkeypatch.setattr(cr, name, lambda *a, **kw: pytest.fail("recovery launched a schedule"))
    assert _invoke(str(run), "--declaration", str(original)) == 0
    report = json.loads((run / cr.REPORT_FILENAME).read_text())
    assert report["kind"] == cr.REPORT_KIND
    assert len(report["attempts"]) == 2
    assert [row["disposition"] for row in report["attempts"]] == ["captured"] * completed + ["not-run"] * (2 - completed)
    assert (run / cr.OUTCOMES_FILENAME).read_bytes() == checkpoint


def test_legacy_run_requires_its_original_declaration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    run, _original, _experiment = _checkpoint(tmp_path)
    assert _invoke(str(run)) == 2
    assert "original --declaration" in capsys.readouterr().err
    assert not (run / cr.REPORT_FILENAME).exists()


@pytest.mark.parametrize("field", ["model", "reasoning_effort"])
def test_changed_checkpoint_pins_refuse_without_overwriting_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: str,
) -> None:
    run, original, _experiment = _checkpoint(tmp_path)
    path = run / cr.OUTCOMES_FILENAME
    data = json.loads(path.read_text())
    data["declared"][field] = "different-pin"
    path.write_text(json.dumps(data))
    report = run / cr.REPORT_FILENAME
    report.write_text("previous report")
    assert _invoke(str(run), "--declaration", str(original)) == 2
    assert "recorded model/effort" in capsys.readouterr().err
    assert report.read_text() == "previous report"


def test_no_executed_attempt_is_reported_but_never_a_success(tmp_path: Path) -> None:
    run, original, _experiment = _checkpoint(tmp_path, completed=0)
    assert _invoke(str(run), "--declaration", str(original)) == 1
    report = json.loads((run / cr.REPORT_FILENAME).read_text())
    assert [row["disposition"] for row in report["attempts"]] == ["not-run", "not-run"]


def test_foreign_outcome_schedule_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    run, original, _experiment = _checkpoint(tmp_path)
    path = run / cr.OUTCOMES_FILENAME
    data = json.loads(path.read_text())
    data["outcomes"][0]["arm"] = "foreign"
    path.write_text(json.dumps(data))
    assert _invoke(str(run), "--declaration", str(original)) == 2
    assert "schedule" in capsys.readouterr().err
    assert not (run / cr.REPORT_FILENAME).exists()


def test_malformed_checkpoint_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / cr.OUTCOMES_FILENAME).write_text("{not-json")
    assert _invoke(str(run)) == 2
    assert "cannot report calibration" in capsys.readouterr().err
    assert not (run / cr.REPORT_FILENAME).exists()


def test_bound_discrimination_rehearsal_needs_no_external_declaration(tmp_path: Path) -> None:
    from test_calibration_discrimination_run import _approved, _rehearse

    data = _approved(tmp_path, attempts=1)
    _rehearse(tmp_path, data)
    run = tmp_path / "run"
    assert _invoke(str(run), "--rehearse") == 0
    report = json.loads((run / cr.REPORT_FILENAME).read_text())
    assert report["kind"] == cr.DISCRIMINATION_REPORT_KIND
    assert report["declaration_digest"] == calibration.declaration_digest(data)
    assert report["rehearsal"] is True
    assert report["rehearsal_accounting"]["every_slot_accounted"] is True


@pytest.mark.parametrize("payload", [None, [], 42, "text"])
def test_non_object_declaration_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: object,
) -> None:
    run, original, _experiment = _checkpoint(tmp_path)
    original.write_text(json.dumps(payload))
    assert _invoke(str(run), "--declaration", str(original)) == 2
    assert "declaration must be a JSON object" in capsys.readouterr().err
    assert not (run / cr.REPORT_FILENAME).exists()


def test_legacy_provided_arm_recovers_named_skill_eligibility(tmp_path: Path) -> None:
    from test_calibration_run import _three_arm_declaration

    declaration = _three_arm_declaration()
    run, original, _experiment = _checkpoint(tmp_path, declaration=declaration)
    assert _invoke(str(run), "--declaration", str(original)) == 0
    report = json.loads((run / cr.REPORT_FILENAME).read_text())
    names = cr.named_skills_by_arm(declaration)
    assert names
    assert len(report["attempts"]) == len(declaration.arm_order)
    for row in report["attempts"]:
        assert ("named_skill_opened" in row) is (row["arm"] in names)


@pytest.mark.parametrize("supply_changed", [False, True])
def test_bound_outcome_endpoint_cannot_be_replaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], supply_changed: bool,
) -> None:
    from test_calibration_outcome_endpoint import _data, _outcomes, _planned

    data = _data()
    experiment, schedule = _planned(tmp_path, data)
    run = tmp_path / "run"
    run.mkdir()
    declaration = calibration.parse_declaration(data)
    cr.write_outcomes(run, experiment, _outcomes(schedule), declaration)
    args = [str(run)]
    if supply_changed:
        data["outcome_endpoint"]["criteria"] = data["outcome_endpoint"]["criteria"][:1]
        replacement = tmp_path / "changed.json"
        replacement.write_text(json.dumps(data))
        args += ["--declaration", str(replacement)]
        assert _invoke(*args) == 2
        assert "launch-bound declaration" in capsys.readouterr().err
        assert not (run / cr.REPORT_FILENAME).exists()
    else:
        # These synthetic records have no observed model: reporting succeeds,
        # while the normal no-eligible-comparison verdict remains nonzero.
        assert _invoke(*args) == 1
        report = json.loads((run / cr.REPORT_FILENAME).read_text())
        assert report["outcome_endpoint"] == data["outcome_endpoint"]
        assert report["declaration_digest"] == calibration.declaration_digest(data)
