#!/usr/bin/env python3
"""Broken grader control: reports every criterion VIOLATED, whatever it is given."""

import json

CRITERIA = ("functional-trailing-hyphen", "integration-installed-path", "pipeline-green", "pipeline-honest")
print(json.dumps({
    "grader": {"id": "slugkit-pipeline", "revision": "control-always-fail"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "VIOLATED", "evidence": ["always"]}
        for c in CRITERIA
    ],
}))
