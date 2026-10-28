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
    ("ordinary-count-mismatch.xml", "serial.xml"),
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


@pytest.mark.parametrize(("ordinary", "serial"), [
    ("ordinary.xml", "serial.xml"),
    ("ordinary.xml", "missing.xml"),
    ("ordinary.xml", "serial-dropped.xml"),
    ("ordinary.xml", "serial-duplicate.xml"),
    ("ordinary-incomplete.xml", "serial.xml"),
    ("ordinary-count-mismatch.xml", "serial.xml"),
])
def test_runner_propagates_missing_or_broken_lane_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ordinary: str, serial: str,
) -> None:
    import json
    import shutil

    from ci import run_pytest_lanes as runner

    events: list[str] = []

    def collect(command, **kwargs):
        assert command[3:5] == ["--collect-only", "-q"]
        assert not any("skillc-test-lane" in arg for arg in command)
        return subprocess.CompletedProcess(command, 0, (FIXTURES / "collected.txt").read_text(), "")

    class Process:
        def __init__(self, command):
            self.lane = next(arg.split("=", 1)[1] for arg in command if "--skillc-test-lane=" in arg)
            self.report = Path(next(arg.split("=", 1)[1] for arg in command if "--junit-xml=" in arg))
            self.pid = 123 if self.lane == "ordinary" else 124
            if self.lane == "serial":
                assert events == ["ordinary-start", "ordinary-reaped"]
                assert command[command.index("-n") + 1] == "0"
            events.append(self.lane + "-start")

        def wait(self):
            fixture = ordinary if self.lane == "ordinary" else serial
            if (FIXTURES / fixture).exists():
                shutil.copyfile(FIXTURES / fixture, self.report)
            events.append(self.lane + "-reaped")
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(runner.subprocess, "run", collect)
    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    result = runner.main(["--report-dir", str(tmp_path)])
    assert result == (0 if (ordinary, serial) == ("ordinary.xml", "serial.xml") else 1)
    assert (tmp_path / "pytest-report.xml").exists() == (result == 0)
    lanes = json.loads((tmp_path / "pytest-lanes.json").read_text())["lanes"]
    assert all(lane["reaped"] for lane in lanes)
    assert lanes[0]["end_ns"] <= lanes[1]["start_ns"]


@pytest.mark.parametrize(("expression", "count"), [
    ("bad_readme_version_differs or no_samples_is_invalid_never_a_division", 2),
    ("bad_readme_version_differs", 1),
    ("no_samples_is_invalid_never_a_division", 1),
])
def test_real_k_selection_preserves_population_including_empty_lane(
    tmp_path: Path, expression: str, count: int,
) -> None:
    from ci.check_pytest_population import check, outcomes

    result = subprocess.run(
        [sys.executable, "ci/run_pytest_lanes.py", "--workers", "2", "--report-dir", str(tmp_path),
         "--", "tests/test_readme_drift.py", "tests/test_load_harness.py", "-k", expression],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{count} collected identities" in check(
        tmp_path / "pytest-collected.txt", tmp_path / "pytest-report.xml")
    assert set(outcomes(tmp_path / "pytest-report.xml").values()) == {"passed"}


def test_real_attribution_id_is_in_serial_lane_and_cannot_override_workers() -> None:
    from ci.merge_pytest_reports import serial_identity
    from ci.run_pytest_lanes import pytest_command

    assert serial_identity("tests.test_load_harness")
    assert not serial_identity("tests.test_load_harness_other")
    command = pytest_command(["-n", "4"], "serial", Path("report.xml"), workers="auto",
                             maxprocesses=8, dist="loadgroup", durations=0)
    assert command[-7:-5] == ["-n", "0"]
    assert "--durations=0" in command


@pytest.mark.parametrize(("ordinary_reaped", "end_ns", "serial_start"), [
    (False, 20, 30), (True, 40, 30), (True, 5, 30),
])
def test_order_proof_rejects_unreaped_or_overlapping_work(
    ordinary_reaped: bool, end_ns: int, serial_start: int,
) -> None:
    from ci.reproduce_load_lanes import validate_order

    lanes = [{"lane": "ordinary", "reaped": ordinary_reaped, "end_ns": end_ns},
             {"lane": "serial", "reaped": True, "start_ns": serial_start}]
    with pytest.raises(ValueError, match="not reaped before"):
        validate_order(lanes, 10)
    validate_order([{"lane": "ordinary", "reaped": True, "end_ns": 20},
                    {"lane": "serial", "reaped": True, "start_ns": 30}], 10)
