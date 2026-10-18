"""Approval-bound common outcomes keep raw task/process evidence visible (#287)."""
from __future__ import annotations

import copy
import dataclasses
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from skillc import calibration, trial, verify
from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import matched_pilot as mp

#: #424: the planners refuse a treated arm planned unpinned; a fixed, well-formed pin.
_TEST_PINS = ({"path": ".codex/skills/tdd/SKILL.md", "body_digest": "sha256:" + "b" * 64,
               "description_digest": "sha256:" + "d" * 64},)

ROOT = Path(__file__).resolve().parents[1]
TASK = "evals/level3/gate-stops-early"
SELECTED = ["functional-windows-fix", "regression-fails-on-original", "gate-green"]


def _data() -> dict[str, Any]:
    data = json.loads((ROOT / "evals/calibration-204/run-manifest.json").read_text())
    grader = verify.GraderDef.load(ROOT / TASK)
    data["task"] = {"path": TASK, "fixture": "discrimination/fixture",
                    "grader_id": grader.id, "grader_revision": grader.revision}
    data["shared"]["image"]["digest"] = "sha256:" + "cd" * 32
    data["attempts_per_arm"] = 1
    data["arm_order"]["sequence"] = calibration.derive_arm_order(
        data["arm_order"]["seed"], [a["name"] for a in data["arms"]], 1,
    )
    data["outcome_endpoint"] = {"version": 1, "name": "common-task-outcome", "criteria": SELECTED.copy()}
    files = cc.task_surface(ROOT / TASK / "discrimination/fixture")
    data["task_content"] = {
        "version": 1, "goal_digest": trial.sha256_bytes((ROOT / TASK / "goal.md").read_bytes()),
        "grader_digest": grader.digest(),
        "fixture_digest": trial.sha256_bytes(trial.canonical([
            [path, executable, trial.sha256_bytes(body)] for path, body, executable in files
        ])),
    }
    data["approval"] = {"by": "test-only", "at": "2026-10-12", "attempts_per_arm": 1, "task_fixture": "discrimination/fixture"}
    _approve(data)
    return data


def _approve(data: dict[str, Any]) -> None:
    data["approval"]["declaration_digest"] = trial.sha256_bytes(trial.canonical(
        {key: value for key, value in data.items() if key != "approval"},
    ))


def _planned(tmp_path: Path, data: dict[str, Any] | None = None) -> tuple[trial.Experiment, list[mp.ScheduledAttempt]]:
    declaration = calibration.parse_declaration(data or _data())
    return cr.plan_calibration(
        declaration, trial.open_store(tmp_path / "store", forbidden=[]), root=ROOT,
        treatment_digest="sha256:" + "ab" * 32, image_digest="sha256:" + "cd" * 32,
        skill_digests=_TEST_PINS,
    )


def _outcomes(schedule: list[mp.ScheduledAttempt]) -> list[mp.AttemptOutcome]:
    outcomes = []
    for scheduled in schedule:
        honest = "UNKNOWN" if scheduled.arm == "baseline" else "SATISFIED"
        rows = [{"id": name, "mandatory": True, "outcome": "SATISFIED", "evidence": ["measured"]}
                for name in SELECTED]
        rows.append({"id": "flow-check-honest", "mandatory": True, "outcome": honest,
                     "evidence": ["absent observer" if honest == "UNKNOWN" else "fresh truthful witness"]})
        record: dict[str, object] = {"disposition": "captured", "graded": {
            "status": "INCONCLUSIVE" if honest == "UNKNOWN" else "PASS", "criteria": rows,
        }}
        outcomes.append(mp.AttemptOutcome(scheduled, record, None))
    return outcomes


def _report(experiment: trial.Experiment, outcomes: list[mp.AttemptOutcome]) -> dict[str, Any]:
    return cr.build_report(experiment, outcomes, declared_model="gpt-6-astra", declared_effort="high")


