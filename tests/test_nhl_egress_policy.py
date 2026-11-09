"""Synthetic permits qualify policy seams, never authorize Docker preparation."""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from test_agent_trial_fixture import GATE_ENTRY, _fixture, _planned
from test_nhl_egress_behavior import ROOT, data, run_control, summary

from skillc import agent_trial as at
from skillc import calibration, cli, egress, trial
from skillc import calibration_run as cr
from skillc import docker_backend as db
from skillc import nhl_egress_policy as nhl
from skillc.backend import BackendUnavailable, Limits


def configured(tmp_path: Path, attempt: str = 'synthetic') -> tuple[db.DockerBackend, nhl.Session]:
    session = nhl.Session(data())
    permit = session.issue(attempt)
    backend = db.DockerBackend('fake-image', tmp_path, egress=True, egress_hosts=session.policy.hosts,
                               nhl_egress_permit=permit)
    session.bind(permit, backend)
    return backend, session


@pytest.mark.parametrize('baseline', [False, True], ids=['treated', 'baseline'])
def test_registered_control_permit_crosses_only_the_fixture_policy_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, baseline: bool,
) -> None:
    fixture, surface = _fixture(tmp_path / 'fixture', 'clean')
    experiment, attempt = _planned(trial.open_store(tmp_path / 'store', forbidden=[]))
    backend, _ = configured(tmp_path, attempt)

    class PastPolicy(Exception):
        pass

    def stop_before_preparation(*_args: Any) -> Any:
        raise PastPolicy

    monkeypatch.setattr(at, '_gate_witness_choice', stop_before_preparation)
    with pytest.raises(PastPolicy):
        at.run_one_attempt(backend=backend, experiment=experiment, attempt_id=attempt, client='codex',
                           base_argv=['codex'], prompt='p', skill_name=None, surface=surface,
                           limits=Limits(timeout=5), base=tmp_path, fixture=fixture,
                           gate_entrypoint=None if baseline else GATE_ENTRY, fixture_baseline=baseline)


@pytest.mark.parametrize('defect', ['copy', 'forged', 'issuer', 'backend', 'attempt', 'changed', 'revoked'])
def test_registration_cannot_be_replaced_by_a_permit_shaped_value(tmp_path: Path, defect: str) -> None:
    backend, session = configured(tmp_path)
    permit = backend.nhl_egress_permit
    assert isinstance(permit, nhl.Permit)
    if defect == 'copy':
        object.__setattr__(backend, 'nhl_egress_permit', copy.copy(permit))
    elif defect == 'forged':
        object.__setattr__(backend, 'nhl_egress_permit', nhl.Permit(session, 'synthetic'))
    elif defect == 'issuer':
        fake = SimpleNamespace(policy=session.policy, require=lambda *_a, **_k: None)
        object.__setattr__(backend, 'nhl_egress_permit', nhl.Permit(cast(nhl.Session, fake), 'synthetic'))
    elif defect == 'backend':
        backend = db.DockerBackend('fake-image', tmp_path, egress=True, egress_hosts=session.policy.hosts,
                                   nhl_egress_permit=permit)
    elif defect == 'changed':
        session._data['extra'] = 'changed after registration'
    elif defect == 'revoked':
        session._permits.clear()
    with pytest.raises(nhl.PolicyRefused):
        nhl.require_backend(backend, 'other' if defect == 'attempt' else 'synthetic')


def test_permit_is_unusable_until_bound_once(tmp_path: Path) -> None:
    session = nhl.Session(data())
    permit = session.issue('synthetic')
    backend = db.DockerBackend('fake-image', tmp_path, egress=True, egress_hosts=session.policy.hosts,
                               nhl_egress_permit=permit)
    with pytest.raises(nhl.PolicyRefused):
        nhl.require_backend(backend, 'synthetic')
    session.bind(permit, backend)
    assert nhl.require_backend(backend, 'synthetic') == session.policy
    with pytest.raises(nhl.PolicyRefused):
        session.bind(permit, backend)
    with pytest.raises(nhl.PolicyRefused):
        session.issue('synthetic')


