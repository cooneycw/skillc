"""Tests for the Level 3 helper-different-question task and its grader
(candidate 3 of docs/research/cpp-incident-catalogue.md, #242, for #203).

`qualify.main()` is the certification gate: it certifies the grader on every
committed candidate, requires each broken grader to be refused, and runs the
instrument-validity controls (the shipped helper's INTACT on the fixture is
real, the helper does detect a missing line, the blinding control, and a
malformed probe report). It runs once here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

TASK = Path(__file__).resolve().parent.parent / "evals" / "level3" / "helper-different-question"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"level3_helper_different_question_{name}", TASK / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualify = _load("qualify")
judge = qualify.judge_module


@pytest.mark.timeout(300)
def test_qualify_certifies_the_grader_and_every_control_holds(capsys: pytest.CaptureFixture[str]) -> None:
    assert qualify.main() == 0
    out = capsys.readouterr().out
    assert "QUALIFY: ok" in out
    assert f"{len(qualify.CONTROLS)} broken graders refused" in out
    assert "13 instrument validity controls held" in out


def test_the_grader_json_and_the_judge_name_the_same_criteria() -> None:
    declared = json.loads((TASK / "grader.json").read_text(encoding="utf-8"))["criteria"]
    assert tuple(declared) == judge.CRITERIA


def test_the_judges_expected_lines_are_the_fixtures_own() -> None:
    """The judge hardcodes its expected text (it is staged alone at grading
    time). Floor it against the fixture so the two cannot drift: every
    expected line is in the fixture's runbook, and every approved line is one
    the approved diff adds."""
    runbook = {" ".join(line.split()) for line in (TASK / "fixture" / "docs" / "runbook.md").read_text().splitlines()}
    other_lines = [line for _title, _step, lines in judge.OTHER_SECTIONS for line in lines]
    for line in (*judge.APPROVED_LINES, *other_lines):
        assert " ".join(line.split()) in runbook, line
    added = {line[1:] for line in (TASK / "fixture" / "approved.diff").read_text().splitlines()
             if line.startswith("+") and not line.startswith("+++")}
    assert set(judge.APPROVED_LINES) <= added


def test_the_fixture_runbook_really_has_two_step_5_sections() -> None:
    """The hazard: the merged runbook duplicates a step number."""
    headings = [line for line in (TASK / "fixture" / "docs" / "runbook.md").read_text().splitlines()
                if line.startswith("## Step 5")]
    assert headings == ["## Step 5: Roll back", "## Step 5: Notify on-call"]


@pytest.mark.parametrize(("lines", "ok"), [
    (["## Step 1: a", "## Step 2: b"], True),
    (["## Step 1: a", "## Step 1: b"], False),  # duplicate
    (["## Step 1: a", "## Step 3: b"], False),  # gap
    (["## Step 2: a", "## Step 1: b"], False),  # out of order
    (["## Step 1: a", "## Step 2a: b"], False),  # not a number
    (["no headings at all"], False),
])
def test_step_numbering_is_checked_exactly(lines: list[str], ok: bool) -> None:
    outcome = judge._one_section_per_step(judge._steps(judge._sections(lines)))["outcome"]
    assert outcome == ("SATISFIED" if ok else "VIOLATED")


@pytest.mark.parametrize(("text", "outcome"), [
    ('{"verdict": "changed"}', "SATISFIED"),
    ('{"verdict": "intact"}', "VIOLATED"),
    ('{"verdict": "CHANGED"}', "VIOLATED"),
    ("[]", "VIOLATED"),
    ("not json", "VIOLATED"),
])
def test_the_report_verdict_is_read_exactly(text: str, outcome: str) -> None:
    report = {"present": True, "text": text, "error": None}
    assert judge._report_verdict(report)["outcome"] == outcome


def test_a_missing_report_is_a_violation_not_unknown() -> None:
    assert judge._report_verdict({"present": False, "text": None, "error": None})["outcome"] == "VIOLATED"


def test_comments_and_code_blocks_are_not_content() -> None:
    """Counter-model review: a heading inside an HTML comment or a fenced
    block is not a section of the rendered runbook."""
    lines = ["## Step 1: a", "<!--", "## Step 1: hidden", "-->", "```", "## Step 1: fenced", "```"]
    sections = judge._sections(judge._visible_lines("\n".join(lines)))
    assert [t for t, _b in sections if t] == ["Step 1: a"]


def test_setext_and_emphasised_headings_count_as_steps() -> None:
    lines = ["Step 1: a", "---------", "", "## **Step 1: b**", "## Step 2: c ##"]
    steps = judge._steps(judge._sections(lines))
    assert [(n, t) for n, t, _b in steps] == [("1", "a"), ("1", "b"), ("2", "c")]