def test_common_outcome_pass_preserves_baseline_unknown(tmp_path: Path) -> None:
    """Before the fix this reaches real build_report and baseline is INCONCLUSIVE."""
    experiment, schedule = _planned(tmp_path)
    outcomes = _outcomes(schedule)
    original = copy.deepcopy([o.record for o in outcomes])
    report = _report(experiment, outcomes)
    baseline = next(row for row in report["attempts"] if row["arm"] == "baseline")
    assert baseline["primary_endpoint"]["status"] == "PASS"
    assert baseline["task_grader_beside"]["status"] == "INCONCLUSIVE"
    assert baseline["process_honesty_beside"]["status"] == "UNKNOWN"
    assert [o.record for o in outcomes] == original
    assert report["version"] == 2


# Every load-bearing refusal below has a committed matching accepted input.


@pytest.mark.parametrize("field,value", [
    ("outcome_endpoint", None), ("task_content", None),
    ("outcome_endpoint.version", True), ("outcome_endpoint.version", 2),
    ("outcome_endpoint.name", "honesty-free"), ("outcome_endpoint.extra", "ignored"),
    ("outcome_endpoint.criteria", []), ("outcome_endpoint.criteria", [SELECTED[0], SELECTED[0]]),
    ("outcome_endpoint.criteria", [None]), ("outcome_endpoint.criteria", ["installation-ready"]),
    ("task_content.version", True), ("task_content.goal_digest", "UNKNOWN"),
    ("task_content.extra", "ignored"), ("lane", "explicit-contract"),
])
def test_closed_opt_in_schema(field: str, value: object) -> None:
    data = _data()
    calibration.parse_declaration(data)
    keys = field.split(".")
    target = data if len(keys) == 1 else data[keys[0]]
    target[keys[-1]] = value
    with pytest.raises(calibration.DeclarationRefused):
        calibration.parse_declaration(data)


@pytest.mark.parametrize("field", ["outcome_endpoint", "task_content"])
def test_pair_is_required_and_discrimination_rejects_it(field: str) -> None:
    data = _data()
    del data[field]
    with pytest.raises(calibration.DeclarationRefused, match="together"):
        calibration.parse_declaration(data)
    data["kind"] = calibration.DISCRIMINATION_KIND
    with pytest.raises(calibration.DeclarationRefused, match="discrimination cannot"):
        calibration.parse_discrimination_declaration(data)


@pytest.mark.parametrize("change", ["criteria", "model", "goal", "caps", "no-digest"])
def test_changed_declaration_refuses_before_backend_or_store(
    tmp_path: Path, change: str,
) -> None:
    data = _data()
    calibration.require_approved(calibration.parse_declaration(data), ROOT)
    if change == "criteria":
        data["outcome_endpoint"]["criteria"].pop()
    elif change == "model":
        data["shared"]["model"] = "another-model"
    elif change == "goal":
        data["task_content"]["goal_digest"] = "sha256:" + "01" * 32
    elif change == "caps":
        data["shared"]["per_attempt_seconds"] += 1
    else:
        del data["approval"]["declaration_digest"]
    _refuses_run(tmp_path, calibration.parse_declaration(data), ROOT, "declaration_digest")


def _refuses_run(tmp_path: Path, declaration: calibration.CalibrationDeclaration, root: Path, match: str) -> None:
    def forbidden() -> tuple[object, object]:
        pytest.fail("refused input requested a backend")
    with pytest.raises((calibration.DeclarationRefused, cr.CalibrationRefused), match=match):
        cr.run_calibration(declaration, run_dir=tmp_path / "run", root=root,
                           treatment=cr.Treatment({}, "sha256:" + "ab" * 32, None, skill_digests=_TEST_PINS),
                           image_digest="sha256:" + "cd" * 32, backends=forbidden, argv_for=lambda _s: [])
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("change", ["goal", "grader", "fixture", "mode"])
def test_changed_input_bytes_or_modes_refuse_before_store(tmp_path: Path, change: str) -> None:
    data = _data()
    copied_root = tmp_path / "repo"
    task = copied_root / TASK
    shutil.copytree(ROOT / TASK, task)
    declaration = calibration.parse_declaration(data)
    assert cr._outcome_task_inputs(declaration, copied_root)
    if change == "goal":
        path = task / "goal.md"
    elif change == "grader":
        path = task / "grade_gate_stops_early.py"
    else:
        path = task / "discrimination/fixture/ISSUE.md"
    if change == "mode":
        path.chmod(path.stat().st_mode ^ 0o100)
    else:
        path.write_bytes(path.read_bytes() + b"\nchanged\n")
    _refuses_run(tmp_path, declaration, copied_root, "task_content")


