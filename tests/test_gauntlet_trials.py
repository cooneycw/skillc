"""Skill-gauntlet rounds 3 and 4 (#736, PR 1): offline controls through ScriptedRunner.

No model is called anywhere in this file. Each control names an input that
makes the machinery report the OTHER verdict (AGENTS.md, negative control).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from skillc import cli
from skillc import gauntlet_trials as g
from skillc.source_digest import digest_tree

ROOT = Path(__file__).resolve().parent.parent
CONTROLS = ROOT / "evals/gauntlet-controls"
GATE = "planner.never-edit-before-approval"
LANES = "planner.always-report-lanes"


def _copy(tmp_path: Path, **overrides: object) -> Path:
    root = tmp_path / "c"
    shutil.copytree(CONTROLS, root)
    path = root / "declaration.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _decl(path: Path) -> g.Declaration:
    return g.load(path)


def _runner(declaration: g.Declaration, script: dict[tuple[str, str], list[str]]) -> g.ScriptedRunner:
    return g.ScriptedRunner(script, declaration.client)


def _fail_all(arm: str, tasks: list[str]) -> dict[tuple[str, str], list[str]]:
    return {(arm, t): [g.FAIL] for t in tasks}


GATE_TASKS = ["a1", "a2", "a3"]
LANE_TASKS = ["b1", "b2", "b3"]


def _round3_complete(path: Path) -> tuple[g.Declaration, g.Ledger]:
    declaration = _decl(path)
    ledger = g.Ledger(path.parent / "ledger.jsonl")
    report = g.round3(declaration, ledger, _runner(declaration, _fail_all("damaged-gate", GATE_TASKS)))
    assert report.verdict == g.COMPLETE, report
    return declaration, ledger


# ---------------------------------------------------------------- round 3


def test_round3_completes_when_the_damaged_arm_separates(tmp_path: Path) -> None:
    declaration = _decl(_copy(tmp_path))
    runner = _runner(declaration, _fail_all("damaged-gate", GATE_TASKS))
    report = g.round3(declaration, g.Ledger(tmp_path / "l.jsonl"), runner)
    assert report.verdict == g.COMPLETE
    assert report.separation["damaged-gate"]["verdict"] == "DISCRIMINATING"
    assert report.per_clause[GATE]["damaged-gate"] == {"pass": 0, "evaluable": 6, "error": 0, "missing": 0}
    # 2 arms x (2 + 2 train tasks) x 3 replicates
    assert report.declared == report.new == report.run == runner.calls == 24


def test_round3_is_unknown_when_the_tasks_cannot_tell_damaged_from_intact(tmp_path: Path) -> None:
    """The charter's guard test: a damaged skill that scores like the intact
    one proves the tasks cannot measure the skill."""
    declaration = _decl(_copy(tmp_path))
    report = g.round3(declaration, g.Ledger(tmp_path / "l.jsonl"), _runner(declaration, {}))
    assert report.verdict == g.UNKNOWN and "did not separate" in report.reason
    assert report.separation["damaged-gate"]["verdict"] == "NOT_SHOWN"


def test_a_damaged_arm_must_name_a_passage_that_occurs_once(tmp_path: Path) -> None:
    path = _copy(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["damaged"][0]["remove"] = "approval gate"  # occurs twice in SKILL.md
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(g.DeclarationError, match="occurs 2 times"):
        g.round3(_decl(path), g.Ledger(tmp_path / "l.jsonl"), _runner(_decl(path), {}))


def test_a_declaration_without_a_damaged_arm_is_refused(tmp_path: Path) -> None:
    with pytest.raises(g.DeclarationError, match="damaged arm is required"):
        _decl(_copy(tmp_path, damaged=[]))


def test_a_skill_that_changed_since_declaration_is_refused(tmp_path: Path) -> None:
    path = _copy(tmp_path)
    (path.parent / "skill/SKILL.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(g.DeclarationError, match="the skill changed"):
        _decl(path)


@pytest.mark.parametrize("bad", [{"min_tasks_per_clause": 1}, {"replicates": 0}, {"tolerance": -1}, {"attempt_cap": 0}])
def test_an_unusable_declaration_is_refused(tmp_path: Path, bad: dict[str, object]) -> None:
    with pytest.raises(g.DeclarationError):
        _decl(_copy(tmp_path, **bad))


def test_below_the_minimum_tasks_per_clause_is_unknown(tmp_path: Path) -> None:
    path = _copy(tmp_path, min_tasks_per_clause=4)
    report = g.round3(_decl(path), g.Ledger(tmp_path / "l.jsonl"), _runner(_decl(path), {}))
    assert report.verdict == g.UNKNOWN and "min_tasks_per_clause 4" in report.reason and report.run == 0


def test_the_split_is_deterministic_and_disjoint(tmp_path: Path) -> None:
    declaration = _decl(_copy(tmp_path))
    first = [g.split(declaration, c) for c in declaration.clauses]
    again = _decl(_copy(tmp_path / "again"))
    names = [tuple(tuple(t.path.name for t in part) for part in g.split(again, c)) for c in again.clauses]
    assert names == [tuple(tuple(t.path.name for t in part) for part in pair) for pair in first]
    for train, held in first:
        assert held and train and not set(train) & set(held)


# ---------------------------------------------------------------- the attempt cap (decision 4)


def test_no_cap_is_refused_before_any_attempt(tmp_path: Path) -> None:
    path = _copy(tmp_path, attempt_cap=None)
    runner = _runner(_decl(path), {})
    report = g.round3(_decl(path), g.Ledger(tmp_path / "l.jsonl"), runner)
    assert report.verdict == g.REFUSED and "no attempt_cap" in report.reason and runner.calls == 0


def test_over_the_cap_is_refused_before_any_attempt(tmp_path: Path) -> None:
    path = _copy(tmp_path, attempt_cap=10)
    runner = _runner(_decl(path), {})
    report = g.round3(_decl(path), g.Ledger(tmp_path / "l.jsonl"), runner)
    assert report.verdict == g.REFUSED and "exceed attempt_cap 10" in report.reason and runner.calls == 0


def test_a_partial_run_stops_at_the_cap_and_reads_incomplete(tmp_path: Path) -> None:
    path = _copy(tmp_path, attempt_cap=10, partial=True)
    runner = _runner(_decl(path), _fail_all("damaged-gate", GATE_TASKS))
    report = g.round3(_decl(path), g.Ledger(tmp_path / "l.jsonl"), runner)
    assert report.verdict == g.INCOMPLETE and runner.calls == report.run == 10
    assert "stopped at attempt_cap 10" in report.reason


def test_a_rerun_on_the_same_digest_spends_nothing(tmp_path: Path) -> None:
    path = _copy(tmp_path)
    declaration, ledger = _round3_complete(path)
    again = _runner(declaration, {})
    report = g.round3(declaration, g.Ledger(ledger.path), again)
    assert again.calls == 0 and report.new == 0 and report.reused == 24 and report.verdict == g.COMPLETE


def test_a_changed_grader_reuses_nothing(tmp_path: Path) -> None:
    """Orchestrator gate: the ledger key includes the grader's identity."""
    path = _copy(tmp_path)
    _declaration, ledger = _round3_complete(path)
    for task in path.parent.glob("tasks/*/grader.json"):
        task.write_text(task.read_text(encoding="utf-8").replace("constraint", "functional"), encoding="utf-8")
    declaration = _decl(path)
    runner = _runner(declaration, _fail_all("damaged-gate", GATE_TASKS))
    report = g.round3(declaration, g.Ledger(ledger.path), runner)
    assert report.reused == 0 and report.new == 24 == runner.calls


