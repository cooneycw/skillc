"""Synthetic operator callbacks and local installation trees only."""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import stamp_approval
from test_calibration import ROOT, _approved
from test_vm_identity import environment, observation

from skillc import calibration
from skillc import vm_admission as va

CONTROLS = ROOT / 'controls/vm-admission'
CASES = json.loads((CONTROLS / 'cases.json').read_text())
NOW = datetime.fromisoformat('2026-01-01T00:10:00Z').timestamp()
WAVE = 'synthetic-wave-1'


@dataclass
class Clocks:
    wall: float = NOW
    mono: float = 10.0


def policy() -> dict[str, Any]:
    return json.loads((CONTROLS / 'policy.json').read_text())['operator_admission']


def declaration() -> calibration.CalibrationDeclaration:
    return calibration.parse_declaration(stamp_approval({**_approved(), 'execution_environment': environment(),
                                                         'operator_admission': policy()}))


def payloads() -> dict[str, Any]:
    return copy.deepcopy(json.loads((CONTROLS / 'receipts.json').read_text())['payloads'])


def session(tmp_path: Path, *, change: dict[str, Any] | None = None) -> tuple[va.WindowSession, Clocks]:
    decl = declaration()
    obs = observation(tmp_path, environment())
    clocks = Clocks()
    facts = payloads()
    change = change or {'action': 'none'}

    def collect(request: dict[str, Any]) -> dict[str, Any]:
        check = request['check']
        response = {key: value for key, value in request.items() if key != 'check'}
        response.update(observed_at=clocks.wall, payload=copy.deepcopy(facts[check]))
        action = change['action']
        if action == 'payload' and check == change['check']:
            response['payload'][change['field']] = change['value']
        elif action == 'receipt' and check == 'runner-drain':
            response[change['field']] = change['value']
        return response

    return va.WindowSession(decl, collector=va.OperatorCollector('synthetic-operator', collect),
                            vm_observation=obs, wall_clock=lambda: clocks.wall,
                            monotonic_clock=lambda: clocks.mono), clocks


def collect_all(window: va.WindowSession, *, reverse: bool = False) -> None:
    for check in reversed(va.CHECKS) if reverse else va.CHECKS:
        window.collect(WAVE, check)


def dispatch(window: va.WindowSession) -> None:
    window.request_dispatch(WAVE, ROOT)


def qualify(admitter: Callable[[va.WindowSession], None], tmp_path: Path) -> None:
    for case in CASES['cases']:
        window, _ = session(tmp_path / case['name'], change=case)
        try:
            if case['action'] != 'no-observation':
                collect_all(window, reverse=case['action'] == 'reverse-order')
            admitter(window)
            actual = 'ADMITTED'
        except (va.AdmissionRefused, calibration.DeclarationRefused):
            actual = 'UNKNOWN'
        assert actual == case['expected'], case['name']
        if actual == 'UNKNOWN':
            row = window.report()['waves'][0]
            assert row['nonstart'] and row['task_status'] == 'UNKNOWN' and row['state'] == 'NONSTART'
        assert len(window.report()['waves']) == 2


def test_committed_operator_evidence_and_nonstart_controls(tmp_path: Path) -> None:
    qualify(dispatch, tmp_path)


def test_committed_blind_admitter_loses_bad_case(tmp_path: Path) -> None:
    control = CASES['qualification_controls'][0]
    assert control['admitter'] == 'always-admit' and control['expected'] == 'REFUSED'
    with pytest.raises(AssertionError, match=control['witness']):
        qualify(lambda _window: None, tmp_path)


def test_dispatch_and_close_are_records_not_task_or_cleanup_success(tmp_path: Path) -> None:
    window, _ = session(tmp_path)
    collect_all(window)
    window.admit(WAVE, ROOT)
    assert window.report()['waves'][0]['state'] == 'ADMITTED'
    dispatch(window)
    row = window.report()['waves'][0]
    assert row['state'] == 'DISPATCHED' and row['dispatch_recorded'] and not row['nonstart']
    assert row['task_status'] == 'UNKNOWN'
    window.close(WAVE)
    report = window.report()
    assert report['waves'][0]['state'] == 'CLOSED'
    assert report['waves'][1]['nonstart'] and report['waves'][1]['task_status'] == 'UNKNOWN'
    report['waves'].clear()
    assert len(window.report()['waves']) == 2
    assert not any(key in window.report() for key in ['credential_removed', 'host_clean', 'runner_restarted'])


