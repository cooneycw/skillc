"""The isolated load-harness invocation cannot disappear from either gate (#462)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "controls/pytest-lanes"


def test_both_gates_use_the_split_runner() -> None:
    for path in (ROOT / "Makefile", ROOT / ".woodpecker/ci.yml"):
        assert "ci/run_pytest_lanes.py" in path.read_text()


def test_committed_report_pair_passes(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ci.merge_pytest_reports", str(FIXTURES / "collected.txt"),
         str(FIXTURES / "ordinary.xml"), str(FIXTURES / "serial.xml"), str(tmp_path / "merged.xml")],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("ordinary", "serial"), [
    ("ordinary.xml", "missing.xml"),
    ("ordinary.xml", "serial-dropped.xml"),
    ("ordinary.xml", "serial-duplicate.xml"),
    ("ordinary-incomplete.xml", "serial.xml"),
])
def test_committed_bad_report_pairs_refuse(tmp_path: Path, ordinary: str, serial: str) -> None:
    output = tmp_path / "merged.xml"
    output.write_text("stale success must not survive refusal")
    result = subprocess.run(
        [sys.executable, "-m", "ci.merge_pytest_reports", str(FIXTURES / "collected.txt"),
         str(FIXTURES / ordinary), str(FIXTURES / serial), str(output)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "pytest-lanes: FAIL" in result.stderr
    assert not output.exists()
