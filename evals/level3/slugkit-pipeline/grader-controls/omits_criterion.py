#!/usr/bin/env python3
"""Broken grader control: a plausible report that silently drops
`pipeline-honest` - reporting only that the pipeline is green would pass a
candidate whose pipeline catches nothing (wrong/pipeline-neutered), exactly
the gap #204's "pipeline-check validity" acceptance item exists to close.
"""

import json

CRITERIA = ("functional-trailing-hyphen", "integration-installed-path", "pipeline-green")
print(json.dumps({
    "grader": {"id": "slugkit-pipeline", "revision": "control-omits-criterion"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["partial"]}
        for c in CRITERIA
    ],
}))
