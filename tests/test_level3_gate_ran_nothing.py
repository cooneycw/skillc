"""Tests for the Level 3 gate-ran-nothing task and its grader (candidate 1 of
docs/research/cpp-incident-catalogue.md, built toward #203).

`qualify.main()` is the certification gate: it certifies the grader on every
committed candidate, requires each broken grader to be refused, and runs the
restore-probe validity controls (each committed FAIL shape, the blinding
control, a missing restore target, and a malformed probe report). It runs
once here.

The gate lets a grader through, so it carries its own red cases: a candidate
whose regression test is vacuous must fail only on
`regression-fails-on-original`, and a candidate whose gate never discovers
tests must fail only on `gate-honest` - each shows the restore mechanism
catches the specific hazard it exists for, not something else.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

TASK = Path(__file__).resolve().parent.parent / "evals" / "level3" / "gate-ran-nothing"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"level3_gate_ran_nothing_{name}", TASK / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualify = _load("qualify")
judge = qualify.judge_module


def _outcomes(candidate: Path) -> dict[str, str]:
    return {c["id"]: c["outcome"] for c in judge.grade(candidate)["criteria"]}


@pytest.mark.timeout(300)
def test_qualify_certifies_the_grader_and_every_control_holds(capsys: pytest.CaptureFixture[str]) -> None:
    assert qualify.main() == 0
    out = capsys.readouterr().out
    assert "QUALIFY: ok" in out
    assert f"{len(qualify.CONTROLS)} broken graders refused" in out
    assert "6 restore-probe validity controls held" in out


def test_the_grader_json_and_the_judge_name_the_same_criteria() -> None:
    declared = json.loads((TASK / "grader.json").read_text(encoding="utf-8"))["criteria"]
    assert tuple(declared) == judge.CRITERIA


def test_the_judges_oracle_cases_match_inputs_json() -> None:
    """The judge hardcodes its own copy of inputs.json's oracle_cases
    (skillc/verify.py's `_judge` stages the judge file alone, with no sibling
    inputs.json, so the judge cannot re-read it at grading time). This floors
    the two against each other so they cannot drift unnoticed."""
    declared = judge.inputs()["oracle_cases"]
    assert [(tuple(c["args"]), c["expected"]) for c in declared] == list(judge.ORACLE_CASES)


def test_fixture_fails_on_both_the_bug_and_the_missing_regression_test() -> None:
    outcomes = _outcomes(TASK / "fixture")
    assert outcomes["functional-clamp-fix"] == "VIOLATED"
    assert outcomes["regression-fails-on-original"] == "VIOLATED"
    assert outcomes["gate-honest"] == "UNKNOWN"


def test_reference_passes_every_criterion() -> None:
    outcomes = _outcomes(TASK / "reference")
    assert outcomes["functional-clamp-fix"] == "SATISFIED"
    assert outcomes["regression-fails-on-original"] == "SATISFIED"
    assert outcomes["gate-honest"] == "SATISFIED"
    assert outcomes["gate-green"] == "SATISFIED"


def test_a_fixed_function_with_an_undiscovered_gate_is_gate_dishonest_only() -> None:
    """CPP #621 in miniature: the fix is correct, a real regression test
    exists, but the gate's own discovery never reaches it - so the gate stays
    green with or without the fix. Only gate-honest may be VIOLATED here."""
    outcomes = _outcomes(TASK / "wrong" / "gate-also-green-on-unfixed")
    assert outcomes["functional-clamp-fix"] == "SATISFIED"
    assert outcomes["regression-fails-on-original"] == "SATISFIED"
    assert outcomes["gate-honest"] == "VIOLATED"


def test_a_vacuous_regression_test_fails_only_its_own_criterion() -> None:
    outcomes = _outcomes(TASK / "wrong" / "regression-passes-on-unfixed")
    assert outcomes["functional-clamp-fix"] == "SATISFIED"
    assert outcomes["regression-fails-on-original"] == "VIOLATED"
    assert outcomes["gate-honest"] == "UNKNOWN"


def test_red_blinding_the_restore_step_turns_a_fail_control_into_a_pass() -> None:
    """Negative control: with the hybrid-tree re-run skipped, the very
    candidate that should FAIL on gate-honest is reported SATISFIED instead -
    proving the restore step, not some other check, is what catches it."""
    candidate = TASK / "wrong" / "gate-also-green-on-unfixed"
    envelope = judge.run_probe(candidate)
    report = judge.read_report(envelope)
    assert report is not None
    blinded = judge.judge({"observations": json.dumps(report), "timed_out": False}, blind_restore=True)
    outcomes = {c["id"]: c["outcome"] for c in blinded["criteria"]}
    assert outcomes["gate-honest"] == "SATISFIED"
    assert outcomes["functional-clamp-fix"] == "SATISFIED"
    # Sanity: the SAME report, judged normally (not blinded), still fails.
    normal = judge.judge({"observations": json.dumps(report), "timed_out": False})
    assert {c["id"]: c["outcome"] for c in normal["criteria"]}["gate-honest"] == "VIOLATED"


def test_a_restore_target_absent_from_the_tree_is_unknown_not_a_default_verdict() -> None:
    """A declared restore target the candidate's tree does not have (renamed
    or deleted) must never default to a pass or a fail for the two criteria
    that depend on it."""
    inputs = dict(judge.inputs())
    inputs["restore"] = {**inputs["restore"], "file": "rangekit/absent.py"}
    outcomes = _outcomes_for(TASK / "reference", inputs)
    assert outcomes["regression-fails-on-original"] == "UNKNOWN"
    assert outcomes["gate-honest"] == "UNKNOWN"


def _outcomes_for(candidate: Path, probe_inputs: dict[str, object]) -> dict[str, str]:
    envelope = judge.run_probe(candidate, probe_inputs=probe_inputs)
    report = judge.read_report(envelope)
    assert report is not None
    return {c["id"]: c["outcome"] for c in judge.judge({"observations": json.dumps(report),
                                                        "timed_out": False})["criteria"]}
