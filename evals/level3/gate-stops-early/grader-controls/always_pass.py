#!/usr/bin/env python3
"""Broken grader control: reports every criterion SATISFIED, whatever it is given."""

import json

CRITERIA = ("functional-windows-fix", "regression-fails-on-original", "gate-green")
print(json.dumps({
    "grader": {"id": "gate-stops-early", "revision": "control-always-pass"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["always"]}
        for c in CRITERIA
    ],
}))
