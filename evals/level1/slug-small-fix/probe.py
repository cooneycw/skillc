#!/usr/bin/env python3
"""Probe for the Level 1 slug task: the ONLY grading code that runs candidate code.

Usage: probe.py CANDIDATE_DIR, with a JSON list of input titles on stdin.

It imports `CANDIDATE_DIR/src/slugify.py` and reports what `slugify` returned for
each input. That report is an OBSERVATION, not a verdict: the probe never sees an
expected output, and the judge (`grade_slug.py --judge`) compares afterwards, in
a separate process that starts only once every process this one started is gone.

Candidate prints go to stderr, so ordinary output cannot mix with the report,
which is written to a duplicate of the original stdout. Candidate code shares
this process, so it CAN write that duplicate itself. It gains nothing it could
not gain by returning values: the judge reads the report strictly, and what it
reads is still only "what slugify returned".

Runs under `python -I -S -B` (skillc.verify): -S disables site-packages, so R4's
"standard library only" is enforced by the run, not inferred from a string.
"""

import json
import os
import sys

report = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)
sys.path.insert(0, os.path.join(sys.argv[1], "src"))
inputs = json.loads(sys.stdin.read())
try:
    import slugify as module
except BaseException as exc:  # noqa: BLE001 - any failure of candidate code is its own
    report.write(json.dumps({"import_error": f"{type(exc).__name__}: {exc}"}))
    report.flush()
    sys.exit(0)
fn = getattr(module, "slugify", None)
if not callable(fn):
    report.write(json.dumps({"import_error": "src/slugify.py defines no callable slugify"}))
    report.flush()
    sys.exit(0)
outputs = []
for text in inputs:
    try:
        got = fn(text)
    except BaseException as exc:  # noqa: BLE001 - any failure of candidate code is its own
        outputs.append({"raised": f"{type(exc).__name__}: {exc}"})
        continue
    if isinstance(got, str):
        outputs.append({"value": got})
    else:
        outputs.append({"not_str": repr(got)})
report.write(json.dumps({"outputs": outputs}))
report.flush()
