"""Bound operator login metadata and synthetic steward orchestration (#630).

No credential resolver, transfer, reference harvester, executor or host operation
exists here. Real-window dispatch/export/restart remain blocked until separately
approved reference-retention and removed-root absence contracts exist. Trusted
callbacks are explicit test/controller seams, not participant-supplied inputs.
"""
from __future__ import annotations

import copy
import math
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial, wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, TypeVar

from . import credential_steward as cs
from . import remnant_scan
from .backend import Confirmation

if TYPE_CHECKING:
    from .vm_admission import Receipt, WindowSession

LOGIN = 'credential-login'
LOGOUT = 'credential-logout'
BLOCKERS = ('reference-retention-contract-unavailable', 'removed-root-absence-contract-unavailable')
STORAGE = {'kind': 'tmpfs', 'directory_mode': 0o700, 'file_mode': 0o600, 'persistence': 'prevented'}


class CustodyRefused(ValueError):
    """Fixed diagnostics only; supplied values never enter exception text."""


def _require(ok: object, reason: str) -> None:
    if not ok:
        raise CustodyRefused('credential_window: ' + reason)


def validate_plan(data: Mapping[str, object]) -> dict[str, Any]:
    raw = data.get('credential_window')
    _require(type(raw) is dict and set(raw) == {
        'version', 'client', 'account_class', 'source', 'storage', 'stop_on_refresh'}, 'invalid declared policy')
    assert isinstance(raw, dict)
    _require(type(raw['version']) is int and raw['version'] == 1
             and raw['client'] == 'codex' and raw['account_class'] == 'owner-subscription'
             and raw['source'] == 'owner-interactive-login' and raw['stop_on_refresh'] is True,
             'unsupported custody policy')
    _require(type(raw['storage']) is dict and raw['storage'] == STORAGE
             and all(type(raw['storage'].get(key)) is int for key in ('directory_mode', 'file_mode')),
             'private transient storage required')
    try:
        plan = remnant_scan.validate_plan(data)
    except remnant_scan.ScanRefused:
        raise CustodyRefused('credential_window: declared remnant coverage required') from None
    return {'policy': copy.deepcopy(raw), 'waves': plan['waves']}


def _epoch(value: object) -> float:
    _require(type(value) in (int, float), 'invalid operator timestamp')
    try:
        result = float(value)  # type: ignore[arg-type]
    except (OverflowError, ValueError):
        raise CustodyRefused('credential_window: invalid operator timestamp') from None
    _require(math.isfinite(result), 'invalid operator timestamp')
    return result


def operator_payload(check: str, value: object) -> dict[str, Any]:
    """Validate BEFORE receipt serialization; never retain unknown fields."""
    key = 'login_at' if check == LOGIN else 'logout_at'
    _require(check in (LOGIN, LOGOUT) and type(value) is dict
             and set(value) == {'account_class', key}, 'invalid operator login/logout fields')
    assert isinstance(value, dict)
    _require(type(value['account_class']) is str and value['account_class'] == 'owner-subscription',
             'unsupported account class')
    return {'account_class': 'owner-subscription', key: _epoch(value[key])}


@dataclass(frozen=True, repr=False)
class WindowCredentialInput:
    """Registered, redacted per-window capability containing NO secret bytes.

    Constructed by WindowSession only after admission. Its issuing session
    rechecks freshness, binding and identity before each steward operation.
    Copying or constructing a lookalike does not create issuer registration.
    """

    _issuer: WindowSession = field(repr=False)
    _wave: str = field(repr=False)
    _receipt: Receipt = field(repr=False)
    _roles: tuple[str, ...] = field(repr=False)

    def __repr__(self) -> str:
        return '<WindowCredentialInput redacted>'

    def require_active(self) -> None:
        self._issuer.require_credential_input(self)

    def hold(self) -> None:
        self._issuer.hold_credentials()


@dataclass(frozen=True, repr=False)
class RoleBinding:
    """Explicit trusted per-role adapters; never read a source implicitly."""

    session_id: str = field(repr=False)
    prepare: Callable[[], cs.CredentialSteward] = field(repr=False)
    backend: cs.StewardBackend = field(repr=False)
    handle: object = field(repr=False)
    cleanup: Callable[[], Confirmation] = field(repr=False)

    def __repr__(self) -> str:
        return '<RoleBinding redacted>'


@dataclass(frozen=True, repr=False)
class ScanObservation:
    result: remnant_scan.ScanResult = field(repr=False)
    roots: Mapping[str, Path] = field(repr=False)
    generation: object = field(repr=False)

    def __repr__(self) -> str:
        return '<ScanObservation redacted>'


