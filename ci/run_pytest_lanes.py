#!/usr/bin/env python3
"""Run ordinary tests, reap pytest, then run isolated self-tests without xdist (#462).

One independent, unpartitioned collection is the population authority. Both
lane reports are mandatory, including a zero-item lane under a user selection.
No failing harness verdict is retried, weakened or turned into a skip here.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ci.check_pytest_population import collected
from ci.merge_pytest_reports import merge, serial_identity


def pytest_command(selection: list[str], lane: str, report: Path, *, workers: str,
                   maxprocesses: int, dist: str, durations: int) -> list[str]:
    return [sys.executable, "-m", "pytest", *selection,
            "-p", "ci.pytest_lanes", f"--skillc-test-lane={lane}",
            "-n", "0" if lane == "serial" else workers,
            f"--maxprocesses={maxprocesses}", f"--dist={dist}", "-rA",
            f"--durations={durations}", f"--junit-xml={report}"]


def run(report_dir: Path, selection: list[str], *, workers: str = "auto",
        maxprocesses: int = 8, dist: str = "loadgroup", durations: int = 0) -> int:
    report_dir.mkdir(parents=True, exist_ok=True)
    collection = report_dir / "pytest-collected.txt"
    output = report_dir / "pytest-report.xml"
    receipt_path = report_dir / "pytest-lanes.json"
    lane_paths = {lane: report_dir / f"pytest-{lane}.xml" for lane in ("ordinary", "serial")}
    for path in (collection, output, receipt_path, *lane_paths.values()):
        path.unlink(missing_ok=True)
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", *selection],
                            capture_output=True, text=True, check=False)
    collection.write_text(result.stdout, encoding="utf-8")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        raise ValueError(f"independent collection failed with exit {result.returncode}")
    expected = collected(collection)
    receipts: list[dict[str, object]] = []
    failed = False
    for lane, report in lane_paths.items():
        command = pytest_command(selection, lane, report, workers=workers,
                                 maxprocesses=maxprocesses, dist=dist, durations=durations)
        started = time.monotonic_ns()
        print(f"pytest-lanes: starting {lane}", flush=True)
        process = subprocess.Popen(command)
        code = process.wait()  # The ordinary pytest and its workers exit before serial starts.
        ended = time.monotonic_ns()
        receipt = {"lane": lane, "pid": process.pid, "start_ns": started, "end_ns": ended,
                   "reaped": process.poll() is not None, "exit_code": code}
        receipts.append(receipt)
        receipt_path.write_text(json.dumps({"lanes": receipts}, indent=2) + "\n", encoding="utf-8")
        print(f"pytest-lanes: reaped {lane} pid={process.pid} exit={code}", flush=True)
        required = {key for key in expected if serial_identity(key[0]) == (lane == "serial")}
        if code == 5 and not required:
            continue  # Pytest's no-tests-selected verdict; an empty XML is still required.
        if code not in (0, 1):
            raise ValueError(f"{lane} invocation did not complete: exit {code}")
        failed |= code != 0
    print(f"pytest-lanes: ok - {merge(collection, lane_paths['ordinary'], lane_paths['serial'], output)}")
    return int(failed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--workers", default="auto")
    parser.add_argument("--maxprocesses", type=int, default=8)
    parser.add_argument("--dist", choices=("loadgroup",), default="loadgroup")
    parser.add_argument("--durations", type=int, default=0)
    parser.add_argument("selection", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    selection = args.selection[1:] if args.selection[:1] == ["--"] else args.selection
    try:
        return run(args.report_dir, selection, workers=args.workers,
                   maxprocesses=args.maxprocesses, dist=args.dist, durations=args.durations)
    except (OSError, UnicodeError, ValueError, ET.ParseError) as exc:
        print(f"pytest-lanes: FAIL - {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
