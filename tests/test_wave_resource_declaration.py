"""Existing declaration consumers expose ignored resource input before the fix."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import test_nhl_egress_behavior as harness
from conftest import stamp_approval

from skillc import calibration

ROOT = Path(__file__).resolve().parents[1]


def data() -> dict[str, Any]:
    raw = harness.data()
    raw['wave_accounting'] = json.loads((ROOT / 'controls/wave-accounting/plan.json').read_text())['wave_accounting']
    raw['wave_resources'] = json.loads((ROOT / 'controls/wave-resources/policy.json').read_text())
    return stamp_approval(raw)


@pytest.mark.parametrize('fault', ['unknown', 'missing-cpu', 'missing-memory', 'boolean-cpu', 'fraction-memory',
                                  'negative', 'overflow', 'missing-role', 'extra-role', 'duplicate-role',
                                  'role-order', 'sizing', 'concurrency', 'missing-aux', 'missing-reservations',
                                  'bad-multiplicity', 'no-plan', 'missing-age', 'nonfinite-age'])
def test_existing_parser_refuses_incomplete_or_misbound_wave_resources(fault: str) -> None:
    raw = data()
    policy = raw['wave_resources']
    if fault == 'unknown':
        policy['unexpected'] = True
    elif fault == 'missing-cpu':
        del policy['roles'][2]['cpu_millicores']
    elif fault == 'missing-memory':
        del policy['roles'][2]['memory_bytes']
    elif fault == 'boolean-cpu':
        policy['roles'][2]['cpu_millicores'] = True
    elif fault == 'fraction-memory':
        policy['roles'][2]['memory_bytes'] = 1.5
    elif fault == 'negative':
        policy['roles'][2]['memory_bytes'] = -1
    elif fault == 'overflow':
        policy['roles'][2]['memory_bytes'] = 1 << 63
    elif fault == 'missing-role':
        policy['roles'].pop()
    elif fault == 'extra-role':
        policy['roles'].append({'role':'other','cpu_millicores':1,'memory_bytes':1})
    elif fault == 'duplicate-role':
        policy['roles'][2]['role'] = policy['roles'][0]['role']
    elif fault == 'role-order':
        policy['roles'].reverse()
    elif fault == 'sizing':
        policy['sizing_report_digest'] = 'sha256:' + 'ff' * 32
    elif fault == 'concurrency':
        policy['concurrency'] = 'one-role-at-a-time'
    elif fault == 'missing-aux':
        policy['auxiliaries'] = []
    elif fault == 'missing-reservations':
        del policy['reservations']
    elif fault == 'bad-multiplicity':
        policy['auxiliaries'][2]['multiplicity'] = 0
    elif fault == 'no-plan':
        del raw['wave_accounting']
    elif fault == 'missing-age':
        del policy['max_age_seconds']
    else:
        policy['max_age_seconds'] = float('inf')
    with pytest.raises(calibration.DeclarationRefused, match='wave_resources'):
        calibration.parse_declaration(raw)


def test_valid_resource_input_preserves_existing_declaration_identity() -> None:
    raw = data()
    parsed = calibration.parse_declaration(raw)
    assert parsed.data['wave_resources'] == raw['wave_resources']
    unchanged = copy.deepcopy(raw)
    assert calibration.declaration_digest(calibration.parse_declaration(unchanged).data) == calibration.declaration_digest(parsed.data)
