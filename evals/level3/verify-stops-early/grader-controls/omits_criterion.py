#!/usr/bin/env python3
"""Broken grader control: a plausible report that silently drops
`regression-fails-on-original` - reporting only the functional fix and a
green gate would pass a candidate whose "regression test" never actually
proves anything (an insensitive or absent test), exactly the gap this
task's own restore-probe validity controls exist to close.
"""

import json

CRITERIA = ("functional-dedupe-fix", "gate-green")
print(json.dumps({
    "grader": {"id": "verify-stops-early", "revision": "control-omits-criterion"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["partial"]}
        for c in CRITERIA
    ],
}))