@pytest.mark.parametrize('entry', ['prepare', 'execute'])
@pytest.mark.parametrize('mode', ['registered-control', 'raw', 'upper', 'trailing-dot'])
def test_no_control_or_raw_alias_can_launch_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, entry: str,
) -> None:
    backend, session = configured(tmp_path)
    if mode != 'registered-control':
        object.__setattr__(backend, 'nhl_egress_permit', None)
        spelling = 'API-WEB.NHLE.COM' if mode == 'upper' else 'api-web.nhle.com.' if mode == 'trailing-dot' else nhl.NHL_HOSTS[0]
        object.__setattr__(backend, 'egress_hosts', (*egress.ALLOWED_HOSTS, spelling))
    calls = []

    def no_io(*args: Any, **_kwargs: Any) -> Any:
        calls.append(args)
        raise AssertionError('a refused launch reached subprocess I/O')

    monkeypatch.setattr(subprocess, 'run', no_io)
    with pytest.raises(BackendUnavailable, match='nhl_egress'):
        if entry == 'prepare':
            backend.prepare('synthetic')
        else:
            backend.execute(db._Handle('synthetic', 'controlled', {}), ['controlled'], Limits(timeout=1))
    assert not calls
    assert not nhl.APPROVED_LIVE_DECLARATIONS
    assert session.policy.purpose == 'synthetic-control'


@pytest.mark.parametrize('target,allowed', [
    ('api-web.nhle.com:443', True), ('api.nhle.com:443', True),
    ('API.NHLE.COM.:443', True), ('chatgpt.com:443', True),
    ('other.api.nhle.com:443', False), ('api.nhle.com.evil.invalid:443', False),
    ('api.nhle.com:80', False), ('192.0.2.1:443', False),
    ('api.nhle.com@evil.invalid:443', False), ('evil.invalid:443', False),
])
def test_the_same_shipped_connect_decision_uses_the_exact_declared_hosts(target: str, allowed: bool) -> None:
    policy = nhl.parse(data())
    assert policy is not None
    assert policy.allowed(target) is allowed
    argv = egress.proxy_run_argv(('fake-docker',), image='fake-image', name='proxy', labels={},
                                 container_user='candidate', subnet='192.0.2.0/24',
                                 hosts=policy.hosts, policy_document=policy.document())
    assert json.loads(argv[-3]) == policy.document() and argv[-2] == policy.digest


@pytest.mark.parametrize('case', ['allowed', 'denied', 'bypass', 'missing', 'unparsed', 'wrong-digest'])
def test_active_execution_cancel_observer_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    backend, session = configured(tmp_path)
    entries = [{'event': 'start', 'digest': session.policy.digest}]
    if case in ('allowed', 'denied', 'bypass'):
        entries.append({'decision': 'denied' if case == 'denied' else 'allowed',
                        'target': 'api.nhle.com:443' if case == 'allowed' else 'evil.invalid:443'})
    if case == 'wrong-digest':
        entries[0]['digest'] = 'sha256:' + '0' * 64
    raw = '\n'.join(json.dumps(row) for row in entries).encode()
    if case == 'unparsed':
        raw += b'\ntruncated'
    monkeypatch.setattr(db.DockerBackend, 'egress_log', lambda _b, _h: None if case == 'missing' else raw)
    handle = db._Handle('synthetic', 'controlled', {})
    assert backend._nhl_egress_stop(handle, session.policy) is (case != 'allowed')
    if case != 'allowed':
        # A later readable/healthy log cannot erase an earlier controller stop.
        healthy = json.dumps({'event': 'start', 'digest': session.policy.digest}).encode()
        monkeypatch.setattr(db.DockerBackend, 'egress_log', lambda _b, _h: healthy)
        assert backend._nhl_egress_stop(handle, session.policy)
        assert isinstance(backend.nhl_egress_permit, nhl.Permit) and backend.nhl_egress_permit.stopped


