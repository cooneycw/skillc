#!/usr/bin/env python3
"""Broken grader control: a plausible report that silently drops
`pipeline-honest` - reporting only that the pipeline is green would pass a
pipeline whose stages pass whatever they run (wrong/unconditional-success),
exactly the gap #281's "certify unconditional success" item exists to close.
"""

import json

CRITERIA = ("artifacts-present", "pipeline-covers-required-checks", "pipeline-green", "behavior-preserved")
print(json.dumps({
    "grader": {"id": "cicd-pipeline", "revision": "control-omits-criterion"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["partial"]}
        for c in CRITERIA
    ],
}))
