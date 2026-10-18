#!/usr/bin/env python3
"""Broken grader control: reports every criterion SATISFIED, whatever it is given."""

import json

CRITERIA = ("artifacts-present", "pipeline-covers-required-checks", "pipeline-green", "pipeline-honest", "behavior-preserved")
print(json.dumps({
    "grader": {"id": "cicd-pipeline", "revision": "control-always-pass"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["always"]}
        for c in CRITERIA
    ],
}))
