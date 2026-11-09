"""Synthetic operator/steward fixtures; arbitrary marker bytes remain in memory."""
from __future__ import annotations

import copy
import json
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import stamp_approval
from test_calibration import ROOT
from test_remnant_scan import Fixture as ScanFixture
from test_remnant_scan import PrivateOutput, no_marker
from test_remnant_scan import audit_captured_output as audit_captured_output  # noqa: PLC0414
from test_remnant_scan import fixture as scan_fixture
from test_vm_admission import NOW, WAVE, Clocks, collect_all, dispatch, payloads
from test_vm_admission import session as legacy_session
from test_vm_credential_window_declaration import data
from test_vm_identity import environment, observation

from skillc import calibration, credential
from skillc import credential_steward as cs
from skillc import vm_admission as va
from skillc import vm_credential_window as cw
from skillc.backend import Confirmation

CASES = json.loads((ROOT / 'controls/vm-credential-window/cases.json').read_text())


@dataclass(repr=False)
class SyntheticWindow:
    window: va.WindowSession = field(repr=False)
    clocks: Clocks = field(repr=False)
    facts: dict[str, Any] = field(repr=False)
    collector: va.OperatorCollector = field(repr=False)
    scan: ScanFixture = field(repr=False)
    source: cw.WindowCredentialInput | None = field(default=None, repr=False)
    calls: list[str] = field(default_factory=list, repr=False)

    def __repr__(self) -> str:
        return '<SyntheticWindow redacted>'


def synthetic(tmp_path: Path, *, admitted: bool = True) -> SyntheticWindow:
    scan = scan_fixture(tmp_path / 'scan')
    scan.declaration = calibration.parse_declaration(stamp_approval({**scan.declaration.data,
                                                       'credential_window': data()['credential_window']}))
    obs = observation(tmp_path / 'identity', environment())
    clocks = Clocks()
    facts = {**payloads(), cw.LOGIN: {'account_class': 'owner-subscription', 'login_at': NOW - 1},
             cw.LOGOUT: {'account_class': 'owner-subscription', 'logout_at': NOW}}

    def collect(request: dict[str, Any]) -> dict[str, Any]:
        return {**{k: v for k, v in request.items() if k != 'check'},
                'observed_at': clocks.wall, 'payload': copy.deepcopy(facts[request['check']])}

    collector = va.OperatorCollector('synthetic-operator', collect)
    window = va.WindowSession(scan.declaration, collector=collector, vm_observation=obs,
                              wall_clock=lambda: clocks.wall, monotonic_clock=lambda: clocks.mono)
    result = SyntheticWindow(window, clocks, facts, collector, scan)
    if admitted:
        for check in (*va.CHECKS, cw.LOGIN):
            window.collect(WAVE, check)
        result.source = cast(cw.WindowCredentialInput, window.credential_input(WAVE, ROOT))
    return result


class StewardBackend:
    def __init__(self, owner: SyntheticWindow, role: str, session: cs.CredentialStewardSession, fault: str) -> None:
        self.owner, self.role, self.session, self.fault = owner, role, session, fault

    def __repr__(self) -> str:
        return '<StewardBackend redacted>'

    def event(self, name: str) -> None:
        self.session.decide({'op': 'credential_steward', 'event': name,
                             'seq': len(self.session.events) + 1, 'opens': 0, 'closes': 0})

    def start_root_daemon_in_attempt(self, handle: object, argv: Sequence[str],
                                     timeout: float | None = None) -> bool:
        no_marker(repr(argv).encode(), self.owner.scan.refs)
        self.owner.calls.append('arm:' + self.role)
        if self.fault == 'prepare':
            raise RuntimeError(self.owner.scan.refs._values[0])
        if self.fault != 'arm':
            self.event('armed')
        return True

    def root_output_in_attempt(self, handle: object, argv: Sequence[str], timeout: float | None = None,
                               max_bytes: int = 4096) -> bytes:
        no_marker(repr(argv).encode(), self.owner.scan.refs)
        if argv[0] == 'cat':
            self.owner.calls.append('vault:' + self.role)
            return self.owner.scan.refs._values[0]
        if '-USR1' in argv[2]:
            self.owner.calls.append('resume:' + self.role)
            if self.fault != 'resume':
                self.event('armed')
        else:
            self.owner.calls.append('stop:' + self.role)
            if self.fault != 'stop':
                self.event('stopped')
        return b'confirmed'


