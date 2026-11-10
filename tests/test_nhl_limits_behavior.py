"""Existing declaration/scheduling consumers; no new module imports for reds."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import test_nhl_egress_behavior as harness
from conftest import stamp_approval

from skillc import calibration
from skillc import calibration_run as cr

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'controls/nhl-limits/cases.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda row: row['name'])
def test_existing_declaration_consumer_refuses_ambiguous_limit_metadata(case: dict[str, Any]) -> None:
    raw = harness.data()
    raw['nhl_limits'] = case['value']
    raw = stamp_approval(raw)
    if case['valid']:
        parsed = calibration.parse_declaration(raw)
        assert parsed.data['nhl_limits'] == case['value']
    else:
        with pytest.raises(calibration.DeclarationRefused, match='nhl_limits'):
            calibration.parse_declaration(raw)


@pytest.mark.parametrize('mode', ['absent', 'capped'])
def test_new_nhl_schedule_requires_explicit_supported_mode_before_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    raw = harness.data()
    if mode == 'absent':
        raw.pop('nhl_limits', None)
    else:
        raw['nhl_limits'] = copy.deepcopy(CASES[1]['value'])
    raw = stamp_approval(raw)
    monkeypatch.setattr(harness, 'data', lambda: copy.deepcopy(raw))
    with pytest.raises(cr.CalibrationRefused, match='nhl_limits'):
        harness.run_control(tmp_path, monkeypatch, harness.summary({}, {}))
    assert not (tmp_path / 'run' / 'store').exists()


@pytest.mark.parametrize('change', ['mode', 'wall', 'tokens', 'source'])
def test_mode_and_limit_changes_break_existing_whole_approval(change: str) -> None:
    raw = harness.data()
    raw['nhl_limits'] = copy.deepcopy(CASES[1]['value'])
    raw = stamp_approval(raw)
    if change == 'mode':
        raw['nhl_limits'] = {'version': 1, 'mode': 'uncapped'}
    elif change == 'wall':
        raw['nhl_limits']['wall_seconds'] += 1
    elif change == 'tokens':
        raw['nhl_limits']['tokens'] += 1
    else:
        raw['nhl_limits']['sizing_report_digest'] = 'sha256:' + 'cd' * 32
    declaration = calibration.parse_declaration(raw)
    with pytest.raises(calibration.DeclarationRefused, match='exact declaration'):
        calibration.approval_record_binding(declaration)


def test_historical_policy_only_shape_stays_readable_but_does_not_select_a_mode() -> None:
    raw = harness.data()
    raw.pop('nhl_limits', None)
    declaration = calibration.parse_declaration(stamp_approval(raw))
    assert 'nhl_limits' not in declaration.data


@pytest.mark.parametrize('case', [CASES[0], CASES[1]], ids=lambda row: row['name'])
def test_actual_live_nhl_approval_stays_held_for_both_modes(case: dict[str, Any]) -> None:
    raw = harness.data()
    raw['nhl_limits'] = copy.deepcopy(case['value'])
    declaration = calibration.parse_declaration(stamp_approval(raw))
    with pytest.raises(calibration.DeclarationRefused):
        calibration.require_approved(declaration, ROOT)