@pytest.mark.parametrize('source', ['participant-json', 'wrong-collector', 'copied-receipt'])
def test_untrusted_receipt_cannot_supply_provenance(tmp_path: Path, source: str) -> None:
    window, _ = session(tmp_path)
    request = {**window._binding(WAVE), 'check': 'verified-key'}
    raw: dict[str, Any] = {k: v for k, v in request.items() if k != 'check'}
    raw.update(observed_at=NOW, payload=payloads()['verified-key'])
    if source == 'participant-json':
        candidate: object = raw
    else:
        wrong = va.OperatorCollector('synthetic-operator', lambda _request: raw)
        receipt = wrong.collect(request)
        candidate = receipt if source == 'wrong-collector' else va.Receipt(receipt.sequence, receipt.data)
    with pytest.raises(va.AdmissionRefused, match='provenance'):
        window.record(WAVE, candidate)
    assert window.report()['waves'][0]['nonstart']
    assert window.report()['waves'][0]['state'] == 'NONSTART'


def test_callback_mutation_cannot_rewrite_issued_receipt(tmp_path: Path) -> None:
    window, _ = session(tmp_path)
    response = {**window._binding(WAVE), 'observed_at': NOW, 'payload': payloads()['verified-key']}
    collector = va.OperatorCollector('synthetic-operator', lambda _request: response)
    receipt = collector.collect({**window._binding(WAVE), 'check': 'verified-key'})
    before = receipt.data
    response['payload']['verified'] = False
    assert receipt.data == before and json.loads(receipt.data)['payload']['verified'] is True


@pytest.mark.parametrize('kind', ['duplicate-check', 'sequence-replay', 'wrong-wave'])
def test_replay_and_duplicate_evidence_refuse_without_repair(tmp_path: Path, kind: str) -> None:
    window, _ = session(tmp_path)
    receipt = window.collect(WAVE, 'verified-key')
    with pytest.raises(va.AdmissionRefused):
        if kind == 'duplicate-check':
            window.collect(WAVE, 'verified-key')
        elif kind == 'wrong-wave':
            window.record('synthetic-wave-2', receipt)
        else:
            window.record(WAVE, receipt)
    target = 1 if kind == 'wrong-wave' else 0
    assert window.report()['waves'][target]['state'] == 'NONSTART'
    with pytest.raises(va.AdmissionRefused):
        window.collect('synthetic-wave-2' if target else WAVE, 'runner-drain')


@pytest.mark.parametrize('change', ['stale-receipt', 'future-clock', 'expired-window', 'monotonic-backward',
                                    'monotonic-timeout', 'nonfinite-wall', 'nonfinite-monotonic'])
def test_clocks_remain_separate_and_failure_records_nonstart(tmp_path: Path, change: str) -> None:
    window, clocks = session(tmp_path)
    collect_all(window)
    if change == 'stale-receipt':
        clocks.wall += 31
    elif change == 'future-clock':
        clocks.wall -= 1
    elif change == 'expired-window':
        clocks.wall += 3600
    elif change == 'monotonic-backward':
        clocks.mono -= 1
    elif change == 'monotonic-timeout':
        clocks.mono += 61
    elif change == 'nonfinite-wall':
        clocks.wall = float('nan')
    else:
        clocks.mono = float('inf')
    with pytest.raises(calibration.DeclarationRefused):
        dispatch(window)
    assert window.report()['waves'][0]['state'] == 'NONSTART'
    assert window.report()['waves'][0]['task_status'] == 'UNKNOWN'


def test_late_callback_does_not_earn_a_receipt(tmp_path: Path) -> None:
    window, clocks = session(tmp_path)

    def late(request: dict[str, Any]) -> dict[str, Any]:
        clocks.mono += 61
        return {**{k: v for k, v in request.items() if k != 'check'},
                'observed_at': clocks.wall, 'payload': payloads()[request['check']]}

    window._collector = va.OperatorCollector('synthetic-operator', late)
    with pytest.raises(va.AdmissionRefused, match='deadline'):
        window.collect(WAVE, 'verified-key')
    assert window.report()['waves'][0]['receipts'] == []


def test_admitted_wave_is_rechecked_at_dispatch_and_terminal_after_failure(tmp_path: Path) -> None:
    window, clocks = session(tmp_path)
    collect_all(window)
    window.admit(WAVE, ROOT)
    clocks.wall += 31
    with pytest.raises(calibration.DeclarationRefused):
        dispatch(window)
    clocks.wall -= 31
    with pytest.raises(calibration.DeclarationRefused):
        dispatch(window)
    assert window.report()['waves'][0]['nonstart']


def test_second_dispatch_and_transition_after_close_refuse(tmp_path: Path) -> None:
    window, _ = session(tmp_path)
    collect_all(window)
    dispatch(window)
    with pytest.raises(calibration.DeclarationRefused):
        dispatch(window)
    window.close(WAVE)
    with pytest.raises(va.AdmissionRefused):
        window.collect(WAVE, 'runner-drain')
    with pytest.raises(va.AdmissionRefused):
        window.close('synthetic-wave-2')
    with pytest.raises(va.AdmissionRefused, match='unplanned'):
        window.close('unplanned')