def bridge(f: SyntheticWindow, fault: str = 'none') -> cw.StewardBridge:
    assert f.source is not None
    bindings = {}
    for index, role in enumerate(f.source._roles):
        session = cs.CredentialStewardSession('synthetic-attempt-' + role)
        backend = StewardBackend(f, role, session, fault if index == 1 else 'none')

        def prepare(session: cs.CredentialStewardSession = session,
                    backend: StewardBackend = backend) -> cs.CredentialSteward:
            driver = cs.CredentialSteward(session, cs.HOME_CODEX, wait_s=.001)
            driver.start(backend, object(), place=lambda _source: None)
            return driver

        def cleanup(role: str = role) -> Confirmation:
            f.calls.append('cleanup:' + role)
            if fault == 'cleanup':
                raise RuntimeError(f.scan.refs._values[0])
            return Confirmation.CONFIRMED

        bindings[role] = cw.RoleBinding(f'00000000-0000-0000-0000-{index + 1:012x}', prepare, backend,
                                        object(), cleanup)

    def action(name: str) -> Confirmation:
        f.calls.append(name)
        if fault == name:
            raise RuntimeError(f.scan.refs._values[0])
        return Confirmation.CONFIRMED

    def logout() -> object:
        f.calls.append('logout')
        if fault == 'logout':
            raise RuntimeError(f.scan.refs._values[0])
        return f.window.collect_credential_logout(f.source)

    def scan() -> cw.ScanObservation:
        action('scan')
        return cw.ScanObservation(f.scan.run(), f.scan.roots, f.scan.generation)

    actions = cw.CloseActions(lambda: action('freeze'), lambda: action('writers'), logout,
                              lambda: action('remove'), scan, lambda: f.calls.append('export'))
    return cw.StewardBridge(f.source, bindings, actions)


def run_turns(b: cw.StewardBridge, turns: int = 2) -> None:
    for _ in range(turns):
        for role, binding in b._bindings.items():
            b.before_turn(role, binding.session_id)
            b.record_launch(role, binding.session_id)
            # Real clients close their startup reads before the next resume.
            b._drivers[role].session.decide({'op': 'credential_steward', 'event': 'withdrawn',
                'seq': len(b._drivers[role].session.events) + 1, 'opens': 4, 'closes': 4})


def test_login_receipt_has_only_class_time_and_bindings(tmp_path: Path) -> None:
    f = synthetic(tmp_path)
    assert f.source is not None
    raw = json.loads(f.source._receipt.data)
    assert raw['payload'] == {'account_class': 'owner-subscription', 'login_at': NOW - 1}
    assert set(raw) == va.BINDING_KEYS | {'version', 'check', 'authority', 'sequence', 'observed_at', 'payload'}
    no_marker(repr(f.source).encode() + json.dumps(raw).encode(), f.scan.refs)


@pytest.mark.parametrize('fault', ['extra', 'account-id', 'token-digest', 'path', 'wrong-class', 'bad-time'])
def test_login_refuses_every_private_or_unknown_field(tmp_path: Path, fault: str) -> None:
    f = synthetic(tmp_path, admitted=False)
    if fault == 'wrong-class':
        f.facts[cw.LOGIN]['account_class'] = f.scan.refs._values[0].decode('utf-8')
    elif fault == 'bad-time':
        f.facts[cw.LOGIN]['login_at'] = f.scan.refs._values[0].decode('utf-8')
    else:
        f.facts[cw.LOGIN][fault] = f.scan.refs._values[0]
    with pytest.raises(va.AdmissionRefused) as caught:
        f.window.collect(WAVE, cw.LOGIN)
    no_marker(''.join(traceback.format_exception(caught.value)).encode(), f.scan.refs)
    no_marker(''.join(traceback.TracebackException.from_exception(
        caught.value, capture_locals=True).format()).encode(), f.scan.refs)
    assert f.collector._issued == {}


def test_secret_free_default_never_resolves_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail('model-free admission accessed a credential source')
    monkeypatch.setattr(credential, 'resolve_path', forbidden)
    monkeypatch.setattr(credential, 'read_fresh', forbidden)
    window, _ = legacy_session(tmp_path)
    collect_all(window)
    dispatch(window)
    window.close(WAVE)
    assert window.report()['waves'][0]['state'] == 'CLOSED'
    with pytest.raises(va.AdmissionRefused):
        window.credential_input(WAVE, ROOT)


