"""Explicit diagnostic criteria must never substitute for required work."""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

from skillc import calibration, judge, records, verify
from skillc import trial as t


def row(cid: str, mandatory: bool, outcome: str) -> dict[str, object]:
    detail = {"missing": "not observed"} if outcome == "UNKNOWN" else {"evidence": ["observed"]}
    return {"id": cid, "mandatory": mandatory, "outcome": outcome, **detail}


@pytest.mark.parametrize("required", ["SATISFIED", "VIOLATED", "UNKNOWN"])
def test_optional_violation_does_not_enter_public_required_violations(required: str) -> None:
    criteria = [row("required", True, required), row("measured", False, "VIOLATED")]
    status = records.derive_status(records.Record(Path("<criteria>"), {"criteria": criteria}))
    result = verify.Graded(status, "verdict", "", criteria, {})
    assert result.status == {"SATISFIED": "PASS", "VIOLATED": "FAIL", "UNKNOWN": "INCONCLUSIVE"}[required]
    assert result.violated == ({"required"} if required == "VIOLATED" else set())


@pytest.mark.parametrize("required", ["SATISFIED", "VIOLATED", "UNKNOWN"])
def test_existing_mandatory_violations_remain_visible(required: str) -> None:
    criteria = [row("required", True, required)]
    result = verify.Graded("unused", "verdict", "", criteria, {})
    assert result.violated == ({"required"} if required == "VIOLATED" else set())


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROWS = [row("required", True, "SATISFIED"), row("measured", False, "VIOLATED")]


def task(tmp: Path, rows: list[dict[str, object]] | None = None,
         *, changes: dict[str, object] | None = None) -> verify.GraderDef:
    root = tmp / "task"
    root.mkdir()
    definition = {"id": "optional-test", "revision": "1", "criteria": ["required"],
                  "optional_criteria": ["measured"], "probe": {"file": "probe.py", "inputs": "inputs.json",
                  "timeout": 10}, "judge": {"file": "judge.py", "timeout": 10}, **(changes or {})}
    (root / "grader.json").write_text(json.dumps(definition))
    (root / "inputs.json").write_text("{}")
    (root / "probe.py").write_text("print('{}')\n")
    report = {"criteria": DEFAULT_ROWS if rows is None else rows}
    (root / "judge.py").write_text(f"import json\nprint(json.dumps({report!r}))\n")
    return verify.GraderDef.load(root)


def grade(g: verify.GraderDef, tmp: Path) -> verify.Graded:
    candidate = tmp / "candidate"
    candidate.mkdir(exist_ok=True)
    (candidate / "answer.txt").write_text("observed")
    return verify.grade_directory(g, candidate)


@pytest.mark.parametrize("required", ["SATISFIED", "VIOLATED", "UNKNOWN"])
@pytest.mark.parametrize("optional", ["SATISFIED", "VIOLATED", "UNKNOWN", None])
def test_public_grading_retains_diagnostics_without_changing_required_status(
    tmp_path: Path, required: str, optional: str | None,
) -> None:
    rows = [row("required", True, required)]
    if optional is not None:
        rows.append(row("measured", False, optional))
    result = grade(task(tmp_path, rows), tmp_path)
    assert result.category == "verdict"
    assert result.criteria == rows
    assert result.status == {"SATISFIED": "PASS", "VIOLATED": "FAIL", "UNKNOWN": "INCONCLUSIVE"}[required]
    assert result.violated == ({"required"} if required == "VIOLATED" else set())
    assert result.detail == ("all mandatory criteria satisfied" if required == "SATISFIED"
                             else "not satisfied: required")
    record = {"graded": {"criteria": result.criteria}}
    assert calibration.raw_primary_endpoint(record)["status"] == result.status
    selected = calibration.OutcomeEndpoint(("measured",))
    assert calibration.raw_primary_endpoint(record, endpoint=selected)["status"] == "INCONCLUSIVE"
    assert calibration.raw_primary_endpoint(record, endpoint=calibration.OutcomeEndpoint(("required",)))["status"] \
        == result.status


@pytest.mark.parametrize("changes", [
    {"criteria": []}, {"criteria": ["required", "required"]}, {"criteria": [False]},
    {"optional_criteria": None}, {"optional_criteria": True}, {"optional_criteria": "measured"},
    {"optional_criteria": [""]}, {"optional_criteria": [" "]}, {"optional_criteria": [False]},
    {"optional_criteria": [{}]}, {"optional_criteria": ["measured", "measured"]},
    {"optional_criteria": ["required"]}, {"optional_criteria": [verify.READINESS_CRITERION]},
])
def test_invalid_declarations_are_refused(tmp_path: Path, changes: dict[str, object]) -> None:
    with pytest.raises(verify.Refused):
        task(tmp_path, changes=changes)


