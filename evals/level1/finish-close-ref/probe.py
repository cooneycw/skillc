#!/usr/bin/env python3
"""Probe for the Level 1 finish-close-ref task: the ONLY grading code that reads a
candidate-controlled artifact.

Usage: probe.py CANDIDATE_DIR, with a JSON list of file names (relative to
CANDIDATE_DIR/src) on stdin.

It reads each named file as bytes and reports its raw text. That report is an
OBSERVATION, not a verdict: the probe never sees the closing-keyword rule the
judge grades against, and the judge (grade_ref.py --judge) reads it afterward,
in a separate process that starts only once every process this one started is
gone.

No candidate code runs here - the graded artifact is plain text, not source -
but it is still read from the untrusted candidate copy, so a missing, oversized
or unreadable file is reported as such, never let crash the probe.
"""

import json
import os
import sys

MAX_BYTES = 200_000

report = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)
names = json.loads(sys.stdin.read())
src_dir = os.path.join(sys.argv[1], "src")
files: dict[str, object] = {}
for name in names:
    path = os.path.join(src_dir, name)
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_BYTES + 1)
    except OSError as exc:
        files[name] = {"read_error": f"{type(exc).__name__}: {exc}"}
        continue
    if len(data) > MAX_BYTES:
        files[name] = {"read_error": "file exceeds the probe's size limit"}
        continue
    files[name] = {"text": data.decode("utf-8", errors="replace")}
report.write(json.dumps({"files": files}))
report.flush()
