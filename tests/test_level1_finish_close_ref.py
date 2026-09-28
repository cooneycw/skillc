"""Tests for the Level 1 finish-close-ref task and its grader (skillc #150).

`test_the_grader_is_certified` and `test_every_broken_grader_is_refused_*` are
the two halves of `qualify.py`, wired into the suite so the grader cannot go
blind unnoticed. `test_a_mutated_reference_turns_the_gate_red` is the
negative control for the gate itself: the same gate, one planted defect, and
it must refuse.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

TASK = Path(__file__).resolve().parent.parent / "evals" / "level1" / "finish-close-ref"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"level1_finish_close_ref_{name}", TASK / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualify = _load("qualify")
grade_ref = _load("grade_ref")


def _outcomes(text: str) -> dict[str, str]:
    envelope = {
        "observations": json.dumps({"files": {"commit_message.txt": {"text": text}}}),
        "timed_out": False,
    }
    result = grade_ref.judge(envelope)
    return {c["id"]: c["outcome"] for c in result["criteria"]}


def _copy_task(tmp_path: Path) -> Path:
    root = tmp_path / "task"
    shutil.copytree(TASK, root, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def test_the_grader_is_certified() -> None:
    certified, rows = qualify.certify(TASK / "grade_ref.py")
    assert certified, [r for r in rows if not r.ok]
    by_name = {r.candidate: r.status for r in rows}
    assert by_name["fixture"] == "FAIL"
    assert by_name["reference"] == "PASS"
    assert len(rows) >= 1 + 1 + 2 + 8


@pytest.mark.parametrize("control", sorted(qualify.CONTROLS))
def test_every_broken_grader_is_refused_for_the_reason_its_name_gives(control: str) -> None:
    held, reason, _ = qualify.control_verdict(control)
    assert held, reason


def test_a_missing_control_does_not_count_as_refused(tmp_path: Path) -> None:
    root = _copy_task(tmp_path)
    (root / "grader-controls" / "always_pass.py").unlink()
    held, reason, _ = qualify.control_verdict("always_pass", root)
    assert not held and "does not exist" in reason


def test_a_control_that_misbehaves_does_not_count_as_refused(tmp_path: Path) -> None:
    root = _copy_task(tmp_path)
    shutil.copy2(root / "grader-controls" / "always_fail.py",
                 root / "grader-controls" / "no_output.py")
    held, reason, _ = qualify.control_verdict("no_output", root)
    assert not held and "not ('INCONCLUSIVE', 'no-output') throughout" in reason


def test_a_mutated_reference_turns_the_gate_red(tmp_path: Path) -> None:
    """The gate's own negative control (ADR 0001/ADR 0008 shape): a planted,
    known-bad edit to a PASS candidate must be caught, not waved through."""
    root = _copy_task(tmp_path)
    reference = root / "reference" / "src" / "commit_message.txt"
    text = reference.read_text(encoding="utf-8")
    reference.write_text(text.rstrip("\n") + "\n\nCloses #42\n", encoding="utf-8")
    certified, rows = qualify.certify(root / "grade_ref.py", root)
    assert not certified
    assert {r.candidate: r.status for r in rows}["reference"] == "FAIL"


def test_an_empty_candidate_population_refuses(tmp_path: Path) -> None:
    root = _copy_task(tmp_path)
    shutil.rmtree(root / "wrong")
    (root / "wrong").mkdir()
    with pytest.raises(SystemExit):
        qualify.certify(root / "grade_ref.py", root)


def test_a_fail_for_the_wrong_reason_does_not_certify(tmp_path: Path) -> None:
    root = _copy_task(tmp_path)
    (root / "wrong" / "no-issue-ref" / "expected.json").write_text(
        '{"status": "FAIL", "violated": ["stays-open"]}', encoding="utf-8")
    certified, rows = qualify.certify(root / "grade_ref.py", root)
    assert not certified
    bad = [r for r in rows if not r.ok]
    assert [(r.candidate, r.status) for r in bad] == [("wrong/no-issue-ref", "FAIL")]


def test_a_single_defect_violates_only_its_own_rule() -> None:
    cases = {
        "reflex-trailer": {"no-closing-match"},
        "negated-close": {"no-closing-match"},
        "not-yet-negation": {"no-closing-match"},
        "colon-form": {"no-closing-match"},
        "no-issue-ref": {"issue-ref"},
        "no-remaining-info": {"stays-open"},
        "summary-no-remaining": {"stays-open"},
    }
    for name, expected in cases.items():
        text = (TASK / "wrong" / name / "src" / "commit_message.txt").read_text(encoding="utf-8")
        outcomes = _outcomes(text)
        violated = {k for k, v in outcomes.items() if v == "VIOLATED"}
        assert violated == expected, name


def test_negation_does_not_save_a_closing_keyword() -> None:
    # This is the discriminating case flow-finish exists to prevent: GitHub's
    # matcher is not grammar-aware, so a careful disclaimer still closes #42.
    for text in (
        "This does not close #42; two items remain open, see TODO.md.",
        "This does not fix #42 yet; two items remain open.",
        "This commit does not yet resolve #42 - two items remain open.",
    ):
        assert _outcomes(text)["no-closing-match"] == "VIOLATED", text


def test_gh_shorthand_is_not_modeled_as_a_closing_form() -> None:
    # Verified against GitHub's own docs (PROVENANCE.md): GH-42 is not
    # documented closing syntax, so referencing it must not violate.
    text = "Refs GH-42; two items remain open, see TODO.md."
    outcomes = _outcomes(text)
    assert outcomes["no-closing-match"] == "SATISFIED"


def test_cross_repo_closing_form_is_not_modeled() -> None:
    # Deliberately out of scope (README.md, "What this task does not grade"):
    # the fixture never declares its own repository, so a judge cannot tell
    # whether an OWNER/REPO#42 reference names this issue or a different one.
    text = "closes some-owner/some-repo#42; two items remain open, see TODO.md."
    outcomes = _outcomes(text)
    assert outcomes["no-closing-match"] == "SATISFIED"
    assert outcomes["issue-ref"] == "VIOLATED"  # not a reference to #42 either


def test_stating_the_issue_is_not_enough_without_remaining_work() -> None:
    text = "Refs #42. Summary report added."
    outcomes = _outcomes(text)
    assert outcomes["issue-ref"] == "SATISFIED"
    assert outcomes["no-closing-match"] == "SATISFIED"
    assert outcomes["stays-open"] == "VIOLATED"


def test_present_participle_is_not_a_closing_keyword() -> None:
    # "closing" is not one of GitHub's nine keyword forms.
    text = "#42 stays open; closing it waits on items 3-4 in TODO.md."
    outcomes = _outcomes(text)
    assert outcomes["no-closing-match"] == "SATISFIED"
    assert outcomes["issue-ref"] == "SATISFIED"
    assert outcomes["stays-open"] == "SATISFIED"


def test_a_missing_artifact_is_a_candidate_violation_with_unknown_downstream() -> None:
    envelope = {
        "observations": json.dumps({"files": {"commit_message.txt": {"read_error": "no such file"}}}),
        "timed_out": False,
    }
    report = grade_ref.judge(envelope)
    outcomes = {c["id"]: c["outcome"] for c in report["criteria"]}
    assert outcomes["artifact-present"] == "VIOLATED"
    assert outcomes["issue-ref"] == outcomes["stays-open"] == outcomes["no-closing-match"] == "UNKNOWN"


def test_an_empty_artifact_is_a_candidate_violation() -> None:
    assert _outcomes("")["artifact-present"] == "VIOLATED"
    assert _outcomes("   \n  ")["artifact-present"] == "VIOLATED"


def test_a_report_missing_a_required_criterion_is_inconclusive() -> None:
    status, detail, _, _ = qualify.status_of(
        TASK / "grader-controls" / "omits_criterion.py", TASK / "reference")
    assert status == "INCONCLUSIVE"
    assert "missing ['issue-ref', 'stays-open']" in detail


def test_qualify_main_reports_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert qualify.main() == 0
    assert "QUALIFY: ok" in capsys.readouterr().out


def test_the_grader_definition_declares_the_required_criteria() -> None:
    definition = json.loads((TASK / "grader.json").read_text(encoding="utf-8"))
    assert tuple(definition["criteria"]) == qualify.REQUIRED_CRITERIA
    assert definition["id"] == grade_ref.GRADER["id"]
    assert definition["revision"] == grade_ref.GRADER["revision"]


def test_the_probe_reads_exactly_the_declared_input_file() -> None:
    inputs = json.loads((TASK / "inputs.json").read_text(encoding="utf-8"))
    assert inputs == ["commit_message.txt"]
    probe = (TASK / "probe.py").read_text(encoding="utf-8")
    assert "src_dir" in probe  # reads from CANDIDATE_DIR/src, matching the fixture layout


def test_the_judge_reads_a_forged_report_as_an_interface_violation() -> None:
    for observations in (
        json.dumps({"criteria": [], "status": "PASS"}),
        json.dumps({"files": {"commit_message.txt": {"text": "ok", "extra": 1}}}),
        json.dumps({"files": {"wrong_name.txt": {"text": "ok"}}}),
        json.dumps({"files": {}}),
        "",
    ):
        report = grade_ref.judge({"observations": observations, "timed_out": False})
        outcomes = {c["id"]: c["outcome"] for c in report["criteria"]}
        assert outcomes["artifact-present"] == "VIOLATED", observations


def test_the_goal_points_at_the_skill_by_name_not_its_content() -> None:
    # Selection concern (PROVENANCE.md, "Selection is held fixed on purpose"):
    # the goal must name the skill, never restate the closing-keyword rule -
    # a restatement would make the case discriminate on reading comprehension,
    # not on whether the agent had the skill's instructions at all.
    goal = (TASK / "goal.md").read_text(encoding="utf-8")
    assert "flow-finish" in goal
    for leaking_word in ("negated", "GitHub", "keyword"):
        assert leaking_word not in goal, leaking_word


def test_reference_and_every_alternative_pass_cleanly() -> None:
    for name in ("reference", "alternatives/part-of", "alternatives/stays-open-phrase"):
        text = (TASK / name / "src" / "commit_message.txt").read_text(encoding="utf-8")
        outcomes = _outcomes(text)
        assert set(outcomes.values()) == {"SATISFIED"}, name
