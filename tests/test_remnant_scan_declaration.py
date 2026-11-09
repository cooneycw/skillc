"""Ignored-field regressions can run unchanged on the actual parent revision."""
from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import stamp_approval
from test_calibration import ROOT, _approved
from test_calibration_discrimination_declaration import _approved as discrimination
from test_vm_admission import policy
from test_vm_identity import environment

from skillc import calibration


def data() -> dict[str, Any]:
    plan = json.loads((ROOT / 'controls/remnant-scan/plan.json').read_text())['remnant_scan']
    return stamp_approval({**_approved(), 'execution_environment': environment(),
                           'operator_admission': policy(), 'remnant_scan': plan})


@pytest.mark.parametrize('fault', ['empty-plan', 'missing-roles', 'missing-cap', 'unknown-field',
                                  'wrong-wave', 'boolean-limit', 'missing-admission'])
def test_invalid_opt_in_is_refused(fault: str) -> None:
    raw = data()
    if fault == 'empty-plan':
        raw['remnant_scan']['waves'] = []
    elif fault == 'missing-roles':
        raw['remnant_scan']['waves'][0]['roles'] = []
    elif fault == 'missing-cap':
        del raw['remnant_scan']['limits']['depth']
    elif fault == 'unknown-field':
        raw['remnant_scan']['exclude'] = ['*']
    elif fault == 'wrong-wave':
        raw['remnant_scan']['waves'][0]['wave_id'] = 'unplanned'
    elif fault == 'boolean-limit':
        raw['remnant_scan']['limits']['entries'] = True
    else:
        del raw['operator_admission']
    with pytest.raises(calibration.DeclarationRefused, match='remnant_scan'):
        calibration.parse_declaration(raw)


def test_discrimination_cannot_ignore_opt_in() -> None:
    raw = discrimination()
    raw['remnant_scan'] = data()['remnant_scan']
    with pytest.raises(calibration.DeclarationRefused, match='remnant_scan'):
        calibration.parse_discrimination_declaration(raw)


@pytest.mark.parametrize('gate', ['record', 'dispatch'])
def test_discrimination_cannot_acquire_opt_in_after_parsing(gate: str) -> None:
    decl = calibration.parse_discrimination_declaration(discrimination())
    decl.data['remnant_scan'] = data()['remnant_scan']  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused, match='remnant_scan'):
        if gate == 'record':
            calibration.require_discrimination_approval_record(decl)
        else:
            calibration.require_approved_discrimination(decl, ROOT)


def test_valid_opt_in_is_bound_by_existing_whole_declaration_approval() -> None:
    decl = calibration.parse_declaration(data())
    calibration.approval_record_binding(decl)
    decl.data['remnant_scan']['limits']['depth'] -= 1  # type: ignore[index]
    with pytest.raises(calibration.DeclarationRefused):
        calibration.approval_record_binding(decl)