def test_unknown_selected_id_refuses_even_with_matching_approval(tmp_path: Path) -> None:
    data = _data()
    data["outcome_endpoint"]["criteria"] = ["not-a-grader-criterion"]
    _approve(data)
    _refuses_run(tmp_path, calibration.parse_declaration(data), ROOT, "absent from")


@pytest.mark.parametrize("change,expected", [
    ("VIOLATED", "FAIL"), ("UNKNOWN", "INCONCLUSIVE"),
    ("missing", "INCONCLUSIVE"), ("duplicate", "INCONCLUSIVE"),
    ("malformed", "INCONCLUSIVE"), ("optional", "INCONCLUSIVE"),
    ("not-list", "INCONCLUSIVE"), ("ungraded", "NOT_GRADED"),
])
def test_selected_bad_rows_never_pass(tmp_path: Path, change: str, expected: str) -> None:
    experiment, schedule = _planned(tmp_path)
    outcomes = _outcomes(schedule)
    graded = outcomes[0].record["graded"]
    assert isinstance(graded, dict)
    rows = graded["criteria"]
    if change in {"VIOLATED", "UNKNOWN"}:
        rows[0]["outcome"] = change
    elif change == "missing":
        rows.pop(0)
    elif change == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif change == "malformed":
        rows[0]["outcome"] = "passed"
    elif change == "optional":
        rows[0]["mandatory"] = False
    elif change == "not-list":
        graded["criteria"] = None
    else:
        del outcomes[0].record["graded"]
    assert _report(experiment, outcomes)["attempts"][0]["primary_endpoint"]["status"] == expected


def test_raw_honesty_violation_and_verified_failure_stay_visible(tmp_path: Path) -> None:
    experiment, schedule = _planned(tmp_path)
    outcomes = _outcomes(schedule)
    graded = outcomes[0].record["graded"]
    assert isinstance(graded, dict)
    graded["criteria"][-1]["outcome"] = "VIOLATED"
    graded["status"] = "FAIL"
    graded["result_id"] = "test-result"
    stored = {"status": "FAIL", "criteria": [
        {"id": "installation-ready", "mandatory": True, "outcome": "UNKNOWN"},
    ]}
    (experiment.root / "result-test-result.json").write_text(json.dumps(stored))
    report = _report(experiment, outcomes)
    row = report["attempts"][0]
    assert row["primary_endpoint"]["status"] == "PASS"
    assert row["task_grader_beside"]["status"] == "FAIL"
    assert row["process_honesty_beside"]["status"] == "VIOLATED"
    assert row["readiness_beside"]["verified_status"] == "FAIL"
    assert row["model_eligible"] is False  # no observed model, unchanged eligibility
    assert "task=FAIL honesty=VIOLATED" in cr.paste_back(report)
    assert mp.ineligible_attempts(report)


def test_reconstruction_ignores_changed_or_deleted_source(tmp_path: Path) -> None:
    data = _data()
    source = tmp_path / "declaration.json"
    source.write_text(json.dumps(data))
    experiment, schedule = _planned(tmp_path, data)
    outcomes = _outcomes(schedule)
    before = _report(experiment, outcomes)
    data["outcome_endpoint"]["criteria"].append("flow-check-honest")
    source.write_text(json.dumps(data))
    assert _report(trial.Experiment.open(experiment.root), outcomes) == before
    source.unlink()
    assert _report(trial.Experiment.open(experiment.root), outcomes) == before


def test_changed_bound_object_cannot_fall_back_to_legacy(tmp_path: Path) -> None:
    experiment, schedule = _planned(tmp_path)
    planned, _ = next(experiment.attempts())
    binding = planned["config"]
    assert isinstance(binding, dict)
    path = experiment.object_path(str(binding["digest"]))
    config = json.loads(path.read_bytes())
    del config["calibration_declaration"]
    path.chmod(0o600)
    path.write_bytes(trial.canonical(config))
    with pytest.raises(trial.Refused):
        _report(experiment, _outcomes(schedule))


