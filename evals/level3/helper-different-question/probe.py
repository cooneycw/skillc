#!/usr/bin/env python3
"""Probe for the Level 3 helper-different-question task.

Usage: probe.py CANDIDATE_DIR, with inputs.json's object on stdin:
`{"report": "<path>", "runbook": "<path>"}`.

Reads two files from the candidate's delivered tree and reports their text,
never a verdict: `grade_helper_different_question.py --judge` holds every
expected value. No candidate code runs - this task is graded from files
alone. Each file is reported as `{"present": bool, "text": str | null,
"error": str | null}`, bounded in size; a symlink is reported as an error,
never followed.
"""

import json
import os
import sys

MAX_BYTES = 256 * 1024


def read(root: str, rel: str) -> dict:
    path = os.path.join(root, rel)
    if os.path.islink(path):
        return {"present": False, "text": None, "error": f"{rel} is a symlink"}
    if not os.path.isfile(path):
        return {"present": False, "text": None, "error": None}
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_BYTES + 1)
    except OSError as exc:
        return {"present": False, "text": None, "error": f"{type(exc).__name__}: {exc}"}
    if len(data) > MAX_BYTES:
        return {"present": True, "text": None, "error": f"{rel} is larger than {MAX_BYTES} bytes"}
    try:
        return {"present": True, "text": data.decode("utf-8"), "error": None}
    except UnicodeDecodeError as exc:
        return {"present": True, "text": None, "error": f"{rel} is not UTF-8: {exc}"}


def main() -> None:
    inputs = json.loads(sys.stdin.read())
    if not isinstance(inputs, dict) or not all(isinstance(inputs.get(k), str) for k in ("report", "runbook")):
        print(json.dumps({"error": "inputs name no report and runbook paths"}))
        return
    root = sys.argv[1]
    print(json.dumps({"report": read(root, inputs["report"]), "runbook": read(root, inputs["runbook"])}))


if __name__ == "__main__":
    main()
