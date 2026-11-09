"""Ignored-field and missing-login regressions run on the unchanged parent API."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import stamp_approval
from test_calibration import ROOT
from test_calibration_discrimination_declaration import _approved as discrimination
from test_remnant_scan_declaration import data as scan_data
from test_vm_admission import NOW, WAVE, Clocks, payloads
from test_vm_identity import environment, observation

from skillc import calibration
from skillc import vm_admission as va


def data() -> dict[str, Any]:
    policy = json.loads((ROOT / 'controls/vm-credential-window/policy.json').read_text())
    return stamp_approval({**scan_data(), **policy})


@pytest.mark.parametrize('fault', ['unknown-field', 'wrong-client', 'wrong-source', 'wrong-class',
                                  'boolean-version', 'persistent-storage', 'broad-mode',
                                  'refresh-allowed', 'missing-scan'])
def test_invalid_credential_window_is_refused(fault: str) -> None:
    raw = data()
    field = raw['credential_window']
    if fault == 'unknown-field':
        field['credential_path'] = 'not-allowed'
    elif fault == 'wrong-client':
        field['client'] = 'unsupported'
    elif fault == 'wrong-source':
        field['source'] = 'transfer'
    elif fault == 'wrong-class':
        field['account_class'] = 'api-key'
    elif fault == 'boolean-version':
        field['version'] = True
    elif fault == 'persistent-storage':
        field['storage']['kind'] = 'disk'
    elif fault == 'broad-mode':
        field['storage']['file_mode'] = 0o644
    elif fault == 'refresh-allowed':
        field['stop_on_refresh'] = False
    else:
        del raw['remnant_scan']
    with pytest.raises(calibration.DeclarationRefused, match='credential_window'):
        calibration.parse_declaration(raw)


def test_discrimination_cannot_ignore_credential_window() -> None:
    raw = discrimination()
    raw['credential_window'] = data()['credential_window']
    with pytest.raises(calibration.DeclarationRefused, match='credential_window'):
        calibration.parse_discrimination_declaration(raw)


def test_existing_approval_gate_requires_login_in_addition_to_host_checks(tmp_path: Path) -> None:
    decl = calibration.parse_declaration(data())
    obs = observation(tmp_path, environment())
    clocks = Clocks()
    facts = payloads()

    def collect(request: dict[str, Any]) -> dict[str, Any]:
        return {**{k: v for k, v in request.items() if k != 'check'},
                'observed_at': NOW, 'payload': copy.deepcopy(facts[request['check']])}

    window = va.WindowSession(decl, collector=va.OperatorCollector('synthetic-operator', collect),
                              vm_observation=obs, wall_clock=lambda: clocks.wall,
                              monotonic_clock=lambda: clocks.mono)
    for check in va.CHECKS:
        window.collect(WAVE, check)
    with pytest.raises(calibration.DeclarationRefused, match='login'):
        calibration.require_approved(decl, ROOT, vm_observation=obs,
                                     operator_admission=window.approval_input(WAVE))
