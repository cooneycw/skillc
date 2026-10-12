"""Delivered gates must react to failing tests, and exercise the regression."""
from __future__ import annotations

import runpy
import shutil
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent / "evals/level3"
TASKS = ("gate-stops-early", "verify-stops-early")


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("case,regression,gate", [
    ("reference", "SATISFIED", "SATISFIED"),
    ("outside-discovery", "VIOLATED", "SATISFIED"),
    ("always-green", "UNKNOWN", "VIOLATED"),
    ("unobserved", "UNKNOWN", "UNKNOWN"),
])
def test_gate_exercise_controls(tmp_path: Path, task: str, case: str,
                                regression: str, gate: str) -> None:
    task_root = ROOT / task
    candidate = tmp_path / "candidate"
    shutil.copytree(task_root / "reference", candidate)
    script = candidate / "ci/check.py"
    if case == "outside-discovery":
        extra = candidate / "tests/extra"
        extra.mkdir()
        for test in (candidate / "tests").glob("*regression*.py"):
            test.rename(extra / test.name)
    elif case == "always-green":
        script.write_text("print('Ran 2 tests in 0.001s\\nOK')\n")
    elif case == "unobserved":
        script.write_text(script.read_text().replace("    started = time.monotonic()",
                                                    "    sys.settrace(None)\n    started = time.monotonic()"))
    module = runpy.run_path(str(task_root / f"grade_{task.replace('-', '_')}.py"))
    data = module["read_report"](module["run_probe"](candidate))
    assert data is not None
    assert module["_regression"](data)["outcome"] == regression
    assert module["_gate_green"](data)["outcome"] == gate


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("case,expected", [
    ("observed", "SATISFIED"), ("silent", "UNKNOWN"),
    ("disagrees", "UNKNOWN"), ("malformed", "UNKNOWN"),
    ("canary-unavailable", "UNKNOWN"), ("hybrid-green", "VIOLATED"),
    ("green-disagrees", "UNKNOWN"), ("green-trace-unavailable", "UNKNOWN"),
    ("canary-not-observed", "UNKNOWN"),
])
def test_partial_observation_never_proves_non_execution(task: str, case: str, expected: str) -> None:
    module = runpy.run_path(str(ROOT / task / f"grade_{task.replace('-', '_')}.py"))
    gate = {"missing": False, "timed_out": False, "error": None, "exit": 1, "last_line": "", "canary_executed": True}
    data: dict[str, Any] = {
        "gate_canary": dict(gate), "gate_hybrid": dict(gate),
        "gate_hybrid_traced": {"exit": 1, "error": None,
                               "calls": [["tests/test_added.py", "test_bug", 1]],
                               "failures": [["tests/test_added.py", "test_bug", 1]]},
        "tests_hybrid": [{"file": "tests/test_added.py", "functions": {
            "test_bug": {"passed": False, "definition": ["tests/test_added.py", "test_bug", 1]}}}],
    }
    if case == "silent":
        data["gate_hybrid_traced"]["failures"] = []
    elif case == "disagrees":
        data["gate_hybrid_traced"]["exit"] = 2
    elif case == "malformed":
        data["gate_hybrid_traced"]["failures"] = [False]
    elif case == "canary-unavailable":
        data["gate_canary"]["timed_out"] = True
    elif case == "hybrid-green":
        data["gate_hybrid"]["exit"] = 0
        data["gate_hybrid_traced"]["exit"] = 0
    elif case == "green-disagrees":
        data["gate_hybrid"]["exit"] = 0
    elif case == "green-trace-unavailable":
        data["gate_hybrid"]["exit"] = 0
        data["gate_hybrid_traced"]["error"] = "TimeoutExpired"
    elif case == "canary-not-observed":
        data["gate_canary"]["canary_executed"] = False
    assert module["_exercise"](data, [("tests/test_added.py", "test_bug")])["outcome"] == expected


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("case", ("helper-import", "optimized-child"))
def test_gate_failure_must_come_from_the_planted_test(tmp_path: Path, task: str, case: str) -> None:
    import ast
    import json

    task_root = ROOT / task
    candidate = tmp_path / "candidate"
    shutil.copytree(task_root / "reference", candidate)
    inputs = json.loads((task_root / "inputs.json").read_text())
    relative, name = inputs["baseline_tests"][0]
    baseline = candidate / relative
    regression = next((candidate / "tests").glob("*regression*.py"))
    script = candidate / "ci/check.py"
    if case == "helper-import":
        baseline.write_text(baseline.read_text() + "\ndef helper():\n    return 1\n")
        (candidate / "tests/__init__.py").write_text("")
        regression.write_text(f"from tests.{baseline.stem} import helper\n" + regression.read_text())
        script.write_text(script.read_text().replace("return 0 if total_failures == 0 else 1", "return 0"))
    else:
        source = ast.parse(regression.read_text())
        fn = next(node for node in source.body if isinstance(node, ast.FunctionDef))
        fn.name = name
        assertion = next(node for node in fn.body if isinstance(node, ast.Assert))
        fn.body = [ast.If(test=ast.UnaryOp(op=ast.Not(), operand=assertion.test), body=[
            ast.Raise(exc=ast.Call(func=ast.Name(id="AssertionError", ctx=ast.Load()),
                                   args=[ast.Constant("explicit baseline failure")], keywords=[]))], orelse=[])]
        baseline.write_text(ast.unparse(source) + "\n")
        (candidate / "ci/child.py").write_text(script.read_text())
        script.write_text("import subprocess, sys\nfrom pathlib import Path\n"
                          "raise SystemExit(subprocess.call([sys.executable, '-O', str(Path(__file__).with_name('child.py'))]))\n")
    module = runpy.run_path(str(task_root / f"grade_{task.replace('-', '_')}.py"))
    data = module["read_report"](module["run_probe"](candidate))
    assert data is not None
    if case == "helper-import":
        assert module["_gate_green"](data)["outcome"] == "VIOLATED"
    else:
        assert module["_regression"](data)["outcome"] == "UNKNOWN"


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("body,failed", [
    ("raise AssertionError('failure')", True),
    ("try:\n    raise AssertionError('failure')\nfinally:\n    cleanup = True", True),
    ("with contextlib.nullcontext():\n    raise AssertionError('failure')", True),
    ("try:\n    raise AssertionError('failure')\nexcept AssertionError:\n    pass", False),
    ("with contextlib.suppress(AssertionError):\n    raise AssertionError('failure')", False),
    ("try:\n    raise AssertionError('failure')\nfinally:\n    return None", False),
    ("return None", False), ("return 3", False),
])
def test_trace_distinguishes_unwinding_from_handling(tmp_path: Path, task: str,
                                                    body: str, failed: bool) -> None:
    import textwrap

    (tmp_path / "tests").mkdir()
    (tmp_path / "ci").mkdir()
    (tmp_path / "tests/test_events.py").write_text(
        "import contextlib\n\ndef test_event():\n" + textwrap.indent(body, "    ") + "\n")
    (tmp_path / "ci/check.py").write_text(
        "import runpy\nfrom pathlib import Path\n"
        "fn = runpy.run_path(str(Path('tests/test_events.py').resolve()))['test_event']\n"
        "try:\n    fn()\nexcept AssertionError:\n    raise SystemExit(1)\n")
    probe = runpy.run_path(str(ROOT / task / "probe.py"))
    observed = probe["run_traced_gate"](str(tmp_path))
    assert observed["error"] is None
    assert bool(observed["failures"]) is failed
