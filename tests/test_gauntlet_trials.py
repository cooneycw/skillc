"""Skill-gauntlet rounds 3 and 4 (#736, PR 1): offline controls through ScriptedRunner.

No model is called anywhere in this file. Each control names an input that
makes the machinery report the OTHER verdict (AGENTS.md, negative control).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from skillc import cli, source_digest
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


# ---------------------------------------------------------------- #737 review (post-receipt, approved)


def test_the_engines_record_beside_the_charter_does_not_change_the_skill_digest(tmp_path: Path) -> None:
    """BUG: `gauntlet run` writes GAUNTLET.json beside CHARTER.md inside a native
    skill, so every engine run made a valid declaration read 'the skill changed'."""
    from skillc import gauntlet

    path = _copy(tmp_path)
    (path.parent / "skill" / gauntlet.RECORD_NAME).write_text('{"engine": "record"}\n', encoding="utf-8")
    assert _decl(path).skill_digest  # accepted


def test_a_real_skill_edit_is_still_refused(tmp_path: Path) -> None:
    path = _copy(tmp_path)
    skill = path.parent / "skill/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nA new rule.\n", encoding="utf-8")
    with pytest.raises(g.DeclarationError, match="the skill changed"):
        _decl(path)


def test_a_charter_edit_still_invalidates_the_declaration(tmp_path: Path) -> None:
    path = _copy(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    (path.parent / "skill/CHARTER.md").write_text("---\ncontract: planner\n---\n", encoding="utf-8")
    data["skill_digest"] = data["skill_digest"]  # unchanged on purpose: the charter is part of the skill
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(g.DeclarationError, match="the skill changed"):
        _decl(path)


def test_variants_and_separation_carry_the_full_passage_digest(tmp_path: Path) -> None:
    """`removes` is cut to 80 characters for display; `remove_sha256` names the
    whole passage, so two passages sharing their first 80 characters differ."""
    import hashlib

    long_a = "A" * 90 + " first ending.\n"
    long_b = "A" * 90 + " second ending.\n"
    path = _copy(tmp_path)
    skill = path.parent / "skill/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\n" + long_a + "\n" + long_b, encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["skill_digest"] = digest_tree((path.parent / "skill").resolve())
    data["variants"] = [{"arm": "va", "file": "SKILL.md", "clause": "x", "remove": long_a},
                        {"arm": "vb", "file": "SKILL.md", "clause": "x", "remove": long_b}]
    path.write_text(json.dumps(data), encoding="utf-8")
    declaration, ledger = _round3_complete(path)
    r4 = json.loads(g.to_json(g.round4(declaration, ledger, _runner(declaration, {}))))
    va, vb = r4["variants"]["va"], r4["variants"]["vb"]
    assert va["removes"][:80] == vb["removes"][:80]
    assert va["remove_sha256"] == "sha256:" + hashlib.sha256(long_a.encode()).hexdigest()
    assert va["remove_sha256"] != vb["remove_sha256"]
    r3 = json.loads(g.to_json(g.round3(declaration, ledger, _runner(declaration, {}))))
    passage = data["damaged"][0]["remove"]
    assert r3["separation"]["damaged-gate"]["remove_sha256"] == "sha256:" + hashlib.sha256(passage.encode()).hexdigest()


def test_the_record_name_matches_the_engines() -> None:
    from skillc import gauntlet

    assert g.ENGINE_RECORD == gauntlet.RECORD_NAME


# ---------------------------------------------------------------- #756: the deferred pass-3 findings


def _a1_identity(path: Path) -> str:
    """The ledger key carries `task_digest` (`attempt_key`), so a new identity
    is exactly "no cached grade for this task is reused"."""
    task = g.read_task((path.parent / "tasks/a1").resolve())
    return task.identity


def _script(path: Path, mode: int) -> None:
    script = path.parent / "tasks/a1/fixture/run.sh"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    script.chmod(mode)


def test_an_execute_bit_change_in_a_fixture_is_a_new_task(tmp_path: Path) -> None:
    """#756 (1): the agent sees whether run.sh is executable."""
    path = _copy(tmp_path)
    _script(path, 0o644)
    before = _a1_identity(path)
    _script(path, 0o755)
    assert _a1_identity(path) != before