@dataclass(frozen=True, repr=False)
class CloseActions:
    freeze_census: Callable[[], Confirmation] = field(repr=False)
    stop_writers: Callable[[], Confirmation] = field(repr=False)
    logout: Callable[[], object] = field(repr=False)
    remove_copies: Callable[[], Confirmation] = field(repr=False)
    scan: Callable[[], ScanObservation] = field(repr=False)
    export: Callable[[], object] = field(repr=False)

    def __repr__(self) -> str:
        return '<CloseActions redacted>'


def _call(action: Callable[[], Any]) -> tuple[bool, Any]:
    try:
        return True, action()
    except Exception:  # noqa: BLE001 - adapters can carry private diagnostics
        return False, None


_P = ParamSpec('_P')
_R = TypeVar('_R')


def _serialized(method: Callable[Concatenate[StewardBridge, _P], _R]) -> Callable[Concatenate[StewardBridge, _P], _R]:
    @wraps(method)
    def locked(self: StewardBridge, /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with self._lock:
            return method(self, *args, **kwargs)
    return locked


class StewardBridge:
    """Metadata/driver rehearsal, never a model launcher or release authority.

    The existing #624 adapter owns actual role delivery. All adapters are
    registered before preparation, so partial failure cannot lose cleanup.
    No source/reference bytes are accepted, read or returned by this bridge.
    """

    def __repr__(self) -> str:
        return '<StewardBridge redacted>'

    def __init__(self, source: WindowCredentialInput, bindings: Mapping[str, RoleBinding],
                 actions: CloseActions) -> None:
        _require(isinstance(source, WindowCredentialInput), 'registered window input required')
        _require(isinstance(actions, CloseActions), 'complete close actions required')
        source.require_active()
        _require(set(bindings) == set(source._roles) and all(isinstance(v, RoleBinding) for v in bindings.values()),
                 'complete role bindings required')
        _require(all(type(v.session_id) is str and re.fullmatch(
                     r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', v.session_id)
                     for v in bindings.values()), 'invalid role session')
        _require(len({v.session_id for v in bindings.values()}) == len(bindings), 'distinct role sessions required')
        self._source, self._bindings, self._actions = source, dict(bindings), actions
        self._lock = threading.RLock()
        self._drivers: dict[str, cs.CredentialSteward] = {}
        self._launches = dict.fromkeys(bindings, 0)
        self._pending: set[str] = set()
        self._prepared = False
        self._closed: dict[str, Any] | None = None
        self._failed = False

    def _events_available(self, driver: cs.CredentialSteward) -> bool:
        try:
            events = driver.session.events
            return (not driver.session.channel_unavailable and bool(events)
                    and all(type(row) is dict and row.get('event') in cs.EVENTS
                            and type(row.get('seq')) is int and row['seq'] == index
                            for index, row in enumerate(events, 1))
                    and not any(row['event'] in ('error', 'withdrawn-at-deadline', 'refreshed-captured', 'stopped')
                                for row in events)
                    and events[-1]['event'] == 'armed')
        except Exception:  # noqa: BLE001 - no raw driver diagnostics
            return False

    @_serialized
    def prepare(self) -> bool:
        _require(not self._prepared and self._closed is None, 'preparation is single use')
        self._source.require_active()
        self._prepared = True
        for role, binding in self._bindings.items():
            try:
                ok, driver = _call(binding.prepare)
            except (KeyboardInterrupt, SystemExit) as interruption:
                self._failed = True
                self.close()
                if isinstance(interruption, KeyboardInterrupt):
                    raise KeyboardInterrupt from None
                raise SystemExit(1) from None
            # Retain even a partially started driver when the adapter returns it.
            if isinstance(driver, cs.CredentialSteward):
                self._drivers[role] = driver
            if not ok or role not in self._drivers or not self._events_available(driver):
                self._failed = True
                self.close()
                return False
        return True

    @_serialized
    def before_turn(self, role: str, session_id: str) -> None:
        _require(self._prepared and self._closed is None and not self._failed, 'steward preparation unavailable')
        self._source.require_active()
        if (role not in self._bindings or self._bindings[role].session_id != session_id
                or role in self._pending or role not in self._drivers):
            self._failed = True
            self._source.hold()
            raise CustodyRefused('credential_window: stale or duplicate role turn')
        driver = self._drivers[role]
        if self._launches[role]:
            binding = self._bindings[role]
            ok, _ = _call(lambda: driver.restore_for_turn(binding.backend, binding.handle))
            if not ok:
                self._failed = True
        if self._failed or not self._events_available(driver):
            self._failed = True
            self._source.hold()
            raise CustodyRefused('credential_window: steward arm unavailable')
        if sum(row['event'] == 'armed' for row in driver.session.events) != self._launches[role] + 1:
            self._failed = True
            self._source.hold()
            raise CustodyRefused('credential_window: steward arm population differs')
        self._pending.add(role)

    @_serialized
    def record_launch(self, role: str, session_id: str) -> None:
        """Record a trusted controller launch, never execute one or infer spend."""
        self._source.require_active()
        if (self._closed is not None or self._failed or role not in self._pending
                or self._bindings[role].session_id != session_id
                or not self._events_available(self._drivers[role])):
            self._failed = True
            self._source.hold()
            raise CustodyRefused('credential_window: launch lacks a bound arm')
        self._launches[role] += 1
        self._pending.remove(role)

    @_serialized
    def close(self) -> dict[str, Any]:
        if self._closed is not None:
            return copy.deepcopy(self._closed)
        self._source.hold()  # Stop every later role/resume before any teardown.
        interruptions: list[type[BaseException]] = []

        def call(action: Callable[[], Any]) -> tuple[bool, Any]:
            try:
                return _call(action)
            except (KeyboardInterrupt, SystemExit) as interruption:
                interruptions.append(type(interruption))
                return False, None

        actions = self._actions
        ok, value = call(actions.freeze_census)
        frozen = ok and value is Confirmation.CONFIRMED
        held = 0
        refreshed = 0
        for role, driver in self._drivers.items():
            binding = self._bindings[role]
            stopped, _ = call(partial(driver.stop, binding.backend, binding.handle))
            valid, record = call(driver.record)
            if valid and type(record) is dict and record.get('status') == 'refreshed':
                refreshed += 1
            # Reconcile to actual controller launches, not requested arm count.
            if (stopped and valid and type(record) is dict and record.get('status') == 'held'
                    and type(record.get('arms')) is int and record['arms'] == self._launches[role]
                    and type(record.get('expected_arms')) is int
                    and record.get('expected_arms') == self._launches[role]
                    and not driver.session.channel_unavailable):
                held += 1
        stopped, value = call(actions.stop_writers)
        writers = stopped and value is Confirmation.CONFIRMED
        ok, receipt = call(actions.logout)
        logout = False
        if ok:
            logout, _ = call(lambda: self._source._issuer.accept_credential_logout(self._source, receipt))
        ok, value = call(actions.remove_copies)
        removed = ok and value is Confirmation.CONFIRMED
        cleaned = 0
        for binding in self._bindings.values():
            ok, value = call(binding.cleanup)
            cleaned += int(ok and value is Confirmation.CONFIRMED)
        ok, scan = call(actions.scan)
        scan_status = 'UNKNOWN'
        if ok and isinstance(scan, ScanObservation):
            matched, value = call(lambda: scan.result.matches(
                self._source._issuer.credential_declaration(), scan.roots, scan.generation))
            if matched and value is True and scan.result.status in ('CLEAN', 'NOT_CLEAN', 'UNKNOWN'):
                scan_status = scan.result.status
        complete = (frozen and writers and logout and removed and cleaned == len(self._bindings)
                    and held == len(self._bindings) and not self._pending and not self._failed)
        # No enabling adapter for the two unapproved contracts. Even synthetic
        # CLEAN is diagnostic only; no exporter/restart callback can run here.
        self._closed = {'version': 1, 'status': 'NOT_CLEAN' if scan_status == 'NOT_CLEAN' else 'UNKNOWN',
                        'runner_held': True, 'exported': False, 'scan_status': scan_status,
                        'lifecycle_complete': bool(complete), 'roles': len(self._bindings),
                        'credential_status': 'refreshed' if refreshed else 'held' if held == len(self._bindings) else 'unknown',
                        'stewards_held': held, 'owned_cleanup_confirmed': cleaned,
                        'freeze_confirmed': bool(frozen), 'writers_stopped': bool(writers),
                        'logout_recorded': bool(logout), 'copies_removed': bool(removed),
                        'blockers': list(BLOCKERS)}
        if interruptions:
            if KeyboardInterrupt in interruptions:
                raise KeyboardInterrupt from None
            raise SystemExit(1) from None
        return copy.deepcopy(self._closed)
