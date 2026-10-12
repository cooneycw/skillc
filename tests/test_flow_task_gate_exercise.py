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
    ("unobserved", "UNKNOWN", "SATISFIED"),
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
                                                    "    sys.setprofile(None)\n    started = time.monotonic()"))
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
])
def test_partial_observation_never_proves_non_execution(task: str, case: str, expected: str) -> None:
    module = runpy.run_path(str(ROOT / task / f"grade_{task.replace('-', '_')}.py"))
    gate = {"missing": False, "timed_out": False, "error": None, "exit": 1, "last_line": ""}
    data: dict[str, Any] = {
        "gate_canary": dict(gate), "gate_hybrid": dict(gate),
        "gate_hybrid_traced": {"exit": 1, "error": None,
                               "calls": [["tests/test_added.py", "test_bug", 1]]},
        "tests_hybrid": [{"file": "tests/test_added.py", "functions": {
            "test_bug": {"passed": False, "definition": ["tests/test_added.py", "test_bug", 1]}}}],
    }
    if case == "silent":
        data["gate_hybrid_traced"]["calls"] = []
    elif case == "disagrees":
        data["gate_hybrid_traced"]["exit"] = 2
    elif case == "malformed":
        data["gate_hybrid_traced"]["calls"] = [False]
    elif case == "canary-unavailable":
        data["gate_canary"]["timed_out"] = True
    elif case == "hybrid-green":
        data["gate_hybrid"]["exit"] = 0
    assert module["_exercise"](data, [("tests/test_added.py", "test_bug")])["outcome"] == expected
