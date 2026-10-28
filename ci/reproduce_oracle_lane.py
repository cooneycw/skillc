"""Reproduce the #462 qualifier red and phased green without editing frozen files.

Explicit Linux two-CPU-quota experiment (not an automatic gate retry):
  uv run python3 -m ci.reproduce_oracle_lane contended --report-dir reports/oracle-red
  uv run python3 -m ci.reproduce_oracle_lane split --report-dir reports/oracle-green
The contended command returns pytest's own nonzero verdict; inspect its JUnit
setup errors to distinguish the five-second probe from other unavailability.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path

from ci.check_pytest_population import outcomes
from ci.reproduce_load_lanes import validate_order

MODULE = "tests/test_change_with_regression_568.py"
CONSUMERS = (
    "test_fixed_population_discriminates_artifacts",
    "test_actual_feature_and_regression_test_reds",
    "test_resources_have_real_refusal_and_positive_twins",
)
WORK = "controls/pytest-oracle-lane/workload.py"


def validate_serial_consumers(path: Path) -> None:
    expected = {(MODULE.removesuffix(".py").replace("/", "."), name): "passed" for name in CONSUMERS}
    try:
        actual = outcomes(path)
    except (OSError, ValueError, ET.ParseError) as exc:
        raise ValueError("serial qualifier proof is missing or incomplete") from exc
    if actual != expected:
        raise ValueError("serial qualifier proof must contain exactly all three passing consumers")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("contended", "split"))
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
    if quota == "max" or int(quota) / int(period) > 2:
        parser.error("this experiment requires a quota of at most two CPUs")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    selection = [MODULE + "::" + name for name in CONSUMERS]
    processes: list[subprocess.Popen] = []
    started = time.monotonic()
    try:
        if args.mode == "contended":
            for _ in range(16):
                processes.append(subprocess.Popen([sys.executable, "-c", "while True: pass"]))
            command = [sys.executable, "-m", "pytest", "-n", "0", "-q", "--durations=0",
                       f"--junit-xml={args.report_dir / 'pytest-report.xml'}", *selection]
        else:
            command = [sys.executable, "ci/run_pytest_lanes.py", "--workers", "2", "--report-dir",
                       str(args.report_dir), "--", WORK, *selection]
        with (args.report_dir / "pytest.log").open("w") as out:
            result = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT, check=False)
    finally:
        for process in processes:
            with suppress(ProcessLookupError):
                process.terminate()
        for process in processes:
            process.wait(timeout=10)
    if result.returncode:
        print(f"oracle-lane-reproduce: pytest exit {result.returncode}; inspect retained setup errors")
        return result.returncode
    if args.mode == "split":
        lanes = json.loads((args.report_dir / "pytest-lanes.json").read_text())["lanes"]
        ordinary = ET.parse(args.report_dir / "pytest-ordinary.xml")
        prop = next(p for p in ordinary.iter("property") if p.get("name") == "work_reaped_ns")
        validate_order(lanes, int(prop.attrib["value"]))
        validate_serial_consumers(args.report_dir / "pytest-serial.xml")
        print(json.dumps({"lanes": lanes, "work_reaped_ns": int(prop.attrib["value"])}, indent=2))
    print(f"oracle-lane-reproduce: {args.mode} completed in {time.monotonic() - started:.3f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