BAD_REPORTS = [
    [], [row("intruder", True, "SATISFIED")],
    [row("required", False, "SATISFIED"), row("intruder", True, "SATISFIED")],
    [row("required", True, "SATISFIED"), row("intruder", True, "SATISFIED")],
    [row("required", True, "SATISFIED"), row("measured", True, "SATISFIED")],
    [row("required", True, "SATISFIED"), row("measured", False, "SATISFIED"),
     row("measured", False, "SATISFIED")],
]


@pytest.mark.parametrize("rows", BAD_REPORTS)
def test_bad_report_controls_cannot_qualify(tmp_path: Path, rows: list[dict[str, object]]) -> None:
    result = grade(task(tmp_path, rows), tmp_path)
    assert result.status == "INCONCLUSIVE"
    assert result.category == "criteria-set"
    assert len(result.criteria) == 1
    assert result.criteria[0]["id"] == "required"
    assert result.criteria[0]["outcome"] == "UNKNOWN"
    assert result.criteria[0]["mandatory"] is True
    assert result.criteria[0]["missing"]


def test_criteria_controls_detect_a_blinded_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same committed bad population must fail if the gate stops checking."""
    monkeypatch.setattr(verify, "criteria_problem", lambda *args: None)
    for i, rows in enumerate(BAD_REPORTS[1:]):
        where = tmp_path / str(i)
        where.mkdir()
        with pytest.raises(AssertionError):
            test_bad_report_controls_cannot_qualify(where, rows)
    healthy = tmp_path / "healthy"
    healthy.mkdir()
    assert grade(task(healthy), healthy).status == "PASS"


@pytest.mark.parametrize("which", ["required", "measured"])
@pytest.mark.parametrize("flag", [None, 0, 1, "true", "false"])
def test_flags_are_literal_booleans(tmp_path: Path, which: str, flag: object) -> None:
    rows = [dict(r, mandatory=flag) if r["id"] == which else r for r in DEFAULT_ROWS]
    result = grade(task(tmp_path, rows), tmp_path)
    assert result.category == "criteria-set" and result.status == "INCONCLUSIVE"


@pytest.mark.parametrize("change", [{"outcome": "invalid"}, {"evidence": []},
                                    {"evidence": [1]}, {"outcome": "UNKNOWN", "missing": ""}])
def test_optional_rows_still_obey_the_record_contract(tmp_path: Path, change: dict[str, object]) -> None:
    rows = [DEFAULT_ROWS[0], {**DEFAULT_ROWS[1], **change}]
    result = grade(task(tmp_path, rows), tmp_path)
    assert result.category == "contract" and result.status == "INCONCLUSIVE"


def legacy_digest(g: verify.GraderDef, loaded: dict[str, bytes]) -> str:
    """The pre-opt-in pin, to prove absent-field definitions did not migrate."""
    digest = t.sha256_bytes
    return t.sha256_bytes(t.canonical({
        "definition": digest(loaded["definition"]), "files": [g.probe.name, g.inputs.name, g.judge.name],
        "id": g.id, "revision": g.revision, "criteria": list(g.criteria),
        "probe": digest(loaded["probe"]), "inputs": digest(loaded["inputs"]), "judge": digest(loaded["judge"]),
        "probe_timeout": g.probe_timeout, "judge_timeout": g.judge_timeout,
    }))


def test_nonempty_published_legacy_population_keeps_exact_pins() -> None:
    definitions = [p for p in sorted((ROOT / "evals").rglob("grader.json"))
                   if "optional_criteria" not in json.loads(p.read_text())]
    assert len(definitions) >= 20
    for definition in definitions:
        g = verify.GraderDef.load(definition.parent)
        assert g.optional_criteria is None
        assert g.digest() == legacy_digest(g, g.read())
        for outcome in ("SATISFIED", "VIOLATED", "UNKNOWN"):
            criteria = [row(cid, True, outcome) for cid in g.criteria]
            result = verify.Graded("unused", "verdict", "", criteria, {})
            assert result.violated == (set(g.criteria) if outcome == "VIOLATED" else set())


def test_opted_policy_and_judge_are_pinned_and_read_once(tmp_path: Path) -> None:
    g = task(tmp_path)
    loaded = g.read()
    original = g.digest(loaded)
    assert g.digest() == original != legacy_digest(g, loaded)
    assert dataclasses.replace(g, optional_criteria=("other",)).digest(loaded) != original
    other = tmp_path / "other.py"
    other.write_text("print('{}')\n")
    changed_judge = g.with_judge(other)
    assert changed_judge.optional_criteria == g.optional_criteria
    assert changed_judge.digest() != original
    g.judge.write_text("print('{}')\n")
    assert g.digest(loaded) == original
    assert g.digest() != original


def test_empty_opt_in_is_distinct_from_absence_and_allows_no_extra_rows(tmp_path: Path) -> None:
    g = task(tmp_path, changes={"optional_criteria": []})
    assert g.optional_criteria == ()
    assert g.digest() != legacy_digest(g, g.read())
    assert grade(g, tmp_path).category == "criteria-set"


def captured(tmp: Path, g: verify.GraderDef) -> tuple[t.Experiment, str, Path]:
    store = t.open_store(tmp / "store", forbidden=[])
    spec: dict[str, object] = {"experiment": "optional", "trials": [{
        "label": "optional", "case": {"id": "optional", "revision": "1"}, "grader": g.identity(),
        "subject": {"digest": "sha256:5a"}, "client": {"name": "fake", "version": "1"},
        "image": {"digest": "sha256:1a"}, "config": {"model": "fake-1"}, "attempts": 1,
    }]}
    experiment = t.plan(spec, store)
    planned, attempt = next(experiment.attempts())
    aid = str(attempt["attempt_id"])
    receipt = json.loads((ROOT / "controls/installation-receipt/good/receipt.json").read_text())
    t.add_receipt(experiment, {**receipt, "attempt_id": aid, "trial_id": planned["trial_id"],
                             "client": {"name": "fake", "version": "1"}})
    base = tmp / "work"
    base.mkdir()
    workspace = t.allocate_workspace(experiment, aid, base, forbidden=[])
    stopped = t.run_attempt(experiment, aid, [sys.executable, "-c",
                            "from pathlib import Path; Path('answer.txt').write_text('observed')"],
                            cwd=workspace, timeout=10, grace=0.5)
    assert stopped["confirmed"] is True
    t.capture(experiment, aid, workspace)
    t.cleanup_workspace(experiment, aid)
    assert t.finalize(experiment, aid)["disposition"] == "captured"
    return experiment, aid, base


@pytest.mark.parametrize("optional", ["SATISFIED", "VIOLATED", "UNKNOWN", None])
def test_actual_storage_and_fake_judges_keep_diagnostics_beside_scoring(tmp_path: Path, optional: str | None) -> None:
    rows = [row("required", True, "SATISFIED")]
    if optional:
        rows.append(row("measured", False, optional))
    g = task(tmp_path, rows)
    experiment, aid, base = captured(tmp_path, g)
    tiers = {judge.SAME_MODEL_TIER: judge.FakeJudge(), judge.INDEPENDENT_TIER: judge.FakeJudge()}
    result = verify.grade(experiment, aid, g, base, judges=tiers, goal_text="observe the required fact")
    assert result["status"] == "PASS" and result["grader"] == g.identity()
    criteria = result["criteria"]
    assert isinstance(criteria, list)
    assert criteria[:-1] == rows
    stored = json.loads((experiment.root / f"result-{result['result_id']}.json").read_text())
    assert stored == result
    verification = result["verification"]
    assert isinstance(verification, dict)
    verdicts = verification["verdicts"]
    assert isinstance(verdicts, dict)
    assert verdicts[verify.GRADING_TIER]["criteria"] == result["criteria"]
    for tier in tiers:
        assert verdicts[tier]["status"] == "PASS"
        assert [r["id"] for r in verdicts[tier]["criteria"]] == ["required"]
    disagreement = verification["disagreement"]
    assert disagreement["agreement_count"] == 1 and disagreement["disagreement_count"] == 0
    assert calibration.raw_primary_endpoint({"graded": {"criteria": result["criteria"]}})["status"] == "PASS"


def test_post_plan_policy_tamper_refuses_before_writing_result(tmp_path: Path) -> None:
    g = task(tmp_path)
    experiment, aid, base = captured(tmp_path, g)
    with pytest.raises(verify.Refused, match="digest|pin"):
        verify.grade(experiment, aid, dataclasses.replace(g, optional_criteria=("forged",)), base)
    assert not list(experiment.root.glob("result-*.json"))


def test_omitted_policy_keeps_legacy_grade_and_storage_shape(tmp_path: Path) -> None:
    g = task(tmp_path, [row("required", True, "SATISFIED")])
    definition = json.loads((g.root / "grader.json").read_text())
    del definition["optional_criteria"]
    (g.root / "grader.json").write_text(json.dumps(definition))
    g = verify.GraderDef.load(g.root)
    assert g.optional_criteria is None and g.digest() == legacy_digest(g, g.read())
    plain = grade(g, tmp_path)
    assert plain.status == "PASS" and plain.criteria == [row("required", True, "SATISFIED")]
    experiment, aid, base = captured(tmp_path, g)
    result = verify.grade(experiment, aid, g, base)
    assert set(result) == {"version", "kind", "producer", "attempt_id", "trial_id", "result_id", "grader",
                           "graded_digests", "criteria", "status", "verification"}
    criteria = result["criteria"]
    assert isinstance(criteria, list)
    assert [r["id"] for r in criteria] == ["required", verify.READINESS_CRITERION]