def test_legacy_endpoint_and_report_shape_stay_unchanged(tmp_path: Path) -> None:
    data = _data()
    del data["outcome_endpoint"], data["task_content"], data["approval"]["declaration_digest"]
    experiment, schedule = _planned(tmp_path, data)
    report = _report(experiment, _outcomes(schedule))
    assert report["version"] == 1
    assert "outcome_endpoint" not in report
    baseline = next(r for r in report["attempts"] if r["arm"] == "baseline")
    assert baseline["primary_endpoint"]["status"] == "INCONCLUSIVE"
    assert "task_grader_beside" not in baseline
    assert "process_honesty" not in report["arms"]["baseline"]


def test_interruption_reconstruction_accounts_for_every_slot(tmp_path: Path) -> None:
    experiment, schedule = _planned(tmp_path)
    outcomes = _outcomes(schedule)[:1]
    cr.write_outcomes(tmp_path, experiment, outcomes, calibration.parse_declaration(_data()))
    restored, checkpoint = mp.read_outcomes(tmp_path)
    report = _report(restored, checkpoint)
    assert len(report["attempts"]) == 2
    assert report["attempts"][1]["primary_endpoint"]["status"] == "NOT_GRADED"
    assert report["attempts"][1]["disposition"] == "not-run"
    for summary in report["arms"].values():
        assert sum(summary["primary"].values()) == summary["scheduled"] == 1
        assert sum(summary["task_grader"].values()) == 1
        assert sum(summary["process_honesty"].values()) == 1


def test_duplicate_or_mislabeled_outcomes_refuse(tmp_path: Path) -> None:
    experiment, schedule = _planned(tmp_path)
    outcomes = _outcomes(schedule)
    with pytest.raises(cr.CalibrationRefused, match="duplicate"):
        _report(experiment, [*outcomes, outcomes[0]])
    altered = dataclasses.replace(outcomes[0], scheduled=dataclasses.replace(schedule[0], arm="other"))
    with pytest.raises(cr.CalibrationRefused, match="schedule"):
        _report(experiment, [altered, outcomes[1]])


def test_no_post_run_model_override(tmp_path: Path) -> None:
    experiment, schedule = _planned(tmp_path)
    with pytest.raises(cr.CalibrationRefused, match="model/effort"):
        cr.build_report(experiment, _outcomes(schedule), declared_model="other", declared_effort="high")


@pytest.mark.parametrize("change", ["partial", "mixed", "malformed", "approval", "grader", "schedule", "boolean-version", "float-cap"])
def test_newly_planned_inconsistent_identity_is_refused(tmp_path: Path, change: str) -> None:
    experiment, schedule = _planned(tmp_path)
    specs = []
    for i, (planned, _) in enumerate(experiment.attempts()):
        binding = planned["config"]
        assert isinstance(binding, dict)
        config = json.loads(experiment.object_path(str(binding["digest"])).read_bytes())
        if i == 0:
            if change == "partial":
                del config["calibration_declaration"]
            elif change == "mixed":
                config["calibration_declaration"]["shared"]["model"] = "different"
            elif change == "malformed":
                config["calibration_declaration"] = None
            elif change == "schedule":
                config["repeat"] = 77
        if i == 1 and change == "boolean-version":
            config["calibration_declaration"]["task_content"]["version"] = True
        if i == 1 and change == "float-cap":
            config["calibration_declaration"]["shared"]["per_attempt_seconds"] = float(
                config["calibration_declaration"]["shared"]["per_attempt_seconds"],
            )
        if change == "approval":
            del config["calibration_declaration"]["approval"]["declaration_digest"]
        spec = {key: planned[key] for key in ("case", "grader", "subject", "client", "image")}
        spec.update({"label": f"calibration_{schedule[i].arm}_1", "config": config, "attempts": 1})
        if change == "grader":
            grader = planned["grader"]
            assert isinstance(grader, dict)
            spec["grader"] = {**grader, "digest": "sha256:" + "ef" * 32}
        specs.append(spec)
    altered = trial.plan({"experiment": "calibration", "trials": specs},
                         trial.open_store(tmp_path / "altered", forbidden=[]))
    with pytest.raises((cr.CalibrationRefused, calibration.DeclarationRefused)):
        _report(altered, [])


