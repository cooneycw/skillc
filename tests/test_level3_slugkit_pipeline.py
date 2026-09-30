"""Tests for the Level 3 slugkit-pipeline task and its grader (#204).

`qualify.main()` is the certification gate: it certifies the grader on every
committed candidate, requires each broken grader to be refused, and runs the
pipeline-validity controls (step attribution, the benign control, and the
paths that must be UNKNOWN rather than detection). It runs once here.

The gate lets a grader through, so it carries its own red cases: a judge made
blind to "no verdict line" must fail the crash control, and a reference whose
pipeline has no package step must fail the attribution control. Each shows
the validity gate can report the other verdict.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

TASK = Path(__file__).resolve().parent.parent / "evals" / "level3" / "slugkit-pipeline"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"level3_pipeline_{name}", TASK / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualify = _load("qualify")
judge = qualify.judge_module


def _outcomes(candidate: Path) -> dict[str, str]:
    return {c["id"]: c["outcome"] for c in judge.grade(candidate)["criteria"]}


# The whole qualify gate, run for real, takes ~107s on a lightly loaded host - 11% under
# the 120s default (pyproject.toml). Added by #206 without a budget of its own,
# it timed out on main's own CI under load (120.00s at load average ~14, 107s at
# ~5, identical code). A budget for this one test tolerates load; it does not
# make the test faster, and the global default stays 120s everywhere else.
@pytest.mark.timeout(600)
def test_qualify_certifies_the_grader_and_every_control_holds(capsys: pytest.CaptureFixture[str]) -> None:
    assert qualify.main() == 0
    out = capsys.readouterr().out
    assert "QUALIFY: ok" in out
    assert f"{len(qualify.CONTROLS)} broken graders refused" in out
    assert "14 pipeline-validity controls held" in out


def test_the_grader_json_and_the_judge_name_the_same_criteria() -> None:
    declared = json.loads((TASK / "grader.json").read_text(encoding="utf-8"))["criteria"]
    assert tuple(declared) == judge.CRITERIA
    inputs = judge.inputs()
    assert [m["id"] for m in inputs["mutations"]] == [mid for mid, _ in judge.MUTATION_KINDS]


def test_a_neutered_pipeline_is_green_and_dishonest() -> None:
    outcomes = _outcomes(TASK / "wrong" / "pipeline-neutered")
    assert outcomes["pipeline-green"] == "SATISFIED"
    assert outcomes["pipeline-honest"] == "VIOLATED"


def test_red_a_pipeline_that_rejects_the_wrapper_shape_is_dishonest(tmp_path: Path) -> None:
    """Counter-model review: a pipeline that rejects any redefinition of
    `slugify` (a structural rule) instead of the behaviour catches the
    behaviour defect for the wrong reason. The benign forwarding wrapper has
    the same shape and changes nothing, so rejecting it is VIOLATED."""
    candidate = tmp_path / "shape-rule"
    shutil.copytree(TASK / "reference", candidate, ignore=shutil.ignore_patterns("__pycache__"))
    verify_py = candidate / "ci" / "verify.py"
    source = verify_py.read_text(encoding="utf-8")
    rule = (
        'def step_test() -> int:\n'
        '    import ast\n'
        '    tree = ast.parse((ROOT / "slugkit" / "core.py").read_text(encoding="utf-8"))\n'
        '    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]\n'
        '    if len(names) != len(set(names)):\n'
        '        print("  test: a function is defined twice")\n'
        '        return 1\n'
        '    return _step_test_behaviour()\n\n\n'
        'def _step_test_behaviour() -> int:\n'
    )
    assert source.count("def step_test() -> int:\n") == 1
    verify_py.write_text(source.replace("def step_test() -> int:\n", rule), encoding="utf-8")
    outcomes = _outcomes(candidate)
    assert outcomes["pipeline-green"] == "SATISFIED"
    assert outcomes["pipeline-honest"] == "VIOLATED"


def test_a_red_clean_pipeline_makes_honesty_unknown_not_satisfied() -> None:
    outcomes = _outcomes(TASK / "wrong" / "pipeline-red")
    assert outcomes["pipeline-green"] == "VIOLATED"
    assert outcomes["pipeline-honest"] == "UNKNOWN"


def test_the_pipeline_requirement_and_its_format_are_public_in_goal_md() -> None:
    goal = (TASK / "goal.md").read_text(encoding="utf-8")
    assert "ci/verify.py" in goal
    assert "VERIFY: ok" in goal and "VERIFY: fail" in goal


def test_red_a_judge_that_reads_a_crash_as_rejection_fails_the_validity_gate(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control for `pipeline_validity`: make the judge count a
    pipeline that ended without a verdict line as a rejection, and the
    "crashed with no verdict line" control must stop holding."""
    real = judge.pipeline_verdict

    def blind(p: dict[str, object]) -> str:
        verdict = real(p)
        return "fail" if verdict == "no-verdict-line" else verdict

    monkeypatch.setattr(judge, "pipeline_verdict", blind)
    held = {name: ok for name, ok, _ in qualify.pipeline_validity()}
    assert held["pipeline crashed with no verdict line -> UNKNOWN, never detection"] is False


def test_red_a_reference_pipeline_without_a_package_step_fails_attribution(tmp_path: Path) -> None:
    """Negative control for step attribution: a reference whose pipeline
    cannot catch the packaging defect at step `package` must fail it."""
    root = tmp_path / "task"
    shutil.copytree(TASK, root, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.rmtree(root / "reference")
    shutil.copytree(TASK / "wrong" / "pipeline-test-only", root / "reference")
    held = {name: ok for name, ok, _ in qualify.pipeline_validity(root)}
    assert held["packaging-entry-point: proven and rejected by step 'package'"] is False
    assert held["behaviour-trailing-hyphen: proven and rejected by step 'test'"] is True
