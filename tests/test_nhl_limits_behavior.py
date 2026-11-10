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


def test_uncapped_model_usage_preserves_finite_multi_hour_operational_deadlines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Synthetic values qualify the existing clock path; they are not study sizes.
    raw = harness.data()
    raw['shared'].update(per_attempt_seconds=9000, total_seconds=40000)
    declaration = calibration.parse_declaration(stamp_approval(raw))
    now = [0.0]
    budgets = []
    def attempt(**kwargs: Any) -> dict[str, object]:
        budgets.append(kwargs['timeout'])
        assert kwargs['completion_deadline'].end <= 18000
        now[0] += 7200
        return {'disposition': 'inconclusive', 'observation': {'egress': harness.summary({}, {})}}
    monkeypatch.setattr(calibration, 'require_approved', lambda *_a, **_k: None)
    monkeypatch.setattr(cr, 'guard_kwargs', lambda *_a: {})
    monkeypatch.setattr(harness.cc, 'run_level1_agent_attempt', attempt)
    directory = tmp_path / 'run'
    directory.mkdir()
    _experiment, outcomes = cr.run_calibration(
        declaration, run_dir=directory, root=ROOT,
        treatment=cr.Treatment({'skill': b'body'}, 'sha256:' + 'ab' * 32, None, skill_digests=harness._TEST_PINS),
        image_digest=harness._IMAGE_DIGEST, backends=lambda: (object(), object()),
        argv_for=lambda _: ['codex'], clock=lambda: now[0], total_seconds=18000)
    assert budgets == [9000, 9000, 3600]
    assert len(outcomes) == 4 and outcomes[-1].record['disposition'] == 'not-run'


def test_report_derives_declared_mode_from_launch_binding_not_mutable_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, outcomes, _calls = harness.run_control(tmp_path, monkeypatch, harness.summary({}, {}))
    report = cr.build_report(experiment, outcomes, declared_model='gpt-6-astra', declared_effort='high')
    expected = {'declared': {'version': 1, 'mode': 'uncapped'}, 'capped_dispatch_available': False,
                'operational_deadlines_finite': True}
    assert report['nhl_limits'] == expected
    for outcome in outcomes:
        outcome.record['nhl_limits'] = copy.deepcopy(CASES[1]['value'])
    assert cr.build_report(experiment, outcomes, declared_model='gpt-6-astra', declared_effort='high')['nhl_limits'] == expected
    # A report with no bound NHL mode must not silently label legacy work uncapped.
    (tmp_path / 'legacy').mkdir()
    legacy, legacy_outcomes, _calls = harness.run_control(tmp_path / 'legacy', monkeypatch,
                                                        harness.summary({}, {}), opted_in=False)
    assert 'nhl_limits' not in cr.build_report(legacy, legacy_outcomes,
                                             declared_model='gpt-6-astra', declared_effort='high')


@pytest.mark.parametrize('mode', ['absent', 'capped'])
def test_direct_planner_requires_mode_but_can_retain_capped_metadata(tmp_path: Path, mode: str) -> None:
    raw = harness.data()
    if mode == 'absent':
        raw.pop('nhl_limits', None)
    else:
        raw['nhl_limits'] = copy.deepcopy(CASES[1]['value'])
    declaration = calibration.parse_declaration(stamp_approval(raw))
    store = harness.trial.open_store(tmp_path / 'store', forbidden=[])
    before = sorted(store.iterdir())
    def plan() -> Any:
        return cr.plan_calibration(declaration, store, root=ROOT,
                                   treatment_digest='sha256:' + 'ab' * 32,
                                   image_digest=harness._IMAGE_DIGEST, skill_digests=harness._TEST_PINS)
    if mode == 'absent':
        with pytest.raises(cr.CalibrationRefused, match='nhl_limits'):
            plan()
        assert sorted(store.iterdir()) == before
    else:
        _experiment, schedule = plan()
        assert len(schedule) == 4  # Planning only; the execution boundary above refuses it.