def test_binding_only_declaration_cannot_enter_dispatch_api(tmp_path: Path) -> None:
    data = stamp_approval({**_approved(), 'execution_environment': environment()})
    decl = calibration.parse_declaration(data)
    obs = observation(tmp_path, environment())
    calibration.require_approved(decl, ROOT, vm_observation=obs)
    with pytest.raises(va.AdmissionRefused, match='policy'):
        va.WindowSession(decl, collector=va.OperatorCollector('synthetic-operator', lambda _r: {}),
                         vm_observation=obs, wall_clock=lambda: NOW, monotonic_clock=lambda: 10.0)


@pytest.mark.parametrize('field', ['max_receipt_age_seconds', 'max_clock_sample_age_seconds',
                                 'max_clock_offset_seconds', 'collection_timeout_seconds',
                                 'firewall_policy_digest', 'allowed_workloads'])
def test_owner_policy_has_no_defaults(field: str) -> None:
    data = copy.deepcopy(declaration().data)
    del data['operator_admission']['policy'][field]  # type: ignore[index]
    with pytest.raises(va.AdmissionRefused):
        va.validate(data)


def test_existing_gate_accepts_only_complete_matching_session(tmp_path: Path) -> None:
    window, _ = session(tmp_path)
    collect_all(window)
    calibration.require_approved(window._declaration, ROOT, vm_observation=window._observation,
                                 operator_admission=window.approval_input(WAVE))
    assert window.report()['waves'][0]['state'] == 'COLLECTING'
    assert window.report()['waves'][0]['nonstart']


@pytest.mark.parametrize('field', ['max_receipt_age_seconds', 'firewall_policy_digest'])
def test_old_session_cannot_authorize_reapproved_different_policy(tmp_path: Path, field: str) -> None:
    window, _ = session(tmp_path)
    collect_all(window)
    data: dict[str, Any] = copy.deepcopy(dict(window._declaration.data))
    data['operator_admission']['policy'][field] = (29 if field == 'max_receipt_age_seconds'
                                                  else 'sha256:' + 'c' * 64)  # type: ignore[index]
    changed = calibration.parse_declaration(stamp_approval(data))
    with pytest.raises(calibration.DeclarationRefused, match='binding differs'):
        calibration.require_approved(changed, ROOT, vm_observation=window._observation,
                                     operator_admission=window.approval_input(WAVE))
    assert window.report()['waves'][0]['state'] == 'NONSTART'


def test_callback_and_clock_errors_record_unknown_without_details(tmp_path: Path) -> None:
    window, _ = session(tmp_path)

    def unavailable(_request: object) -> object:
        raise RuntimeError('private operator detail')

    window._collector = va.OperatorCollector('synthetic-operator', unavailable)
    with pytest.raises(va.AdmissionRefused, match='unavailable') as error:
        window.collect(WAVE, 'verified-key')
    assert 'private operator detail' not in str(error.value)
    assert 'private operator detail' not in json.dumps(window.report())
    assert window.report()['waves'][0]['state'] == 'NONSTART'

    other, _ = session(tmp_path / 'clock')
    collect_all(other)
    other._wall_clock = lambda: (_ for _ in ()).throw(RuntimeError('private clock detail'))
    with pytest.raises(calibration.DeclarationRefused, match='wall clock unavailable'):
        dispatch(other)
    assert other.report()['waves'][0]['state'] == 'NONSTART'
    assert 'private clock detail' not in json.dumps(other.report())


def test_concurrent_dispatch_is_recorded_at_most_once(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    window, _ = session(tmp_path)
    collect_all(window)
    barrier = Barrier(2)

    def attempt() -> str:
        barrier.wait(timeout=5)
        try:
            dispatch(window)
            return 'admitted'
        except calibration.DeclarationRefused:
            return 'refused'

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _i: attempt(), range(2)))
    assert sorted(results) == ['admitted', 'refused']
    assert window.report()['waves'][0]['events'].count('DISPATCHED') == 1


@pytest.mark.parametrize('field,value', [
    ('max_receipt_age_seconds', True), ('max_clock_sample_age_seconds', -1),
    ('max_clock_offset_seconds', float('nan')), ('collection_timeout_seconds', 0),
    ('firewall_policy_digest', 'UNKNOWN'), ('allowed_workloads', ['duplicate', 'duplicate']),
])
def test_invalid_owner_policy_cannot_admit(field: str, value: object) -> None:
    data: dict[str, Any] = copy.deepcopy(dict(declaration().data))
    data['operator_admission']['policy'][field] = value
    with pytest.raises(va.AdmissionRefused):
        va.validate(data)


def test_arbitrary_participant_input_cannot_bypass_existing_approval_gate(tmp_path: Path) -> None:
    window, _ = session(tmp_path)
    with pytest.raises(calibration.DeclarationRefused, match='receipts'):
        calibration.require_approved(window._declaration, ROOT, vm_observation=window._observation,
                                     operator_admission={'admitted': True})  # type: ignore[arg-type]
