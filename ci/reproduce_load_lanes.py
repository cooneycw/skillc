"""Manual #462 quota experiment: external contention stays INVALID; phased work passes.

Run explicitly in a Linux container with a CPU quota of at most two CPUs:
  uv run python3 -m ci.reproduce_load_lanes contended --report-dir reports/contended
  uv run python3 -m ci.reproduce_load_lanes split --report-dir reports/split
This is evidence collection, not an automatic retry or a weaker harness verdict.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TEST = "tests/test_load_harness.py::test_busy_workers_are_attributed_their_cpu_time"
WORK = "controls/pytest-lanes/workload.py"


def validate_order(lanes: list[dict], work_reaped_ns: int) -> None:
    if ([lane["lane"] for lane in lanes] != ["ordinary", "serial"]
            or not all(lane["reaped"] for lane in lanes)
            or not (work_reaped_ns <= lanes[0]["end_ns"] <= lanes[1]["start_ns"])):
        raise ValueError("ordinary competing work was not reaped before the serial phase")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("contended", "split"))
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
    if quota == "max" or int(quota) / int(period) > 2:
        parser.error("this reproducer requires a CPU quota of at most two CPUs")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "contended":
        processes = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(4)]
        try:
            result = subprocess.run([sys.executable, "-m", "pytest", "-n", "0", "-q", TEST],
                                    capture_output=True, text=True, check=False)
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                process.wait(timeout=10)
        log = result.stdout + result.stderr
        (args.report_dir / "pytest.log").write_text(log)
        if result.returncode != 1 or "LOAD_PHASE: INVALID" not in log:
            raise ValueError("forced external contention did not produce the expected INVALID red")
        print("load-lanes-reproduce: ok - external contention still refuses (INVALID, pytest exit 1)")
    else:
        command = [sys.executable, "ci/run_pytest_lanes.py", "--workers", "4", "--report-dir",
                   str(args.report_dir), "--", WORK, TEST]
        with (args.report_dir / "pytest.log").open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        lanes = json.loads((args.report_dir / "pytest-lanes.json").read_text())["lanes"]
        report = ET.parse(args.report_dir / "pytest-ordinary.xml")
        prop = next(p for p in report.iter("property") if p.get("name") == "work_reaped_ns")
        work_reaped_ns = int(prop.attrib["value"])
        validate_order(lanes, work_reaped_ns)
        print(json.dumps({"lanes": lanes, "work_reaped_ns": work_reaped_ns}, indent=2))
        print("load-lanes-reproduce: ok - ordinary competing work reaped, then real attribution test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
