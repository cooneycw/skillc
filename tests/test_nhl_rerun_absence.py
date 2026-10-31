"""Model-free controls for the real replay cleanup witness (Refs #634, #663)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from test_nhl_rerun_live import container_is_absent

CASES = {case['name']: case for case in json.loads((Path(__file__).resolve().parents[1] /
                    'controls/nhl-rerun-absence/cases.json').read_text())}
CASE_IDS = [
    'docker29-lowercase', 'legacy-capitalized', 'legacy-daemon-container',
    'container-still-exists', 'unrelated-inspect-error', 'wrong-object',
    'wrong-object-case', 'daemon-unavailable', 'conflicting-object-payload',
    'malformed-output', 'wrong-exit-status', 'success-with-error-text',
]


@pytest.mark.parametrize('case_id', CASE_IDS)
def test_container_absence_controls(case_id: str) -> None:
    # Explicit IDs keep an empty or shortened control file from becoming skips.
    case: dict[str, Any] = CASES[case_id]
    name = 'nhl-replay-control-source'
    inspected = subprocess.CompletedProcess(['docker', 'inspect', name], case['returncode'],
                                            case['stdout'], case['stderr'])
    assert container_is_absent(name, inspected) is case['absent']
