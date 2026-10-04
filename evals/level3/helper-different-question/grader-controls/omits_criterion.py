#!/usr/bin/env python3
"""Broken grader control: a plausible report that silently drops
`one-section-per-step` - grading only the report and the content would pass
wrong/changed-not-fixed, whose runbook still has two Step 5 sections, exactly
the gap this task's blinding control exists to show.
"""

import json

CRITERIA = ("report-verdict", "approved-content-present", "other-content-preserved")
print(json.dumps({
    "grader": {"id": "helper-different-question", "revision": "control-omits-criterion"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["partial"]}
        for c in CRITERIA
    ],
}))
