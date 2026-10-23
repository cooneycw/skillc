#!/usr/bin/env python3
"""Probe for the Level 3 flow-check-route task (#530).

Everything the judge scores comes from controller-held records in its trusted
channel, except the report the task asks for: this probe reads `report.json`
(bounded, never executed) from the delivered repository - `repo/report.json`
in a live attempt's frozen workspace, else `report.json` at the candidate
root (a committed qualify candidate). Usage: probe.py CANDIDATE_DIR (stdin:
inputs.json, unused).
"""

import json
import sys
from pathlib import Path

MAX_REPORT = 16384
CANDIDATES = ("repo/report.json", "report.json")


def main(argv: list[str]) -> int:
    sys.stdin.read()
    root = Path(argv[1])
    report: dict[str, object] = {"present": False, "path": None}
    for rel in CANDIDATES:
        path = root / rel
        if path.is_symlink():
            report = {"present": True, "path": rel, "error": "report.json is a symlink"}
            break
        if path.is_file():
            data = path.read_bytes()
            if len(data) > MAX_REPORT:
                report = {"present": True, "path": rel, "error": f"report.json exceeds {MAX_REPORT} bytes"}
            else:
                report = {"present": True, "path": rel, "text": data.decode("utf-8", errors="replace")}
            break
    print(json.dumps({"probe": "flow-check-route", "report": report}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