def test_non_opted_in_admission_report_is_byte_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(va.secrets, 'token_hex', lambda count: '11' * count)
    window, _ = legacy_session(tmp_path)
    collect_all(window)
    dispatch(window)
    window.close(WAVE)
    observed = json.dumps(window.report(), sort_keys=True, separators=(',', ':')) + '\n'
    assert observed.encode() == (ROOT / 'controls/vm-credential-window/legacy-admission.json').read_bytes()


@pytest.mark.parametrize('override', ['none', 'env-live', 'env-release', 'env-owner'])
def test_opt_in_dispatch_is_held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: str) -> None:
    if override != 'none':
        monkeypatch.setenv({'env-live': 'SKILLC_CREDENTIAL_WINDOW_ALLOW_LIVE',
                           'env-release': 'SKILLC_ALLOW_RUNNER_RELEASE',
                           'env-owner': 'SKILLC_OWNER_APPROVED'}[override], '1')
    f = synthetic(tmp_path)
    with pytest.raises(va.AdmissionRefused, match='contracts unavailable'):
        f.window.request_dispatch(WAVE, ROOT)
    row = f.window.report()['waves'][0]
    assert row['state'] == 'NONSTART' and row['nonstart'] and not row['dispatch_recorded']
    assert row['task_status'] == 'UNKNOWN'
    assert 'DISPATCHED' not in row['events']


@pytest.mark.parametrize('fault', CASES['steward_faults'])
def test_all_public_sinks_exclude_synthetic_material(tmp_path: Path, fault: str) -> None:
    f = synthetic(tmp_path)
    b = bridge(f, fault)
    ready = b.prepare()
    if ready:
        if fault in ('resume', 'refresh'):
            run_turns(b, 1)
            if fault == 'refresh':
                driver = next(iter(b._drivers.values()))
                driver.session.decide({'op': 'credential_steward', 'event': 'refreshed-captured',
                                       'seq': len(driver.session.events) + 1, 'opens': 4, 'closes': 4})
            with pytest.raises(cw.CustodyRefused):
                run_turns(b, 1)
        else:
            run_turns(b)
    report = b.close()
    output = PrivateOutput(json.dumps(report).encode() + json.dumps(f.window.report()).encode()
              + repr(b).encode() + repr(f.source).encode()
              + b''.join(repr(driver).encode() for driver in b._drivers.values()))
    no_marker(output.data, f.scan.refs)
    for path in tmp_path.rglob('*'):
        if path.is_file():
            no_marker(path.read_bytes(), f.scan.refs)
    assert 'export' not in f.calls
    assert report['runner_held'] and report['status'] == 'UNKNOWN'
    assert set(report['blockers']) == set(CASES['unapproved_contracts'])
    assert len([x for x in f.calls if x.startswith('cleanup:')]) == 2
    if fault == 'none':
        assert report['lifecycle_complete'] and report['stewards_held'] == 2
        assert f.calls.index('freeze') < f.calls.index('vault:integrator') < f.calls.index('stop:integrator')
        assert f.calls.index('writers') < f.calls.index('logout') < f.calls.index('remove') < f.calls.index('scan')
        assert sum(x.startswith('resume:') for x in f.calls) == 2
    before = list(f.calls)
    assert b.close() == report and f.calls == before


@pytest.mark.parametrize('planted', [False, True])
def test_export_blocks_a_planted_role_credential(tmp_path: Path, planted: bool) -> None:
    f = synthetic(tmp_path)
    if planted:
        f.scan.planted_key = 'export-payload'
    b = bridge(f)
    assert b.prepare()
    run_turns(b)
    report = b.close()
    assert report['scan_status'] == ('NOT_CLEAN' if planted else 'CLEAN')
    assert report['status'] == ('NOT_CLEAN' if planted else 'UNKNOWN')
    assert report['runner_held'] and not report['exported'] and 'export' not in f.calls


