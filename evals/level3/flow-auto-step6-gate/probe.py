#!/usr/bin/env python3
"""Probe for the Level 3 flow-auto-step6-gate task (#279).

Nothing in this task's grading comes from candidate files: the verdict,
evidence, effects and source state are all read from controller-held records
in the judge's trusted channel. The probe only lists what the candidate
directory holds, so the staged grading path stays the same one every task
uses. Usage: probe.py CANDIDATE_DIR (stdin: inputs.json, unused).
"""

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    sys.stdin.read()
    root = Path(argv[1])
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    print(json.dumps({"probe": "flow-auto-step6-gate", "files": files}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