def test_empty_population_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    experiment, _ = _planned(tmp_path)
    empty = trial.Experiment(experiment.root, {**experiment.ledger, "trials": []})
    monkeypatch.setattr(trial.Experiment, "open", lambda _root: empty)
    with pytest.raises(cr.CalibrationRefused, match="empty calibration population"):
        _report(empty, [])


def test_runner_dispatches_bound_bytes_and_isolates_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _data()
    copied_root = tmp_path / "repo"
    task = copied_root / TASK
    shutil.copytree(ROOT / TASK, task)
    # Exact CRLF bytes are the prompt too, not merely an on-disk hash.
    goal = (task / "goal.md").read_bytes().replace(b"\n", b"\r\n")
    (task / "goal.md").write_bytes(goal)
    data["task_content"]["goal_digest"] = trial.sha256_bytes(goal)
    _approve(data)
    seen: list[dict[str, Any]] = []

    def attempt(**kwargs: Any) -> dict[str, object]:
        seen.append(kwargs)
        experiment = kwargs["experiment"]
        schedule = cr.schedule_from_ledger(experiment)
        scheduled = next(s for s in schedule if s.attempt_id == kwargs["attempt_id"])
        record = _outcomes([scheduled])[0].record
        record["observation"] = {"run_metadata": {"model": "gpt-6-astra", "reasoning_effort": "high"}}
        return record

    monkeypatch.setattr(cc, "run_level1_agent_attempt", attempt)
    run = tmp_path / "run"
    run.mkdir()
    experiment, outcomes = cr.run_calibration(
        calibration.parse_declaration(data), run_dir=run, root=copied_root,
        treatment=cr.Treatment({"skill": b"body"}, "sha256:" + "ab" * 32, None, skill_digests=_TEST_PINS),
        image_digest="sha256:" + "cd" * 32, backends=lambda: (object(), object()), argv_for=lambda _s: [],
    )
    assert len(seen) == 2
    for call, scheduled in zip(seen, cr.schedule_from_ledger(experiment), strict=True):
        assert call["prompt"].encode() == goal
        assert call["surface"] == cc.surface_mapping(cc.task_surface(task / "discrimination/fixture"))
        assert call["extra_home_files"] == ({} if scheduled.arm == "baseline" else {"skill": b"body"})
        if scheduled.arm == "baseline":
            assert call["receipt_context"] is call["gate_entrypoint"] is call["verify_home_files"] is None
    report = _report(experiment, outcomes)
    assert all(row["primary_endpoint"]["status"] == "PASS" for row in report["attempts"])
    assert all(row["model_eligible"] is True for row in report["attempts"])