def test_an_unchanged_fixture_mode_is_the_same_task_and_reuses_everything(tmp_path: Path) -> None:
    """#756 (1) twin: rewriting the same bytes and mode is not a change."""
    path = _copy(tmp_path)
    _script(path, 0o755)
    before = _a1_identity(path)
    declaration, ledger = _round3_complete(path)
    _script(path, 0o755)
    again = _runner(declaration, {})
    report = g.round3(_decl(path), g.Ledger(ledger.path), again)
    assert _a1_identity(path) == before and again.calls == 0 == report.new


def _linked_fixture(path: Path, target: str) -> None:
    task = path.parent / "tasks/a1"
    for name, text in (("alt1", "one\n"), ("alt2", "two\n")):
        (task / name).mkdir(exist_ok=True)
        (task / name / "data.txt").write_text(text, encoding="utf-8")
    link = task / "fixture/data"
    if link.is_symlink():
        link.unlink()
    link.symlink_to(target, target_is_directory=True)


def test_retargeting_a_fixture_directory_symlink_is_a_new_task(tmp_path: Path) -> None:
    """#756 (1): a directory symlink is part of what the agent sees, and is never followed."""
    path = _copy(tmp_path)
    _linked_fixture(path, "../alt1")
    before = _a1_identity(path)
    _linked_fixture(path, "../alt2")
    assert _a1_identity(path) != before


def test_relinking_a_fixture_symlink_to_the_same_target_is_the_same_task(tmp_path: Path) -> None:
    """#756 (1) twin."""
    path = _copy(tmp_path)
    _linked_fixture(path, "../alt1")
    before = _a1_identity(path)
    _linked_fixture(path, "../alt1")
    assert _a1_identity(path) == before


def test_a_fifo_in_a_fixture_is_recorded_never_opened(tmp_path: Path) -> None:
    """#756 (1): a special file is part of the task as not-a-file (never read, so never a hang)."""
    path = _copy(tmp_path)
    before = _a1_identity(path)
    os.mkfifo(path.parent / "tasks/a1/fixture/pipe")
    assert _a1_identity(path) != before


def _held(declaration: g.Declaration) -> set[str]:
    placed = g.assignments(declaration)
    return {identity for identity, side in placed.items() if side == "held"}


def _rename_a1(path: Path, new: str) -> None:
    (path.parent / "tasks/a1").rename(path.parent / "tasks" / new)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["clauses"][GATE] = [t.replace("tasks/a1", f"tasks/{new}") for t in data["clauses"][GATE]]
    path.write_text(json.dumps(data), encoding="utf-8")


def test_renaming_a_task_directory_keeps_every_assignment(tmp_path: Path) -> None:
    """#756 (2): the split is by content, so a rename never moves a task."""
    path = _copy(tmp_path)
    before = g.assignments(_decl(path))
    _rename_a1(path, "z1")
    assert g.assignments(_decl(path)) == before


def test_the_split_still_moves_with_the_seed(tmp_path: Path) -> None:
    """#756 (2) twin: the comparison above can see a different split."""
    path = _copy(tmp_path)
    base = _held(_decl(path))
    moved = []
    for seed in range(40):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["seed"] = f"other-{seed}"
        path.write_text(json.dumps(data), encoding="utf-8")
        moved.append(_held(_decl(path)) != base)
    assert any(moved)


def _copy_agent_inputs(path: Path, source: str, target: str, *, grader: bool) -> None:
    tasks = path.parent / "tasks"
    shutil.rmtree(tasks / target)
    shutil.copytree(tasks / source, tasks / target)
    if not grader:
        grader_file = tasks / target / "grader.json"
        grader_file.write_text(grader_file.read_text(encoding="utf-8").replace(source, target), encoding="utf-8")


def test_one_task_with_different_graders_in_two_clauses_is_refused_before_any_attempt(tmp_path: Path) -> None:
    """#756 (3): the reviewer's reproduction spent 24 attempts before UNKNOWN."""
    path = _copy(tmp_path)
    _copy_agent_inputs(path, "a1", "b1", grader=False)
    with pytest.raises(g.DeclarationError, match="same task with different graders"):
        _decl(path)


def test_one_task_with_the_same_grader_in_two_clauses_is_accepted(tmp_path: Path) -> None:
    """#756 (3) twin: sharing a task across clauses is allowed; only a conflict is refused."""
    path = _copy(tmp_path)
    _copy_agent_inputs(path, "a1", "b1", grader=True)
    declaration = _decl(path)
    assert {t.identity for t in declaration.clauses[GATE]} & {t.identity for t in declaration.clauses[LANES]}


