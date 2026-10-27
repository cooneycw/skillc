"""Public aggregate credit, through the existing task probe/judge APIs (#543)."""
from __future__ import annotations

import hashlib
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
    for name, source in cell.get("copy_source", {}).items():
        shutil.copy2(LEGACY / source, work / name)
    for name in cell["delete"]:
        (work / name).unlink()
    for name, payload in cell["replace"].items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(payload)
    for name, (old, new) in cell.get("replace_once", {}).items():
        path = work / name
        content = path.read_text()
        assert content.count(old) == 1
        path.write_text(content.replace(old, new, 1))
    result = judge_module()._gate_green(probe(work))
    assert result["outcome"] == cell["gate_green"], result


@pytest.mark.parametrize("seed", ["fixture", "discrimination/fixture"])
def test_restore_is_byte_identical_to_the_delivered_original(seed: str) -> None:
    restore = json.loads((TASK / "inputs.json").read_text())["restore"]
    assert restore["content"].encode() == (TASK / seed / restore["file"]).read_bytes()


def test_import_sensitive_test_is_not_an_original_bug_regression(tmp_path: Path) -> None:
    work = candidate(tmp_path)
    (work / "tests/test_windows_regression.py").unlink()
    payload = "from rangekit import windows\n\ndef test_sequence_is_class():\n    assert isinstance(windows.Sequence, type)\n"
    (work / "tests/test_sequence.py").write_text(payload)
    unfixed = tmp_path / "unfixed"
    shutil.copytree(TASK / "fixture", unfixed)
    (unfixed / "tests/test_sequence.py").write_text(payload)
    # This supposed regression actually passes against the delivered unfixed source.
    assert subprocess.run([sys.executable, "-B", "ci/check.py"], cwd=unfixed,
                          capture_output=True, timeout=15, check=False).returncode == 0
    assert judge_module()._regression(probe(work))["outcome"] == "VIOLATED"


def test_genuine_window_regression_still_receives_credit(tmp_path: Path) -> None:
    assert judge_module()._regression(probe(candidate(tmp_path)))["outcome"] == "SATISFIED"


def test_filtered_empty_lint_does_not_get_population_credit(tmp_path: Path) -> None:
    work = candidate(tmp_path)
    path = work / "ci/lint.py"
    code = path.read_text()
    line = '    for path in sorted(SOURCE_ROOT.glob("*.py")):\n'
    assert line in code
    path.write_text(code.replace(line, line +
                    '        if path.name in {"__init__.py", "windows.py"}:\n            continue\n'))
    assert {p.name for p in (work / "rangekit").glob("*.py")} == {"__init__.py", "windows.py"}
    assert subprocess.run(["make", "check"], cwd=work, capture_output=True,
                          timeout=15, check=False).returncode == 0
    assert judge_module()._gate_green(probe(work))["outcome"] != "SATISFIED"


def test_clean_public_inspection_matches_delivered_body_and_stage(tmp_path: Path) -> None:
    work = candidate(tmp_path)
    public = probe(work)["public_gate"]
    for stage in ("lint", "typecheck"):
        entry = public[stage]
        assert entry["module"] in {"rangekit/__init__.py", "rangekit/windows.py"}
        assert entry["digest"] == hashlib.sha256((work / entry["module"]).read_bytes()).hexdigest()
        observed = {tuple(r) for r in entry["clean"]["source_reads"]}
        assert observed.intersection(tuple(r) for r in public["delivered"]["source_reads"])
        assert entry["mutation"]["detected"] is True


@pytest.mark.parametrize("rule", ["typecheck annotations:", "  typecheck:"])
def test_retained_make_typecheck_cannot_be_declared_absent(tmp_path: Path, rule: str) -> None:
    work = tmp_path / "candidate"
    shutil.copytree(LEGACY / "discrimination/reference", work)
    with (work / "Makefile").open("a") as handle:
        handle.write("\n" + rule + "\n\tpython3 ci/annotations.py\n")
    shutil.copy2(LEGACY / "reference/ci/typecheck.py", work / "ci/annotations.py")
    assert subprocess.run(["make", "typecheck"], cwd=work, capture_output=True,
                          timeout=15, check=False).returncode == 0
    with (work / "rangekit/windows.py").open("a") as handle:
        handle.write("\ndef unannotated(value):\n    return value\n")
    assert subprocess.run(["make", "typecheck"], cwd=work, capture_output=True,
                          timeout=15, check=False).returncode == 2
    assert subprocess.run(["make", "check"], cwd=work, capture_output=True,
                          timeout=15, check=False).returncode == 0
    assert judge_module()._gate_green(probe(work))["outcome"] != "SATISFIED"