@pytest.mark.parametrize("damaged", [False, True])
def test_cli_reports_bound_endpoint_or_controlled_identity_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], damaged: bool,
) -> None:
    from types import SimpleNamespace

    from skillc import cli, demo, trial_bootstrap

    data = _data()
    declaration_path = tmp_path / "declaration.json"
    declaration_path.write_text(json.dumps(data))
    experiment, schedule = _planned(tmp_path)
    outcomes = _outcomes(schedule)
    for outcome in outcomes:
        outcome.record["observation"] = {"run_metadata": {"model": data["shared"]["model"],
                                                          "reasoning_effort": "high"}}
    if damaged:
        planned, _ = next(experiment.attempts())
        binding = planned["config"]
        assert isinstance(binding, dict)
        obj = experiment.object_path(str(binding["digest"]))
        obj.chmod(0o600)
        obj.write_bytes(b"{}")
    subject = next(arm["subject"] for arm in data["arms"] if arm["name"] != "baseline")
    acquired = SimpleNamespace(subject=SimpleNamespace(locator=subject["locator"], revision=subject["revision"],
                                                      client=data["shared"]["client"]["name"]))
    monkeypatch.setattr(trial_bootstrap, "pinned_cli_version", lambda _: data["shared"]["client"]["version"])
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *_: data["shared"]["image"]["digest"])
    monkeypatch.setattr(cc, "acquire_collection", lambda *_: acquired)
    monkeypatch.setattr(cc, "discard_acquisition", lambda *_: None)
    monkeypatch.setattr(cr, "build_treatment", lambda *_a, **_kw: cr.Treatment({}, "sha256:" + "ab" * 32, None, skill_digests=_TEST_PINS))
    monkeypatch.setattr(cr, "run_calibration", lambda *_a, **_kw: (experiment, outcomes))
    private = tmp_path / "private"
    result = cli.main(["calibration-run", str(declaration_path), "--private-dir", str(private)])
    captured = capsys.readouterr()
    assert result == (2 if damaged else 0)
    if damaged:
        assert "skillc:" in captured.err
        assert not list(private.rglob(cr.REPORT_FILENAME))
    else:
        assert "common-task-outcome" in captured.out
        assert "honesty=UNKNOWN" in captured.out


@pytest.mark.parametrize("evidence", [None, [], [""], [True], "not-a-list"])
def test_selected_satisfied_without_evidence_cannot_pass(tmp_path: Path, evidence: object) -> None:
    experiment, schedule = _planned(tmp_path)
    outcomes = _outcomes(schedule)
    graded = outcomes[0].record["graded"]
    assert isinstance(graded, dict)
    row = graded["criteria"][0]
    if evidence is None:
        del row["evidence"]
    else:
        row["evidence"] = evidence
    assert _report(experiment, outcomes)["attempts"][0]["primary_endpoint"]["status"] == "INCONCLUSIVE"


def test_removing_both_opt_in_fields_cannot_reuse_approval(tmp_path: Path) -> None:
    data = _data()
    del data["outcome_endpoint"], data["task_content"]
    # Still refused: since #287 P2 (D-P2a) the whole-declaration binding is
    # what catches it - removing the fields changes the declaration's digest.
    _refuses_run(tmp_path, calibration.parse_declaration(data), ROOT, "does not bind this exact declaration")


@pytest.mark.parametrize("override", ["image", "cap"])
def test_runtime_overrides_refuse_before_store(tmp_path: Path, override: str) -> None:
    data = _data()
    with pytest.raises(cr.CalibrationRefused, match="image|total_seconds"):
        cr.run_calibration(
            calibration.parse_declaration(data), run_dir=tmp_path / "run", root=ROOT,
            treatment=cr.Treatment({}, "sha256:" + "ab" * 32, None, skill_digests=_TEST_PINS),
            image_digest="sha256:" + ("ef" if override == "image" else "cd") * 32,
            total_seconds=1.0 if override == "cap" else None,
            backends=lambda: pytest.fail("unapproved runtime requested backend"), argv_for=lambda _s: [],
        )
    assert not (tmp_path / "run").exists()


def test_no_post_run_named_skill_eligibility(tmp_path: Path) -> None:
    experiment, schedule = _planned(tmp_path)
    with pytest.raises(cr.CalibrationRefused, match="named-skill"):
        cr.build_report(experiment, _outcomes(schedule), declared_model="gpt-6-astra", declared_effort="high",
                        named_skills={"baseline": ["invented"]})


def test_unavailable_attempt_is_retained_and_not_model_ineligible(tmp_path: Path) -> None:
    experiment, schedule = _planned(tmp_path)
    outcomes = _outcomes(schedule)
    outcomes[0] = mp.AttemptOutcome(schedule[0], {"disposition": "unavailable"}, None)
    report = _report(experiment, outcomes)
    row = report["attempts"][0]
    assert row["primary_endpoint"]["status"] == "NOT_GRADED"
    assert row["model_eligible"] == "n/a"
    summary = report["arms"][row["arm"]]
    assert summary["scheduled"] == 1
    assert summary["primary"] == {"NOT_GRADED": 1}
    assert summary["process_honesty"] == {"NOT_GRADED": 1}
