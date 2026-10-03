#!/usr/bin/env python3
"""Broken grader control: a plausible report that silently drops
`gate-honest` - reporting only that the gate is green would pass a candidate
whose gate catches nothing on the restored tree (wrong/gate-also-green-on-
unfixed and wrong/gate-discovery-deleted), exactly the gap this task's own
restore-probe validity controls exist to close.
"""

import json

CRITERIA = ("functional-clamp-fix", "regression-fails-on-original", "gate-green")
print(json.dumps({
    "grader": {"id": "gate-ran-nothing", "revision": "control-omits-criterion"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["partial"]}
        for c in CRITERIA
    ],
}))
