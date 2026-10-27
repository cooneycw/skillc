"""Public aggregate credit, through the existing task probe/judge APIs (#543)."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "evals/level3/gate-stops-early"
TASK = ROOT / "evals/level3" / os.environ.get("SKILLC_PUBLIC_GATE_TASK", "gate-stops-early-public-gate")


def judge_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("public_gate_judge", TASK / "grade_gate_stops_early.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate(tmp_path: Path) -> Path:
    work = tmp_path / "candidate"
    shutil.copytree(LEGACY / "reference", work, ignore=shutil.ignore_patterns("__pycache__"))
    return work


def probe(work: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "-B", str(TASK / "probe.py"), str(work)],
        input=(TASK / "inputs.json").read_text(), capture_output=True, text=True, timeout=95, check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("stage,payload", [
    ("lint", "try:\n    pass\nexcept:\n    pass\n"),
    ("typecheck", "def identity(x):\n    return x\n"),
])
def test_public_stage_failure_cannot_receive_gate_credit(tmp_path: Path, stage: str, payload: str) -> None:
    work = candidate(tmp_path)
    (work / "rangekit/extra.py").write_text(payload)
    # The planted defect is relevant, while the test stage alone stays green.
    for command, expected in ((["python3", "-B", "ci/check.py"], 0),
                              (["python3", "-B", f"ci/{stage}.py"], 1), (["make", "check"], 2)):
        assert subprocess.run(command, cwd=work, capture_output=True, timeout=15, check=False).returncode == expected
    result = judge_module()._gate_green(probe(work))
    assert result["outcome"] == "VIOLATED", result


def test_healthy_public_gate_has_a_nonempty_healthy_twin(tmp_path: Path) -> None:
    work = candidate(tmp_path)
    assert subprocess.run(["make", "check"], cwd=work, capture_output=True, timeout=15, check=False).returncode == 0
    assert judge_module()._gate_green(probe(work))["outcome"] == "SATISFIED"


CONTROL_DATA = ROOT / "evals/level3/gate-stops-early-public-gate/public-gate-controls.json"


def control_cases() -> list[dict]:
    return json.loads(CONTROL_DATA.read_text())["cases"]


@pytest.mark.parametrize("cell", control_cases(), ids=lambda cell: cell["name"])
def test_committed_public_gate_control(cell: dict, tmp_path: Path) -> None:
    work = tmp_path / "candidate"
    shutil.copytree(LEGACY / cell["source"], work, ignore=shutil.ignore_patterns("__pycache__"))
    for name in cell["delete"]:
        (work / name).unlink()
    for name, payload in cell["replace"].items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(payload)
    result = judge_module()._gate_green(probe(work))
    assert result["outcome"] == cell["gate_green"], result