def test_a_changed_client_version_reuses_nothing(tmp_path: Path) -> None:
    path = _copy(tmp_path)
    _declaration, ledger = _round3_complete(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["client"]["version"] = "scripted-2"
    path.write_text(json.dumps(data), encoding="utf-8")
    report = g.round3(_decl(path), g.Ledger(ledger.path), _runner(_decl(path), _fail_all("damaged-gate", GATE_TASKS)))
    assert report.reused == 0


def test_no_runner_refuses_rather_than_pretending(tmp_path: Path) -> None:
    report = g.round3(_decl(_copy(tmp_path)), g.Ledger(tmp_path / "l.jsonl"), None)
    assert report.verdict == g.REFUSED and "PR 3" in report.reason


# ---------------------------------------------------------------- round 4


def test_round4_finds_the_redundant_passage_removable(tmp_path: Path) -> None:
    declaration, ledger = _round3_complete(_copy(tmp_path))
    script = _fail_all("lean-lanes", LANE_TASKS)
    report = g.round4(declaration, ledger, _runner(declaration, script))
    assert report.verdict == g.COMPLETE and report.recommendation == g.TRIM
    assert report.variants["lean-repeat"]["passes"] is True
    assert report.variants["lean-lanes"]["passes"] is False


def test_round4_keeps_a_lean_skill(tmp_path: Path) -> None:
    declaration, ledger = _round3_complete(_copy(tmp_path))
    script = {**_fail_all("lean-lanes", LANE_TASKS), **_fail_all("lean-repeat", GATE_TASKS)}
    report = g.round4(declaration, ledger, _runner(declaration, script))
    assert report.recommendation == g.KEEP and not any(v["passes"] for v in report.variants.values())


def test_round4_judges_on_the_held_out_tasks_only(tmp_path: Path) -> None:
    """A variant that fails only TRAIN tasks still passes round 4."""
    declaration, ledger = _round3_complete(_copy(tmp_path))
    train_gate = [t.path.name for t in g.split(declaration, GATE)[0]]
    report = g.round4(declaration, ledger, _runner(declaration, _fail_all("lean-repeat", train_gate)))
    assert report.variants["lean-repeat"]["passes"] is True


def test_one_fewer_pass_is_worse_under_the_strict_rule_and_a_declared_tolerance_prints(tmp_path: Path) -> None:
    declaration, ledger = _round3_complete(_copy(tmp_path))
    held_gate = g.split(declaration, GATE)[1][0].path.name
    script = {("lean-repeat", held_gate): [g.FAIL, g.PASS, g.PASS], **_fail_all("lean-lanes", LANE_TASKS)}
    strict = g.round4(declaration, ledger, _runner(declaration, script))
    assert strict.variants["lean-repeat"]["passes"] is False and strict.recommendation == g.KEEP
    path = _copy(tmp_path / "tol", tolerance=1)
    declaration, ledger = _round3_complete(path)
    tolerant = g.round4(declaration, ledger, _runner(declaration, script))
    assert tolerant.variants["lean-repeat"]["passes"] is True
    assert "no-worse tolerance: 1 (declared by the owner)" in g.render(tolerant)


def test_an_errored_attempt_is_never_no_worse(tmp_path: Path) -> None:
    declaration, ledger = _round3_complete(_copy(tmp_path))
    held_gate = g.split(declaration, GATE)[1][0].path.name
    script = {("lean-repeat", held_gate): [g.ERROR], **_fail_all("lean-lanes", LANE_TASKS)}
    report = g.round4(declaration, ledger, _runner(declaration, script))
    assert report.variants["lean-repeat"]["passes"] is False


def test_round4_refuses_until_round3_is_complete(tmp_path: Path) -> None:
    declaration = _decl(_copy(tmp_path))
    runner = _runner(declaration, {})
    report = g.round4(declaration, g.Ledger(tmp_path / "l.jsonl"), runner)
    assert report.verdict == g.REFUSED and "run round 3 first" in report.reason and runner.calls == 0


def test_round4_is_unknown_when_round3_is(tmp_path: Path) -> None:
    path = _copy(tmp_path)
    declaration = _decl(path)
    ledger = g.Ledger(tmp_path / "l.jsonl")
    assert g.round3(declaration, ledger, _runner(declaration, {})).verdict == g.UNKNOWN
    assert g.round4(declaration, ledger, _runner(declaration, {})).verdict == g.UNKNOWN


def test_below_the_minimum_held_out_is_unknown(tmp_path: Path) -> None:
    declaration, ledger = _round3_complete(_copy(tmp_path, min_heldout=3))
    report = g.round4(declaration, ledger, _runner(declaration, {}))
    assert report.verdict == g.UNKNOWN and "min_heldout 3" in report.reason


def test_round4_never_repays_round3(tmp_path: Path) -> None:
    declaration, ledger = _round3_complete(_copy(tmp_path))
    runner = _runner(declaration, _fail_all("lean-lanes", LANE_TASKS))
    report = g.round4(declaration, ledger, runner)
    # intact on held-out (2 tasks x 3) is new; round 3's train attempts are untouched
    assert runner.calls == report.new == 3 * 2 * 3


# ---------------------------------------------------------------- the command


def test_plan_spends_nothing_and_prints_the_count(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _copy(tmp_path)
    assert cli.main(["gauntlet", "round3", str(path), "--plan"]) == 0
    out = capsys.readouterr().out
    assert "declared 24" in out and "new 24" in out and "run 0" in out
    assert not (path.parent / ".gauntlet-ledger.jsonl").exists()


def test_a_real_run_is_refused_in_pr1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _copy(tmp_path)
    assert cli.main(["gauntlet", "round3", str(path)]) == cli.GAUNTLET_EXIT_REFUSED
    assert "PR 3" in capsys.readouterr().out


def test_the_fixture_digest_is_current() -> None:
    data = json.loads((CONTROLS / "declaration.json").read_text(encoding="utf-8"))
    assert data["skill_digest"] == digest_tree((CONTROLS / "skill").resolve())


# ---------------------------------------------------------------- counter-model review, pass 1


def test_byte_identical_task_copies_are_one_task(tmp_path: Path) -> None:
    """HIGH: six copies of one task let a clause meet its minimum with one task."""
    path = _copy(tmp_path)
    tasks = path.parent / "tasks"
    for name in ("a2", "a3"):
        shutil.rmtree(tasks / name)
        shutil.copytree(tasks / "a1", tasks / name)
    declaration = _decl(path)
    assert len(declaration.clauses[GATE]) == 1
    report = g.round3(declaration, g.Ledger(tmp_path / "l.jsonl"), _runner(declaration, {}))
    assert report.verdict == g.UNKNOWN and "fewer distinct tasks" in report.reason and report.run == 0


def test_a_task_shared_by_two_clauses_is_never_train_and_held_out(tmp_path: Path) -> None:
    """HIGH: one global split, so round 4 really is held out."""
    path = _copy(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["clauses"][LANES] = ["tasks/a1", "tasks/a2", "tasks/a3"]
    path.write_text(json.dumps(data), encoding="utf-8")
    declaration = _decl(path)
    train = {t.identity for c in declaration.clauses for t in g.split(declaration, c)[0]}
    held = {t.identity for c in declaration.clauses for t in g.split(declaration, c)[1]}
    assert train and held and not train & held


def test_a_runner_reporting_another_client_is_refused_and_never_cached(tmp_path: Path) -> None:
    declaration = _decl(_copy(tmp_path))
    other = g.ScriptedRunner({}, g.Client("codex", "9", "other-model"))
    ledger = g.Ledger(tmp_path / "l.jsonl")
    report = g.round3(declaration, ledger, other)
    assert report.verdict == g.REFUSED and "not the declared" in report.reason
    assert ledger.rows == {} and not (tmp_path / "l.jsonl").exists()


@pytest.mark.parametrize("line", ['not json', '{"key": "k"}',
                                  json.dumps({k: "x" for k in g.LEDGER_FIELDS} | {"result": "invalid"})])
def test_an_untrustworthy_ledger_row_refuses_the_ledger(tmp_path: Path, line: str) -> None:
    (tmp_path / "l.jsonl").write_text(line + "\n", encoding="utf-8")
    with pytest.raises(g.LedgerError):
        g.Ledger(tmp_path / "l.jsonl")


def test_the_cli_reports_an_untrustworthy_ledger_as_a_usage_error(tmp_path: Path) -> None:
    path = _copy(tmp_path)
    (path.parent / ".gauntlet-ledger.jsonl").write_text("not json\n", encoding="utf-8")
    assert cli.main(["gauntlet", "round3", str(path), "--plan"]) == cli.GAUNTLET_EXIT_USAGE


def test_editing_a_readme_beside_the_grader_keeps_the_cache(tmp_path: Path) -> None:
    """MEDIUM: the grader identity is verify.GraderDef's pin, not every file."""
    path = _copy(tmp_path)
    _declaration, ledger = _round3_complete(path)
    for task in path.parent.glob("tasks/*"):
        (task / "README.md").write_text("notes only\n", encoding="utf-8")
    declaration = _decl(path)
    runner = _runner(declaration, {})
    report = g.round3(declaration, g.Ledger(ledger.path), runner)
    assert report.reused == 24 and runner.calls == 0


def test_round4_can_be_planned_before_round3_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _copy(tmp_path)
    assert cli.main(["gauntlet", "round4", str(path), "--plan"]) == 0
    out = capsys.readouterr().out
    assert "declared 18" in out and "round 3 prerequisite: REFUSED" in out  # 3 arms x 2 held-out x 3


def test_a_partial_run_still_names_the_client_of_what_ran(tmp_path: Path) -> None:
    path = _copy(tmp_path, attempt_cap=10, partial=True)
    report = g.round3(_decl(path), g.Ledger(tmp_path / "l.jsonl"), _runner(_decl(path), {}))
    assert report.verdict == g.INCOMPLETE and report.clients == ["claude scripted scripted"]
    assert "client: claude scripted scripted" in g.render(report)


def test_missing_evidence_is_never_a_verdict(tmp_path: Path) -> None:
    """A clause whose recorded attempts fall short of its population reads UNKNOWN."""
    declaration = _decl(_copy(tmp_path))
    report = g.RoundReport(4, g.COMPLETE, "", 0, 0, 0, 0, None, 0)
    report.per_clause = {GATE: {g.INTACT: {"pass": 0, "evaluable": 0, "error": 0, "missing": 6}}}
    assert g._evidence_problem(report, {GATE: 6}) is not None
    del declaration


# ---------------------------------------------------------------- counter-model review, pass 2


def test_one_agent_visible_task_with_different_graders_is_refused(tmp_path: Path) -> None:
    """HIGH: graders do not make two tasks; what the agent sees does."""
    path = _copy(tmp_path)
    tasks = path.parent / "tasks"
    for name in ("a2", "a3"):
        (tasks / name / "goal.md").write_text((tasks / "a1/goal.md").read_text(encoding="utf-8"), encoding="utf-8")
        (tasks / name / "fixture/README.md").write_text((tasks / "a1/fixture/README.md").read_text(encoding="utf-8"),
                                                        encoding="utf-8")
    with pytest.raises(g.DeclarationError, match="same task with different graders"):
        _decl(path)


def test_errors_in_one_arm_never_fake_a_separation(tmp_path: Path) -> None:
    """HIGH: intact passes a1 and fails a3; damaged errors on a1 and fails a3."""
    path = _copy(tmp_path, replicates=10, attempt_cap=100, discrimination_rule={
        "rule_id": "c", "alpha": 0.05, "tolerance": 4, "citation_url": "https://example.invalid"})
    declaration = _decl(path)
    train = [t.path.name for t in g.split(declaration, GATE)[0]]
    script = {(g.INTACT, train[1]): [g.FAIL], ("damaged-gate", train[0]): [g.ERROR], ("damaged-gate", train[1]): [g.FAIL]}
    report = g.round3(declaration, g.Ledger(tmp_path / "l.jsonl"), _runner(declaration, script))
    assert report.verdict == g.UNKNOWN and report.separation["damaged-gate"]["verdict"] == "UNKNOWN"


@pytest.mark.parametrize("remove", ["goal.md", "fixture"])
def test_a_task_without_its_agent_inputs_is_refused(tmp_path: Path, remove: str) -> None:
    path = _copy(tmp_path)
    target = path.parent / "tasks/a1" / remove
    shutil.rmtree(target) if target.is_dir() else target.unlink()
    with pytest.raises(g.DeclarationError, match="needs a goal.md file and a fixture/ directory"):
        _decl(path)


def test_a_tampered_cached_row_is_never_reused(tmp_path: Path) -> None:
    path = _copy(tmp_path)
    _declaration, ledger = _round3_complete(path)
    rows = [json.loads(line) for line in ledger.path.read_text(encoding="utf-8").splitlines()]
    ledger.path.write_text("".join(json.dumps(r | {"client": "codex", "model": "other"}) + "\n" for r in rows),
                           encoding="utf-8")
    declaration = _decl(path)
    runner = _runner(declaration, {})
    report = g.round3(declaration, g.Ledger(ledger.path), runner)
    assert report.verdict == g.REFUSED and "not trusted" in report.reason and runner.calls == 0


@pytest.mark.parametrize("file", ["../tasks/a1/goal.md", "/etc/hostname", "missing.md"])
def test_a_passage_outside_the_skill_is_refused(tmp_path: Path, file: str) -> None:
    path = _copy(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["damaged"][0]["file"] = file
    path.write_text(json.dumps(data), encoding="utf-8")
    declaration = _decl(path)
    with pytest.raises(g.DeclarationError, match="not a regular file inside the skill"):
        g.round3(declaration, g.Ledger(tmp_path / "l.jsonl"), _runner(declaration, {}))


@pytest.mark.parametrize("value", ["false", 1, "true"])
def test_partial_must_be_a_json_boolean(tmp_path: Path, value: object) -> None:
    with pytest.raises(g.DeclarationError, match="partial must be true or false"):
        _decl(_copy(tmp_path, partial=value))


# ---------------------------------------------------------------- --json (#737 reads it; post-receipt, output-only)


def _scripted_rounds(tmp_path: Path) -> tuple[g.RoundReport, g.RoundReport]:
    declaration, ledger = _round3_complete(_copy(tmp_path))
    r3 = g.round3(declaration, ledger, _runner(declaration, {}))  # cached: same verdict
    r4 = g.round4(declaration, ledger, _runner(declaration, _fail_all("lean-lanes", LANE_TASKS)))
    return r3, r4


def test_json_is_exactly_asdict_of_the_report_for_rounds_3_and_4(tmp_path: Path) -> None:
    import dataclasses

    for report in _scripted_rounds(tmp_path):
        parsed = json.loads(g.to_json(report))
        assert parsed == json.loads(json.dumps(dataclasses.asdict(report)))
        for name in ("round", "verdict", "recommendation", "variants", "per_clause", "separation"):
            assert name in parsed  # the fields #737 reads


def test_round4_json_carries_each_variants_passes_and_worse_on(tmp_path: Path) -> None:
    _r3, r4 = _scripted_rounds(tmp_path)
    variants = json.loads(g.to_json(r4))["variants"]
    assert variants["lean-repeat"]["passes"] is True and variants["lean-repeat"]["worse_on"] == []
    assert variants["lean-lanes"]["passes"] is False and variants["lean-lanes"]["worse_on"]


def test_the_cli_json_flag_prints_the_plan_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _copy(tmp_path)
    assert cli.main(["gauntlet", "round3", str(path), "--plan", "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["verdict"] == g.PLANNED and parsed["declared"] == 24 and parsed["round"] == 3


def test_the_text_output_is_unchanged_by_the_json_flag(tmp_path: Path) -> None:
    """The golden was captured BEFORE --json was added (post-receipt change)."""
    r3, r4 = _scripted_rounds(tmp_path)
    golden = (ROOT / "tests/fixtures/gauntlet/render-golden.txt").read_text(encoding="utf-8")
    # The golden's round 3 ran fresh (24 new attempts); here round 3 is a cached re-run.
    fresh_r3 = golden.split("GAUNTLET ROUND 4")[0]
    assert g.render(r4) == "GAUNTLET ROUND 4" + golden.split("GAUNTLET ROUND 4")[1]
    assert g.render(r3).replace("reused 24, new 0, run 0", "reused 0, new 24, run 24") == fresh_r3
