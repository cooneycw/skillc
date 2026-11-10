"""Behavior reds use pre-existing declaration and schedule consumers, no new API.

The schedule harness replaces approval and the attempt/backend I/O boundaries
ONLY for synthetic in-process observations. Unpatched approval is tested below
and must never authorize these synthetic declarations for real execution.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from conftest import stamp_approval
from test_calibration_run import _IMAGE_DIGEST, _TEST_PINS, _declaration_data

from skillc import calibration, egress, trial
from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import matched_pilot as mp

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / 'controls/nhl-egress/policy.json').read_text())
DOCUMENT = {'policy': 'nhl-declaration-egress', 'version': 1, 'issue': 638,
            'hosts': sorted([*egress.ALLOWED_HOSTS, *POLICY['hosts']]), 'port': 443,
            'stop_on_denied': True,
            'measurement': 'CONNECT authorities; HTTP requests and response codes not measured'}
DIGEST = 'sha256:' + hashlib.sha256(json.dumps(DOCUMENT, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def data() -> dict[str, Any]:
    raw = cast(dict[str, Any], _declaration_data(attempts=2))
    raw['nhl_egress'] = copy.deepcopy(POLICY)
    raw['nhl_limits'] = {'version': 1, 'mode': 'uncapped'}  # Explicit synthetic fixture choice, not a default.
    raw['shared']['agent_network'] = {'policy': 'nhl-declaration-egress', 'allowlist_digest': DIGEST,
                                     'codex_server_side_off': list(egress.CODEX_SERVER_SIDE_OFF)}
    return stamp_approval(raw)


def summary(allowed: dict[str, int], denied: dict[str, int]) -> dict[str, object]:
    return {'status': 'read', 'allowlist_digest': DIGEST, 'unparsed_lines': 0,
            'allowed': allowed, 'denied': denied}


def run_control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, observation: dict[str, object],
                *, opted_in: bool = True) -> tuple[Any, list[mp.AttemptOutcome], list[str]]:
    declaration = calibration.parse_declaration(data() if opted_in else stamp_approval(_declaration_data(attempts=2)))
    calls = []

    def attempt(**kwargs: Any) -> dict[str, object]:
        calls.append(kwargs['attempt_id'])
        return {'disposition': 'inconclusive', 'codex_guard': {'stop': None},
                'observation': {'run_metadata': {'model': 'gpt-6-astra', 'reasoning_effort': 'high'},
                                'server_side_tool_uses': [], 'egress': observation}}

    monkeypatch.setattr(calibration, 'require_approved', lambda *_a, **_k: None)
    monkeypatch.setattr(cr, 'guard_kwargs', lambda *_a: {})
    monkeypatch.setattr(cc, 'run_level1_agent_attempt', attempt)
    directory = tmp_path / 'run'
    directory.mkdir()
    experiment, outcomes = cr.run_calibration(
        declaration, run_dir=directory, root=ROOT,
        treatment=cr.Treatment({'skill': b'body'}, 'sha256:' + 'ab' * 32, None, skill_digests=_TEST_PINS),
        image_digest=_IMAGE_DIGEST, backends=lambda: (object(), object()), argv_for=lambda _: ['codex'])
    return experiment, outcomes, calls


@pytest.mark.parametrize('host', ['api-web.nhle.com', 'api.nhle.com'])
def test_declared_nhl_does_not_trigger_global_provider_only_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: str,
) -> None:
    experiment, outcomes, calls = run_control(tmp_path, monkeypatch, summary({host + ':443': 1}, {}))
    assert len(calls) == 4
    report = cr.build_report(experiment, outcomes, declared_model='gpt-6-astra', declared_effort='high')
    assert not report.get('containment_stop')
    rows = report['attempts']
    assert isinstance(rows, list)
    assert all('containment_violation' not in row for row in rows)


@pytest.mark.parametrize('traffic', ['denied-request', 'off-list-success', 'upstream-failed-request'])
def test_strict_nhl_policy_stops_schedule_and_recovery_binds_the_same_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, traffic: str,
) -> None:
    off_list = {'undeclared.invalid:443': 1}
    observation = summary(off_list if traffic == 'off-list-success' else {},
                          off_list if traffic == 'denied-request' else {})
    if traffic == 'upstream-failed-request':
        observation['upstream_failed'] = off_list
    experiment, outcomes, calls = run_control(tmp_path, monkeypatch, observation)
    assert len(calls) == 1
    assert all(o.record['disposition'] == 'not-run' for o in outcomes[1:])
    report = cr.build_report(experiment, outcomes, declared_model='gpt-6-astra', declared_effort='high')
    stop = report['containment_stop']
    assert isinstance(stop, dict) and stop['at_attempt'] == calls[0]
    marker = outcomes[0].record['schedule_containment_stop']
    assert isinstance(marker, dict) and marker['evidence']


def test_legacy_denied_traffic_still_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, calls = run_control(tmp_path, monkeypatch, summary({}, {'undeclared.invalid:443': 1}), opted_in=False)
    assert len(calls) == 4


@pytest.mark.parametrize('change', [
    {'version': True}, {'purpose': 'test'}, {'hosts': ['*.nhle.com']},
    {'hosts': [*POLICY['hosts'], 'undeclared.invalid']}, {'port': 80},
    {'stop_on_denied': False}, {'approved': True},
])
def test_malformed_or_undeclared_widening_is_refused_by_existing_parser(change: dict[str, Any]) -> None:
    raw = data()
    raw['nhl_egress'].update(change)
    with pytest.raises(calibration.DeclarationRefused):
        calibration.parse_declaration(stamp_approval(raw))


@pytest.mark.parametrize('purpose', ['synthetic-control', 'sizing', 'live'])
def test_approval_json_cannot_register_a_frozen_live_declaration(purpose: str) -> None:
    raw = data()
    raw['nhl_egress']['purpose'] = purpose
    declaration = calibration.parse_declaration(stamp_approval(raw))
    with pytest.raises(calibration.DeclarationRefused, match='frozen live declaration'):
        calibration.require_approved(declaration, ROOT)


def test_legacy_policy_and_containment_bytes_match_parent_fixture() -> None:
    record = {'disposition': 'inconclusive', 'observation': {'egress': {'denied': {'undeclared.invalid:443': 1}}}}
    actual = {'document': egress.allowlist_document(), 'digest': egress.allowlist_digest(),
              'denied_traffic': cr.containment_evidence(record)}
    assert trial.canonical(actual) == (ROOT / 'controls/nhl-egress/legacy-policy.json').read_bytes()


@pytest.mark.parametrize('config', [None, 0, False, [], 'nhl_egress'])
def test_malformed_stored_config_keeps_the_existing_report_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: object,
) -> None:
    experiment = SimpleNamespace(root=tmp_path, attempts=lambda: iter([
        ({'config': {'digest': 'a' * 64}}, {})]))
    # Isolate the report's post-verification shape check, not ledger hashing.
    monkeypatch.setattr(trial.Experiment, 'open', lambda _root: experiment)
    monkeypatch.setattr(trial, '_read_object', lambda *_a: json.dumps(config).encode())
    with pytest.raises(cr.CalibrationRefused, match='configuration is not an object'):
        cr.build_report(cast(trial.Experiment, experiment), [], declared_model='fixed', declared_effort='fixed')
