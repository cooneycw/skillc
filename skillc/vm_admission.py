"""Operator-receipt binding and admission bookkeeping, not host operations.

The explicit collector CALLBACK is the trust seam. Authenticating its authority
is a later trusted-adapter responsibility: neither an authority string nor a
matching digest is physical proof. Participant JSON is never a receipt. These
in-process objects do not defend against malicious Python in the controller.

No executor or automatic host observer exists here. CLOSED covers admission
lifecycle only; credential cleanup, host teardown and runner restart belong to
later slices. Calibration's existing gate is the sole approval path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, TypeVar

from . import vm_identity
from .completion import CompletionDeadline, CompletionUnavailable

if TYPE_CHECKING:
    from .calibration import CalibrationDeclaration

CHECKS = ('verified-key', 'time-sync', 'firewall-isolation', 'runner-drain')
POLICY_KEYS = {'max_receipt_age_seconds', 'max_clock_sample_age_seconds', 'max_clock_offset_seconds',
               'collection_timeout_seconds', 'firewall_policy_digest', 'allowed_workloads'}
BINDING_KEYS = {'collection_id', 'window_id', 'wave_id', 'vm_binding_digest', 'declaration_digest'}
MAX_WAVES = 1000
MAX_RECEIPTS = 10_000
MAX_RECEIPT_BYTES = 64 * 1024


class AdmissionRefused(ValueError):
    """Admission cannot be established; this is not a task failure."""


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise AdmissionRefused('operator_admission: ' + reason)


def _object(value: object, keys: set[str], reason: str) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == keys, reason)
    assert isinstance(value, dict)
    return value


def _number(value: object) -> float:
    _require(type(value) in (int, float), 'non-numeric observation or policy')
    try:
        number = float(value)  # type: ignore[arg-type]
    except (ValueError, OverflowError) as exc:
        raise AdmissionRefused('operator_admission: invalid numeric observation') from exc
    _require(math.isfinite(number), 'non-finite observation or policy')
    return number


def _names(value: object, *, nonempty: bool = False) -> list[str]:
    _require(isinstance(value, list) and (not nonempty or bool(value)), 'invalid name population')
    assert isinstance(value, list)
    _require(all(isinstance(x, str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,128}', x) for x in value),
             'invalid logical identity')
    _require(len(value) <= MAX_WAVES and len(value) == len(set(value)), 'invalid name population')
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise AdmissionRefused('operator_admission: unreadable receipt') from exc


def _digest(value: object) -> str:
    return 'sha256:' + hashlib.sha256(_canonical(value)).hexdigest()


def validate(data: Mapping[str, object]) -> dict[str, Any]:
    """All operational policy values are explicit declaration inputs."""
    _require(data.get('kind') == 'calibration-declaration', 'unsupported declaration kind')
    _require('execution_environment' in data, 'VM execution_environment is required')
    try:
        vm_identity.validate(data['execution_environment'])
    except vm_identity.IdentityRefused as exc:
        raise AdmissionRefused('operator_admission: invalid VM environment') from exc
    raw = _object(data.get('operator_admission'), {'version', 'planned_waves', 'policy'}, 'invalid policy fields')
    _require(type(raw['version']) is int and raw['version'] == 1, 'unsupported policy version')
    _names(raw['planned_waves'], nonempty=True)
    policy = _object(raw['policy'], POLICY_KEYS, 'incomplete or unknown policy values')
    for name in POLICY_KEYS - {'firewall_policy_digest', 'allowed_workloads'}:
        value = _number(policy[name])
        _require(value >= 0 and (name != 'collection_timeout_seconds' or value > 0), 'invalid policy bound')
    _require(isinstance(policy['firewall_policy_digest'], str)
             and re.fullmatch(r'sha256:[0-9a-f]{64}', policy['firewall_policy_digest']), 'invalid firewall digest')
    _names(policy['allowed_workloads'])
    return copy.deepcopy(raw)


@dataclass(frozen=True)
class Receipt:
    """Canonical immutable bytes, accepted only from the issuing registry."""

    sequence: int
    data: bytes


class OperatorCollector:
    """Trusted injected callback only; never turns participant JSON into authority."""

    def __init__(self, authority: str, callback: Callable[[dict[str, Any]], object]) -> None:
        _names([authority], nonempty=True)
        self.authority = authority
        self._callback = callback
        self._issued: dict[int, Receipt] = {}

    def collect(self, request: Mapping[str, str]) -> Receipt:
        _require(len(self._issued) < MAX_RECEIPTS, 'collection population exceeded')
        try:
            response = self._callback(dict(request))
        except Exception:  # noqa: BLE001 - injected adapter failure must become unavailable evidence
            # An adapter error can contain a private path, identity or payload.
            raise AdmissionRefused('operator_admission: operator observation unavailable') from None
        raw = _object(response, BINDING_KEYS | {'observed_at', 'payload'}, 'incomplete operator observation')
        sequence = len(self._issued) + 1
        data = _canonical({**raw, 'version': 1, 'check': request['check'],
                           'authority': self.authority, 'sequence': sequence})
        _require(len(data) <= MAX_RECEIPT_BYTES, 'operator observation exceeds bound')
        receipt = Receipt(sequence, data)
        self._issued[sequence] = receipt
        return receipt

    def owns(self, receipt: object) -> bool:
        return isinstance(receipt, Receipt) and self._issued.get(receipt.sequence) is receipt


@dataclass(frozen=True)
class ApprovalInput:
    session: WindowSession
    wave_id: str


_P = ParamSpec('_P')
_R = TypeVar('_R')


def _serialized(method: Callable[Concatenate[WindowSession, _P], _R]) -> Callable[Concatenate[WindowSession, _P], _R]:
    @wraps(method)
    def locked(self: WindowSession, /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with self._lock:
            return method(self, *args, **kwargs)
    return locked


class WindowSession:
    """Record every planned wave; unknown admission always remains a nonstart.

    Clocks and collector are required injected inputs, with no live defaults.
    A collection timeout refuses late results; the adapter must itself bound
    blocking IO. This pure synchronous API cannot preempt a hung callback.
    """

    def __init__(self, declaration: CalibrationDeclaration, *, collector: OperatorCollector,
                 vm_observation: vm_identity.Observation, wall_clock: Callable[[], float],
                 monotonic_clock: Callable[[], float]) -> None:
        from . import calibration

        _require(isinstance(collector, OperatorCollector), 'explicit operator collector required')
        self._lock = threading.RLock()
        self._declaration = copy.deepcopy(declaration)
        raw = validate(self._declaration.data)
        self._policy = raw['policy']
        self._collector = collector
        self._observation = vm_observation
        self._wall_clock, self._monotonic = wall_clock, monotonic_clock
        self._digest = calibration.declaration_digest(self._declaration.data)
        self._vm = vm_identity.verify(self._declaration.data['execution_environment'], vm_observation)
        self._collection_id = secrets.token_hex(16)
        self._waves: dict[str, dict[str, Any]] = {wave: {'state': 'PLANNED', 'reason': 'host-observation-absent',
                             'receipts': {}, 'events': ['PLANNED']} for wave in raw['planned_waves']}
        self._deadlines: dict[str, CompletionDeadline] = {}
        self._last_sequence = 0

    def _row(self, wave: str) -> dict[str, Any]:
        _require(wave in self._waves, 'unplanned wave')
        return self._waves[wave]

    def _nonstart(self, wave: str, reason: str) -> None:
        row = self._row(wave)
        if row['state'] not in ('DISPATCHED', 'CLOSED', 'NONSTART'):
            row['state'], row['reason'] = 'NONSTART', reason
            row['events'].append('NONSTART')

    def _deadline(self, wave: str) -> None:
        try:
            if wave not in self._deadlines:
                self._deadlines[wave] = CompletionDeadline.after(
                    self._policy['collection_timeout_seconds'], self._monotonic)
            self._deadlines[wave].remaining(self._policy['collection_timeout_seconds'])
        except CompletionUnavailable as exc:
            raise AdmissionRefused('operator_admission: collection deadline unavailable') from exc

    def _binding(self, wave: str) -> dict[str, str]:
        return {'collection_id': self._collection_id, 'window_id': self._vm['window']['id'],
                'wave_id': wave, 'vm_binding_digest': _digest(self._vm), 'declaration_digest': self._digest}

    @_serialized
    def collect(self, wave: str, check: str) -> Receipt:
        row = self._row(wave)
        try:
            _require(row['state'] in ('PLANNED', 'COLLECTING'), 'wave collection is closed')
            _require(check in CHECKS, 'unknown host check')
            self._deadline(wave)
            receipt = self._collector.collect({**self._binding(wave), 'check': check})
            self._deadline(wave)
            self.record(wave, receipt)
            return receipt
        except AdmissionRefused:
            self._nonstart(wave, 'collection-unavailable')
            raise

    @_serialized
    def record(self, wave: str, receipt: object) -> None:
        """Only receipts actually issued by this configured collector qualify."""
        row = self._row(wave)
        try:
            _require(row['state'] in ('PLANNED', 'COLLECTING'), 'wave collection is closed')
            _require(self._collector.owns(receipt), 'receipt lacks configured collector provenance')
            assert isinstance(receipt, Receipt)
            raw = json.loads(receipt.data)
            _require(receipt.sequence > self._last_sequence, 'receipt sequence replay')
            _require(all(raw[k] == v for k, v in self._binding(wave).items()), 'receipt binding differs')
            _require(raw['check'] in CHECKS and raw['check'] not in row['receipts'], 'duplicate or unknown check')
            self._deadline(wave)
            row['receipts'][raw['check']] = receipt
            row['state'], row['reason'] = 'COLLECTING', 'host-checks-incomplete'
            row['events'].append('COLLECTING')
            self._last_sequence = receipt.sequence
        except AdmissionRefused:
            self._nonstart(wave, 'receipt-provenance-or-binding-unavailable')
            raise

    @_serialized
    def approval_input(self, wave: str) -> ApprovalInput:
        self._row(wave)
        return ApprovalInput(self, wave)

    def _check(self, check: str, payload: object, now: float) -> None:
        if check == 'verified-key':
            p = _object(payload, {'verified', 'fingerprint'}, 'incomplete key verification')
            _require(p['verified'] is True and p['fingerprint'] == self._vm['vm']['host_key_fingerprint'],
                     'key verification unavailable')
        elif check == 'time-sync':
            p = _object(payload, {'synchronized', 'packet_count', 'restarted', 'fresh_exchange',
                                  'offset_seconds', 'sampled_at'}, 'incomplete time observation')
            _require(p['synchronized'] is True and type(p['packet_count']) is int and p['packet_count'] > 0
                     and type(p['restarted']) is bool and p['fresh_exchange'] is True, 'fresh time sync unavailable')
            _require(abs(_number(p['offset_seconds'])) <= self._policy['max_clock_offset_seconds'],
                     'clock offset exceeds declared policy')
            age = now - _number(p['sampled_at'])
            _require(0 <= age <= self._policy['max_clock_sample_age_seconds'], 'clock sample is stale or future')
        elif check == 'firewall-isolation':
            p = _object(payload, {'policy_digest', 'firewall_complete', 'isolation_complete', 'management_allowed',
                                  'provider_egress', 'forbidden_egress_blocked', 'workloads'}, 'incomplete firewall observation')
            _require(p['policy_digest'] == self._policy['firewall_policy_digest']
                     and all(p[k] is True for k in ('firewall_complete', 'isolation_complete', 'management_allowed',
                                                  'provider_egress', 'forbidden_egress_blocked')),
                     'firewall or isolation evidence unavailable')
            _require(set(_names(p['workloads'])) <= set(self._policy['allowed_workloads']), 'unexpected workload')
        elif check == 'runner-drain':
            p = _object(payload, {'timer_state', 'service_state', 'service_substate', 'jobs', 'processes', 'complete'},
                        'incomplete runner observation')
            _require(p['complete'] is True and p['timer_state'] == p['service_state'] == 'inactive'
                     and p['service_substate'] == 'dead' and _names(p['jobs']) == [] and _names(p['processes']) == [],
                     'runner not drained')

    @_serialized
    def require_ready(self, declaration: CalibrationDeclaration, observed: vm_identity.Observation | None,
                      wave: str) -> None:
        """Existing calibration approval calls this, never an alternate approval."""
        from . import calibration

        row = self._row(wave)
        try:
            _require(row['state'] in ('PLANNED', 'COLLECTING', 'ADMITTED'), 'wave is terminal or dispatched')
            validate(declaration.data)
            _require(calibration.declaration_digest(declaration.data) == self._digest, 'approval binding differs')
            record = vm_identity.verify(declaration.data['execution_environment'], observed)
            _require(record == self._vm, 'VM binding differs')
            self._deadline(wave)
            try:
                now = _number(self._wall_clock())
            except Exception:  # noqa: BLE001 - clock adapter failure cannot permit admission
                raise AdmissionRefused('operator_admission: wall clock unavailable') from None
            start, end = (datetime.fromisoformat(self._vm['window'][k]).timestamp() for k in ('starts_at', 'ends_at'))
            _require(start <= now < end, 'outside declared window')
            _require(set(row['receipts']) == set(CHECKS), 'host observation absent or incomplete')
            for check, receipt in row['receipts'].items():
                _require(self._collector.owns(receipt), 'receipt provenance lost')
                raw = json.loads(receipt.data)
                age = now - _number(raw['observed_at'])
                _require(start <= raw['observed_at'] < end and 0 <= age <= self._policy['max_receipt_age_seconds'],
                         'receipt stale, future or outside window')
                self._check(check, raw['payload'], now)
        except (AdmissionRefused, vm_identity.IdentityRefused):
            self._nonstart(wave, 'admission-unverified')
            raise

    @_serialized
    def admit(self, wave: str, root: Path) -> None:
        from . import calibration

        self._row(wave)
        try:
            calibration.require_approved(self._declaration, root, vm_observation=self._observation,
                                         operator_admission=self.approval_input(wave))
        except (calibration.DeclarationRefused, AdmissionRefused):
            self._nonstart(wave, 'approval-or-admission-unverified')
            raise
        row = self._row(wave)
        row['state'], row['reason'] = 'ADMITTED', None
        if not row['events'] or row['events'][-1] != 'ADMITTED':
            row['events'].append('ADMITTED')

    @_serialized
    def request_dispatch(self, wave: str, root: Path) -> None:
        """Validate again at dispatch; no work is executed by this transition."""
        self.admit(wave, root)
        row = self._row(wave)
        row['state'] = 'DISPATCHED'
        row['events'].append('DISPATCHED')

    @_serialized
    def close(self, wave: str) -> None:
        row = self._row(wave)
        _require(row['state'] in ('DISPATCHED', 'NONSTART'), 'invalid close transition')
        row['state'] = 'CLOSED'
        row['events'].append('CLOSED')

    @_serialized
    def report(self) -> dict[str, Any]:
        """Every planned wave stays UNKNOWN as a task; admission is not success."""
        rows = []
        for wave, row in self._waves.items():
            dispatched = 'DISPATCHED' in row['events']
            rows.append({'wave_id': wave, 'state': row['state'], 'task_status': 'UNKNOWN',
                         'nonstart': not dispatched, 'dispatch_recorded': dispatched,
                         'reason': row['reason'], 'events': list(row['events']),
                         'receipts': [{'check': check, 'sequence': receipt.sequence,
                                       'sha256': 'sha256:' + hashlib.sha256(receipt.data).hexdigest()}
                                      for check, receipt in sorted(row['receipts'].items())]})
        return {'version': 1, 'scope': 'operator-receipt-binding-and-admission-only',
                'authority': self._collector.authority, 'declaration_digest': self._digest,
                'vm_binding_digest': _digest(self._vm), 'window_id': self._vm['window']['id'], 'waves': rows}
