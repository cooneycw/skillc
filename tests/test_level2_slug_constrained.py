"""Tests for the Level 2 slug-constrained task and its grader (#13).

Mirrors `tests/test_level1_slug.py`'s own wiring: `qualify.py` is loaded and
driven directly so the grader cannot go blind unnoticed, and each broken
grader control is proven refused for the reason its name gives. A gate that
runs only as a standalone script, invoked by nothing, is an instrument no CI
gate actually exercises - this file is what makes it one.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

TASK = Path(__file__).resolve().parent.parent / "evals" / "level2" / "slug-constrained"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"level2_{name}", TASK / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualify = _load("qualify")
grade_constrained = _load("grade_constrained")


def _outcomes(candidate: Path, timeout: float = 15) -> dict[str, str]:
    result = grade_constrained.grade(candidate, timeout)
    return {c["id"]: c["outcome"] for c in result["criteria"]}


def test_the_grader_is_certified() -> None:
    certified, rows = qualify.certify(TASK / "grade_constrained.py")
    assert certified, [r for r in rows if not r.ok]
    by_name = {r.candidate: r.status for r in rows}
    assert by_name["fixture"] == "FAIL"
    assert by_name["reference"] == "PASS"


@pytest.mark.parametrize("control", sorted(qualify.CONTROLS))
def test_every_broken_grader_is_refused_for_the_reason_its_name_gives(control: str) -> None:
    held, reason, _ = qualify.control_verdict(control)
    assert held, reason


def test_qualify_main_reports_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert qualify.main() == 0
    assert "QUALIFY: ok" in capsys.readouterr().out


def test_a_single_new_constraint_violates_only_its_own_criterion() -> None:
    # extra-required-param is deliberately non-surgical (README.md): a
    # required second argument breaks every 1-arg call, so it cascades into
    # the functional criteria too, not only constraint-interface-stability.
    for name, criteria in [
        ("deferred-import", {"constraint-dependency"}),
        ("notes-touched", {"constraint-data-preservation"}),
    ]:
        outcomes = _outcomes(TASK / "wrong" / name)
        violated = {cid for cid, outcome in outcomes.items() if outcome == "VIOLATED"}
        assert violated == criteria, name


def test_the_deferred_import_is_not_reachable_by_any_functional_held_out_input() -> None:
    # Proves constraint-dependency's static ast scan is not redundant with
    # functional-interface's own dynamic `-S` enforcement: this candidate's
    # functional criteria must all still be SATISFIED, since none of the
    # functional held-out inputs ever execute the branch holding the import.
    outcomes = _outcomes(TASK / "wrong" / "deferred-import")
    assert outcomes["functional-interface"] == "SATISFIED"
    assert outcomes["functional-R1"] == "SATISFIED"
    assert outcomes["functional-R2"] == "SATISFIED"
    assert outcomes["functional-R3"] == "SATISFIED"


def test_notes_touched_still_passes_every_functional_and_other_constraint_criterion() -> None:
    # A whitespace-only NOTES.md edit is the only defect - proves the sha256
    # digest check isn't lenient, without help from any other criterion.
    outcomes = _outcomes(TASK / "wrong" / "notes-touched")
    assert outcomes["constraint-interface-stability"] == "SATISFIED"
    assert outcomes["constraint-dependency"] == "SATISFIED"


def test_constraints_are_stated_publicly_in_goal_md() -> None:
    goal = (TASK / "goal.md").read_text(encoding="utf-8")
    for marker in ("C1", "C2", "C3", "NOTES.md"):
        assert marker in goal


def test_the_grader_definition_declares_the_required_criteria() -> None:
    import json

    definition = json.loads((TASK / "grader.json").read_text(encoding="utf-8"))
    assert tuple(definition["criteria"]) == qualify.REQUIRED_CRITERIA