@pytest.mark.parametrize('fault', ['missing', 'empty', 'wrong-generation', 'public-copy', 'logout', 'cleanup'])
def test_cleanup_release_is_load_bearing(tmp_path: Path, fault: str) -> None:
    f = synthetic(tmp_path)
    if fault == 'missing':
        f.scan.roots['staging'] = tmp_path / 'removed'
    elif fault == 'empty':
        (f.scan.roots['staging'] / 'benign.txt').unlink()
    b = bridge(f, fault)
    assert b.prepare()
    run_turns(b)
    if fault in ('wrong-generation', 'public-copy'):
        result = f.scan.run()
        observation_value: Any = result.public() if fault == 'public-copy' else cw.ScanObservation(
            result, f.scan.roots, object())
        object.__setattr__(b._actions, 'scan', lambda: observation_value)
    report = b.close()
    assert report['runner_held'] and report['status'] == 'UNKNOWN' and 'export' not in f.calls
    if fault not in ('logout', 'cleanup'):
        assert report['scan_status'] == 'UNKNOWN'


@pytest.mark.parametrize('fault', ['future', 'before-window', 'stale-receipt', 'copied-input', 'new-wave-input'])
def test_login_input_lifetime_and_custody_are_bound(tmp_path: Path, fault: str) -> None:
    f = synthetic(tmp_path, admitted=False)
    if fault in ('future', 'before-window'):
        f.facts[cw.LOGIN]['login_at'] = NOW + 1 if fault == 'future' else 0
    for check in (*va.CHECKS, cw.LOGIN):
        f.window.collect(WAVE, check)
    if fault in ('future', 'before-window'):
        with pytest.raises(calibration.DeclarationRefused):
            f.window.credential_input(WAVE, ROOT)
        return
    source = cast(cw.WindowCredentialInput, f.window.credential_input(WAVE, ROOT))
    if fault == 'stale-receipt':
        f.clocks.wall += 31
        value = source
    elif fault == 'copied-input':
        value = cw.WindowCredentialInput(source._issuer, source._wave, source._receipt, source._roles)
    else:
        value = cw.WindowCredentialInput(source._issuer, 'synthetic-wave-2', source._receipt, source._roles)
    with pytest.raises(va.AdmissionRefused):
        value.require_active()


@pytest.mark.parametrize('fault', ['foreign-session', 'duplicate-arm', 'launch-before-arm', 'refresh-before-launch'])
def test_role_turn_binding_cannot_be_bypassed(tmp_path: Path, fault: str) -> None:
    f = synthetic(tmp_path)
    b = bridge(f)
    assert b.prepare()
    role, binding = next(iter(b._bindings.items()))
    if fault == 'launch-before-arm':
        action = lambda: b.record_launch(role, binding.session_id)
    elif fault == 'foreign-session':
        action = lambda: b.before_turn(role, 'ffffffff-ffff-ffff-ffff-ffffffffffff')
    else:
        b.before_turn(role, binding.session_id)
        if fault == 'duplicate-arm':
            action = lambda: b.before_turn(role, binding.session_id)
        else:
            driver = b._drivers[role]
            driver.session.decide({'op': 'credential_steward', 'event': 'refreshed-captured',
                                   'seq': len(driver.session.events) + 1, 'opens': 0, 'closes': 0})
            action = lambda: b.record_launch(role, binding.session_id)
    with pytest.raises(cw.CustodyRefused):
        action()
    assert b.close()['runner_held']


def test_no_marker_oracle_rejects_deliberately_leaking_repr(tmp_path: Path) -> None:
    f = synthetic(tmp_path)
    # Deliberately leak only into the independent in-memory oracle; its own
    # failure is sanitized and the synthetic bytes never reach a file/log.
    with pytest.raises(AssertionError, match='privacy control refused'):
        no_marker(repr(f.scan.refs._values[0]).encode(), f.scan.refs)
    no_marker(repr(f).encode(), f.scan.refs)


def test_opaque_wrapper_traceback_with_locals_exposes_no_marker(tmp_path: Path) -> None:
    f = synthetic(tmp_path)
    b = bridge(f)
    assert b.prepare()
    run_turns(b)
    b.close()
    rendered = b''
    try:
        raise AssertionError('synthetic diagnostic')
    except AssertionError as error:
        rendered = ''.join(traceback.TracebackException.from_exception(error, capture_locals=True).format()).encode()
    no_marker(rendered, f.scan.refs)


