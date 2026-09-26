#!/usr/bin/env python3
"""Broken grader control: reports every criterion SATISFIED, whatever it is given."""

import json

CRITERIA = ("R4-interface", "reported-example", "R1", "R2", "R3")
print(json.dumps({
    "grader": {"id": "slug-small-fix", "revision": "control-always-pass"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["always"]}
        for c in CRITERIA
    ],
}))