def test_execute_connects_the_policy_observer_to_its_existing_cancellation_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, session = configured(tmp_path)
    require = nhl.require_backend
    # Replace the never-authorized live boundary only for this fake executor.
    # The unpatched prepare/execute refusal is qualified separately above.
    monkeypatch.setattr(nhl, 'require_backend', lambda b, a, **_kw: require(b, a))
    monkeypatch.setattr(db.DockerBackend, '_inspect', lambda *_a: (True, False, 'running'))
    monkeypatch.setattr(db.DockerBackend, '_forwarding_available', lambda *_a: False)
    raw = '\n'.join(json.dumps(row) for row in [
        {'event': 'start', 'digest': session.policy.digest},
        {'decision': 'denied', 'target': 'evil.invalid:443'},
    ]).encode()
    monkeypatch.setattr(db.DockerBackend, 'egress_log', lambda *_a: raw)

    class FakeExecutorObservedStop(Exception):
        pass

    def fake_executor(_b: Any, _h: Any, _argv: Any, _limits: Any, cancel: Any,
                      _stdin: Any, **_kwargs: Any) -> Any:
        assert cancel() is True
        raise FakeExecutorObservedStop

    monkeypatch.setattr(db.DockerBackend, '_launch_and_wait', fake_executor)
    with pytest.raises(FakeExecutorObservedStop):
        backend.execute(db._Handle('synthetic', 'controlled', {}), ['controlled'], Limits(timeout=1))


def test_public_readonly_recovery_keeps_native_stop_and_checkpoint_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_control(tmp_path, monkeypatch, summary({}, {'evil.invalid:443': 1}))
    directory = tmp_path / 'run'
    checkpoint = directory / cr.OUTCOMES_FILENAME
    before = checkpoint.read_bytes()
    declaration = tmp_path / 'declaration.json'
    declaration.write_text(json.dumps(data()))
    assert cli.main(['calibration-report', str(directory), '--declaration', str(declaration)]) == 1
    report = json.loads((directory / cr.REPORT_FILENAME).read_text())
    assert report['containment_stop']['evidence']['undeclared_requests'] == ['evil.invalid:443']
    assert checkpoint.read_bytes() == before


@pytest.mark.parametrize('defect', ['missing', 'changed-declaration', 'forged-marker'])
def test_recovery_refuses_mixed_binding_changed_approval_or_forged_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str,
) -> None:
    experiment, outcomes, _ = run_control(tmp_path, monkeypatch, summary({}, {'evil.invalid:443': 1}))
    if defect == 'forged-marker':
        outcomes[0].record['schedule_containment_stop'] = {'trigger': 'forged'}
    else:
        first = next(experiment.attempts())[0]['config']
        assert isinstance(first, dict)
        digest = str(first['digest'])
        read = trial._read_object

        def changed(root: Path, identity: str) -> bytes:
            raw = read(root, identity)
            if identity == digest:
                config = json.loads(raw)
                if defect == 'missing':
                    del config['nhl_egress']
                else:
                    config['nhl_egress']['declaration']['nhl_egress']['purpose'] = 'live'
                return json.dumps(config).encode()
            return raw

        monkeypatch.setattr(trial, '_read_object', changed)
    with pytest.raises(cr.CalibrationRefused):
        cr.build_report(experiment, outcomes, declared_model='gpt-6-astra', declared_effort='high')


@pytest.mark.parametrize('control', json.loads((ROOT / 'controls/nhl-egress/mutants.json').read_text()),
                         ids=lambda row: row['name'])
def test_committed_blind_policy_and_authority_mutants_lose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, control: dict[str, str],
) -> None:
    if control['name'] == 'always-issue':
        monkeypatch.setattr(nhl, 'require_live_authority', lambda _data: None)
        # Through the pre-existing approval consumer, the mutant falsely admits.
        admitted = False
        try:
            calibration.require_approved(calibration.parse_declaration(data()), ROOT)
            admitted = True
        except calibration.DeclarationRefused:
            pass
        assert admitted, 'mutant must expose the unauthorized approval witness'
    else:
        if control['name'] == 'allow-all':
            monkeypatch.setattr(nhl.Policy, 'allowed', lambda *_a: True)
            observed = summary({'evil.invalid:443': 1}, {})
        else:
            original = nhl.violation
            monkeypatch.setattr(nhl, 'violation', lambda s, p: original({**s, 'denied': {}}, p))
            observed = summary({}, {'evil.invalid:443': 1})
        _, _, calls = run_control(tmp_path, monkeypatch, observed)
        assert len(calls) == 4, 'mutant must expose the known-bad continuation'


def test_committed_mutant_population_is_complete() -> None:
    cases = json.loads((ROOT / 'controls/nhl-egress/mutants.json').read_text())
    assert len(cases) == 3
    assert {row['name'] for row in cases} == {'allow-all', 'ignore-denied', 'always-issue'}