@pytest.mark.parametrize('where', ['prepare', 'cleanup'])
def test_interrupt_attempts_every_owned_cleanup_then_propagates(
    tmp_path: Path, where: str,
) -> None:
    f = synthetic(tmp_path)
    b = bridge(f)
    role = tuple(b._bindings)[1]
    binding = b._bindings[role]
    def interrupted() -> Any:
        raise KeyboardInterrupt
    object.__setattr__(binding, where, interrupted)
    if where == 'prepare':
        with pytest.raises(KeyboardInterrupt):
            b.prepare()
    else:
        assert b.prepare()
        run_turns(b)
        with pytest.raises(KeyboardInterrupt):
            b.close()
    # The second role's callback was invoked too (and deliberately interrupted).
    assert 'cleanup:integrator' in f.calls and 'scan' in f.calls
    assert b.close()['runner_held'] and 'export' not in f.calls


def test_committed_allow_dispatch_variant_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert CASES['qualification_controls'][0]['name'] == 'allow-dispatch'
    def allow(window: va.WindowSession, wave: str, root: Path) -> None:
        window.admit(wave, root)
        window._waves[wave]['state'] = 'DISPATCHED'
        window._waves[wave]['events'].append('DISPATCHED')
    with monkeypatch.context() as patch:
        patch.setattr(va.WindowSession, 'request_dispatch', allow)
        with pytest.raises(pytest.fail.Exception):
            test_opt_in_dispatch_is_held(tmp_path, patch, 'none')


def test_committed_always_release_variant_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert CASES['qualification_controls'][2]['name'] == 'always-release'
    with monkeypatch.context() as patch:
        patch.setattr(cw.StewardBridge, 'close', lambda _self: {
            'status': 'CLEAN', 'runner_held': False, 'exported': True, 'scan_status': 'CLEAN'})
        with pytest.raises(AssertionError):
            test_cleanup_release_is_load_bearing(tmp_path, 'missing')


def test_committed_leaking_renderer_variant_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert CASES['qualification_controls'][1]['name'] == 'leaking-repr'
    with monkeypatch.context() as patch:
        patch.setattr(cs.CredentialSteward, '__repr__', lambda driver: repr(driver.final_vault))
        with pytest.raises(AssertionError, match='privacy control refused'):
            test_all_public_sinks_exclude_synthetic_material(tmp_path, 'none')


@pytest.mark.parametrize('kind', [KeyboardInterrupt, SystemExit], ids=['keyboard-interrupt', 'system-exit'])
def test_preparation_interrupt_diagnostics_exclude_private_adapter_message(tmp_path: Path, kind: Any) -> None:
    f = synthetic(tmp_path)
    b = bridge(f)

    def interrupted() -> Any:
        raise kind(f.scan.refs._values[0])

    object.__setattr__(next(iter(b._bindings.values())), 'prepare', interrupted)
    with pytest.raises(kind) as caught:
        b.prepare()
    rendered = PrivateOutput(''.join(traceback.TracebackException.from_exception(
        caught.value, capture_locals=True).format()).encode())
    no_marker(rendered.data, f.scan.refs)
    assert 'scan' in f.calls and b.close()['runner_held']


def test_logout_latches_window_held_immediately(tmp_path: Path) -> None:
    f = synthetic(tmp_path)
    assert f.source is not None
    receipt = f.window.collect_credential_logout(f.source)
    with pytest.raises(va.AdmissionRefused):
        f.source.require_active()
    f.window.accept_credential_logout(f.source, receipt)
    with pytest.raises(va.AdmissionRefused):
        f.window.accept_credential_logout(f.source, receipt)


def test_private_extra_envelope_is_not_retained_in_error_locals(tmp_path: Path) -> None:
    f = synthetic(tmp_path, admitted=False)
    def invalid(request: dict[str, Any]) -> dict[str, Any]:
        return {**{k: v for k, v in request.items() if k != 'check'}, 'observed_at': NOW,
                'payload': f.facts[cw.LOGIN], 'unexpected': f.scan.refs._values[0]}
    f.collector._callback = invalid
    with pytest.raises(va.AdmissionRefused) as caught:
        f.window.collect(WAVE, cw.LOGIN)
    no_marker(''.join(traceback.TracebackException.from_exception(
        caught.value, capture_locals=True).format()).encode(), f.scan.refs)
    assert not f.collector._issued
