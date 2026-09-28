#!/usr/bin/env python3
"""Broken grader control: reports every criterion VIOLATED, whatever it is given."""

import json

CRITERIA = ("artifact-present", "issue-ref", "stays-open", "no-closing-match")
print(json.dumps({
    "grader": {"id": "finish-close-ref", "revision": "control-always-fail"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "VIOLATED", "evidence": ["always"]}
        for c in CRITERIA
    ],
}))
