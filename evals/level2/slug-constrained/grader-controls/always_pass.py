#!/usr/bin/env python3
"""Broken grader control: reports every criterion SATISFIED, whatever it is given."""

import json

CRITERIA = (
    "functional-interface", "functional-reported-example", "functional-R1", "functional-R2",
    "functional-R3", "constraint-interface-stability", "constraint-dependency",
    "constraint-data-preservation",
)
print(json.dumps({
    "grader": {"id": "slug-constrained", "revision": "control-always-pass"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["always"]}
        for c in CRITERIA
    ],
}))
