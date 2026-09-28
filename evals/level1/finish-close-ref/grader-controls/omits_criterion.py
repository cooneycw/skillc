#!/usr/bin/env python3
"""Broken grader control: a plausible report that silently drops issue-ref and
stays-open.

The remaining criteria still fail most wrong candidates, so without a required
criterion set this grader would look discriminating while examining two fewer
requirements than the task publishes.
"""

import json

CRITERIA = ("artifact-present", "no-closing-match")
print(json.dumps({
    "grader": {"id": "finish-close-ref", "revision": "control-omits-criterion"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["partial"]}
        for c in CRITERIA
    ],
}))
