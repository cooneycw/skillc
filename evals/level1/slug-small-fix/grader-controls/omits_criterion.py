#!/usr/bin/env python3
"""Broken grader control: a plausible report that silently drops R1 and R2.

The remaining criteria still fail most wrong candidates, so without a required
criterion set this grader would look discriminating while examining two fewer
requirements than the task publishes.
"""

import json

CRITERIA = ("R4-interface", "reported-example", "R3")
print(json.dumps({
    "grader": {"id": "slug-small-fix", "revision": "control-omits-criterion"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["partial"]}
        for c in CRITERIA
    ],
}))
