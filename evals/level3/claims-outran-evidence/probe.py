#!/usr/bin/env python3
"""Probe for the Level 3 claims-outran-evidence task.

Usage: probe.py CANDIDATE_DIR, with inputs.json's object on stdin:
`{"report": "<path>", "runbook": "<path>", "delegated_stream": "<path>",
"lint_tool": "<name>"}`.

No candidate code runs here except the tool-availability lookup, which is
the one piece of ground truth that can only be answered by asking THIS
process's own environment at THIS moment - never by reading a file the
candidate could have written, and never by asking the host that happens to
run `qualify.py` a question about the candidate's own attempt. This is the
controller's own check, run once per grading pass, after the candidate
tree is already frozen - the same role `ci/check.py`'s direct execution
plays in `gate-stops-early`'s probe.py. Everything else (the report, the
runbook, the delegated-run stream) is read as raw text/bytes and handed to
the judge unparsed, exactly `helper-different-question`'s own probe.py's
convention: this task is graded from files (plus one live environment
fact), never from a verdict this script computes itself.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

MAX_BYTES = 256 * 1024


def read(root: str, rel: str) -> dict[str, object]:
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


def tool_availability(name: str) -> dict[str, object]:
    """The controller's own, live answer to "is this tool on PATH right
    now" - never derived from anything the candidate tree contains."""
    path = shutil.which(name)
    return {"tool": name, "available": path is not None, "path": path}


def main() -> None:
    inputs = json.loads(sys.stdin.read())
    required = ("report", "runbook", "delegated_stream", "lint_tool")
    if not isinstance(inputs, dict) or not all(
        isinstance(inputs.get(k), str) for k in required
    ):
        print(json.dumps({"error": "inputs name no report/runbook/delegated_stream/lint_tool"}))
        return
    root = sys.argv[1]
    print(json.dumps({
        "report": read(root, inputs["report"]),
        "runbook": read(root, inputs["runbook"]),
        "delegated_stream": read(root, inputs["delegated_stream"]),
        "lint_tool_availability": tool_availability(inputs["lint_tool"]),
    }))


if __name__ == "__main__":
    main()