def _rerun_round3(path: Path, ledger: g.Ledger) -> tuple[g.RoundReport, g.ScriptedRunner]:
    declaration = _decl(path)
    runner = _runner(declaration, _fail_all("damaged-gate", GATE_TASKS))
    return g.round3(declaration, g.Ledger(ledger.path), runner), runner


def _respell_damaged(path: Path, **fields: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["damaged"][0].update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_an_equivalent_passage_path_spelling_reuses_every_attempt(tmp_path: Path) -> None:
    """#756 (4): ./SKILL.md is SKILL.md."""
    path = _copy(tmp_path)
    _declaration, ledger = _round3_complete(path)
    _respell_damaged(path, file="./SKILL.md")
    report, runner = _rerun_round3(path, ledger)
    assert runner.calls == 0 == report.new and report.verdict == g.COMPLETE


def test_a_different_passage_is_still_a_different_arm(tmp_path: Path) -> None:
    """#756 (4) twin: canonical paths never merge two different damaged copies."""
    path = _copy(tmp_path)
    _declaration, ledger = _round3_complete(path)
    _respell_damaged(path, file="./SKILL.md", remove="ALWAYS report every lane the project lists.\n")
    report, runner = _rerun_round3(path, ledger)
    assert report.new == runner.calls > 0


@pytest.mark.parametrize("file", ["./../tasks/a1/goal.md", "sub/../../tasks/a1/goal.md", "out/goal.md"])
def test_a_canonicalised_passage_path_outside_the_skill_is_still_refused(tmp_path: Path, file: str) -> None:
    """#756 (4), gate condition: canonicalising is never an escape (`out` links outside the skill)."""
    path = _copy(tmp_path)
    (path.parent / "skill/out").symlink_to("../tasks/a1", target_is_directory=True)
    _respell_damaged(path, file=file)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["skill_digest"] = digest_tree((path.parent / "skill").resolve())
    path.write_text(json.dumps(data), encoding="utf-8")
    declaration = _decl(path)
    with pytest.raises(g.DeclarationError, match="not a regular file inside the skill"):
        g.round3(declaration, g.Ledger(tmp_path / "l.jsonl"), _runner(declaration, {}))


def test_an_unreadable_or_oversized_file_beside_the_agent_inputs_changes_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#756 review: only goal.md and fixture/ are walked, never the grader's neighbours."""
    path = _copy(tmp_path)
    before = _a1_identity(path)
    monkeypatch.setattr(source_digest, "MAX_FILE_BYTES", 64)
    task = path.parent / "tasks/a1"
    (task / "notes.txt").write_text("x" * 200, encoding="utf-8")
    (task / "private").mkdir()
    (task / "private/secret.txt").write_text("s", encoding="utf-8")
    (task / "private").chmod(0o000)
    try:
        assert _a1_identity(path) == before
    finally:
        (task / "private").chmod(0o755)


def test_an_oversized_file_inside_the_fixture_is_still_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#756 review twin: the agent's own inputs stay under the byte budget."""
    path = _copy(tmp_path)
    monkeypatch.setattr(source_digest, "MAX_FILE_BYTES", 64)
    (path.parent / "tasks/a1/fixture/big.txt").write_text("x" * 200, encoding="utf-8")
    with pytest.raises(g.DeclarationError, match="not read"):
        _a1_identity(path)


def test_a_git_directory_inside_the_fixture_is_part_of_the_task(tmp_path: Path) -> None:
    """#756 review control: only the TASK root's .git is not content; the agent sees fixture/.git."""
    path = _copy(tmp_path)
    before = _a1_identity(path)
    (path.parent / "tasks/a1/fixture/.git").mkdir()
    (path.parent / "tasks/a1/fixture/.git/HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert _a1_identity(path) != before


def test_many_files_beside_the_agent_inputs_never_exhaust_the_entry_budget(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#756 review pass 2: excluded neighbours are not counted."""
    path = _copy(tmp_path)
    before = _a1_identity(path)
    monkeypatch.setattr(source_digest, "MAX_ENTRIES", 3)
    for n in range(5):
        (path.parent / f"tasks/a1/note{n}.txt").write_text("n", encoding="utf-8")
    assert _a1_identity(path) == before


def test_too_many_entries_inside_the_fixture_are_still_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#756 review pass 2 twin."""
    path = _copy(tmp_path)
    monkeypatch.setattr(source_digest, "MAX_ENTRIES", 3)
    for n in range(5):
        (path.parent / f"tasks/a1/fixture/f{n}.txt").write_text("n", encoding="utf-8")
    with pytest.raises(g.DeclarationError, match="not read"):
        _a1_identity(path)
