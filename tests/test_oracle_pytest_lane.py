"""The artifact qualifier belongs in the isolated phase, with every ID retained (#462)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ci.merge_pytest_reports import serial_identity

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "controls/pytest-oracle-lane"
QUALIFIER = "tests/test_change_with_regression_568.py::test_fixed_population_discriminates_artifacts"


def test_qualifier_identity_is_serial() -> None:
    assert serial_identity("tests.test_change_with_regression_568")
    assert not serial_identity("tests.test_change_with_regression_568_other")


@pytest.mark.parametrize(("lane", "code"), [("serial", 0), ("ordinary", 5)])
def test_real_qualifier_collection_is_isolated(lane: str, code: int) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "ci.pytest_lanes", f"--skillc-test-lane={lane}",
         "--collect-only", "-q", QUALIFIER],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == code, result.stdout + result.stderr
    assert (QUALIFIER in result.stdout) == (lane == "serial")


@pytest.mark.parametrize(("serial", "expected"), [
    ("serial.xml", 0), ("missing.xml", 1),
    ("serial-dropped-qualifier.xml", 1), ("serial-duplicate-qualifier.xml", 1),
])
def test_qualifier_report_controls(tmp_path: Path, serial: str, expected: int) -> None:
    output = tmp_path / "merged.xml"
    result = subprocess.run(
        [sys.executable, "-m", "ci.merge_pytest_reports", str(FIXTURES / "collected.txt"),
         str(FIXTURES / "ordinary.xml"), str(FIXTURES / serial), str(output)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert output.exists() == (expected == 0)
