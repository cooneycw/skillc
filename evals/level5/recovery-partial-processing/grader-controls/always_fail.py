#!/usr/bin/env python3
"""Broken grader control: reports every criterion VIOLATED, whatever it is given."""

import json

CRITERIA = ("report-present", "work-preserved", "report-supported")
print(json.dumps({
    "grader": {"id": "recovery-partial-processing", "revision": "control-always-fail"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "VIOLATED", "evidence": ["always"]}
        for c in CRITERIA
    ],
}))
