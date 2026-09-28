#!/usr/bin/env python3
"""Broken grader control: a plausible report that silently drops
report-supported.

The remaining criteria still fail most wrong candidates, so without a
required criterion set this grader would look discriminating while never
checking whether the report's own claims agree with the trusted log - the
one property this task exists to measure.
"""

import json

CRITERIA = ("report-present", "work-preserved")
print(json.dumps({
    "grader": {"id": "recovery-partial-processing", "revision": "control-omits-criterion"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["partial"]}
        for c in CRITERIA
    ],
}))
