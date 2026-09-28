#!/usr/bin/env python3
"""Broken grader control: a plausible report that silently drops the two
constraint criteria this task ADDS over Level 1 (constraint-dependency,
constraint-data-preservation).

The remaining criteria still fail most wrong candidates, so without a
required criterion set this grader would look discriminating while never
examining the two dimensions this task exists to add.
"""

import json

CRITERIA = (
    "functional-interface", "functional-reported-example", "functional-R1", "functional-R2",
    "functional-R3", "constraint-interface-stability",
)
print(json.dumps({
    "grader": {"id": "slug-constrained", "revision": "control-omits-criterion"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["partial"]}
        for c in CRITERIA
    ],
}))
