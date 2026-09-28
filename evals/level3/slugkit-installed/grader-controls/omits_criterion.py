#!/usr/bin/env python3
"""Broken grader control: a plausible report that silently drops
`integration-installed-path` - reporting only the functional unit-test
outcome would let a candidate pass whose installed path is broken, exactly
the gap #13's acceptance line ("a passing unit test must not imply
installed-path success") names directly.
"""

import json

CRITERIA = ("functional-trailing-hyphen",)
print(json.dumps({
    "grader": {"id": "slugkit-installed", "revision": "control-omits-criterion"},
    "criteria": [
        {"id": c, "mandatory": True, "outcome": "SATISFIED", "evidence": ["partial"]}
        for c in CRITERIA
    ],
}))
