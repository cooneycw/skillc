#!/usr/bin/env python3
"""Probe for recovery-partial-processing: the ONLY grading code that reads a
candidate-controlled file.

Usage: probe.py CANDIDATE_DIR, with a JSON list of step numbers on stdin
(`inputs.json`). No candidate code runs for this task - the graded
artifacts are `src/output/<n>.json`, `src/report.json` and
`src/disruption-log.json`, all plain data files, mirroring
finish-close-ref's probe.py (`evals/level1/finish-close-ref/probe.py`)
rather than slug-small-fix's function-calling one.

`disruption-log.json` is still read from `src/` alongside `report.json` and
still reported here exactly as found - but the judge no longer trusts this
copy for anything (issue #14): it is the CANDIDATE's own, and a subject that
can write it can write whatever `failed_after_step` it likes inside it. The
judge's actual trust source is `envelope["trusted"]`, a field this probe
never sets - see `grade_recovery.py`'s `_trusted_log`. This candidate-writable
copy stays in the probe's report only as a diagnostic observation, never as
evidence of the disruption point on its own.
"""

import json
import os
import sys

MAX_BYTES = 200_000

report = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)
candidate_dir = sys.argv[1]
src_dir = os.path.join(candidate_dir, "src")
steps = json.loads(sys.stdin.read())


def _read(path: str) -> dict[str, object]:
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_BYTES + 1)
    except OSError as exc:
        return {"read_error": f"{type(exc).__name__}: {exc}"}
    if len(data) > MAX_BYTES:
        return {"read_error": "file exceeds the probe's size limit"}
    return {"text": data.decode("utf-8", errors="replace")}


outputs: dict[str, object] = {}
for step in steps:
    outputs[str(step)] = _read(os.path.join(src_dir, "output", f"{step}.json"))

files: dict[str, object] = {}
for name in ("report.json", "disruption-log.json"):
    files[name] = _read(os.path.join(src_dir, name))

report.write(json.dumps({"outputs": outputs, "files": files}))
report.flush()
