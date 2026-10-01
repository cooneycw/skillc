#!/usr/bin/env python3
"""Broken grader control: reports every criterion VIOLATED, whatever it is given."""

import json

CRITERIA = ("functional-clamp-fix", "regression-fails-on-original", "gate-honest", "gate-green")
print(json.dumps({
    "grader": {"id": "gate-ran-nothing", "revision": "control-always-fail"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "VIOLATED", "evidence": ["always"]}
        for c in CRITERIA
    ],
}))
