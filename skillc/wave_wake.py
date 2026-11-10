"""Arm-neutral controller resume turns (#622); no message interpretation.

The driver observes only opaque file/ref digests, records attempts separately
from executions, and never certifies task success. Native thread wake is deferred.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import controller_turns as ct
from .backend import BackendUnavailable, Confirmation, ExecuteResult
from .completion import CompletionUnavailable, number
from .wave_attachment import WAVE_ROOT
from .wave_snapshot import SnapshotUnavailable

MAX_FILES = 4096
MAX_BYTES = 4 * 1024 * 1024
MAX_ROLES = 64
MAX_DECLARATION = 1024 * 1024


class WakeRefused(ValueError):
    """An incomplete or misbound controller input cannot authorize a turn."""


def _role(value: object) -> str:
    if type(value) is not str or re.fullmatch(r'[a-z][a-z0-9-]{0,39}', value) is None:
        raise WakeRefused('logical wake role required')
    return value


def _roles(value: object) -> tuple[str, ...]:
    if type(value) not in (tuple, list):
        raise WakeRefused('bounded nonempty wake population required')
    assert isinstance(value, (tuple, list))
    if not 1 <= len(value) <= MAX_ROLES:
        raise WakeRefused('bounded nonempty wake population required')
    names = tuple(_role(name) for name in value)
    if len(set(names)) != len(names):
        raise WakeRefused('unique wake population required')
    return names


def _digest(value: object) -> str:
    if type(value) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}', value) is None:
        raise WakeRefused('complete wake digest required')
    return value


def _session(value: object) -> str:
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value) is None:
        raise WakeRefused('canonical wake session required')
    return value


def _nonce(value: object) -> str:
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{32}', value) is None:
        raise WakeRefused('controller wake nonce required')
    return value


def _time(value: object) -> float:
    result = number(value)
    if result < 0:
        raise WakeRefused('nonnegative wake time required')
    return result


@dataclass(frozen=True)
class Revision:
    files: str
    refs: str

    def __post_init__(self) -> None:
        for value in (self.files, self.refs):
            _digest(value)

    @property
    def identity(self) -> str:
        return 'sha256:' + hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class WakePolicy:
    literal: str
    poll_seconds: float
    min_spacing_seconds: float
    max_pokes: int
    after_failure: str = 'stop'
    after_cap: str = 'stop'
    max_files: int = 4096
    max_bytes: int = 4 * 1024 * 1024
    on_observation_failure: str = 'retry-until-deadline'
    after_unconfirmed: str = 'wait-for-change-or-deadline'

    def __post_init__(self) -> None:
        ct.parse_turns({'version': 1, 'by_case': {'role': [{'text': self.literal}]}}, ['role'])
        try:
            self.literal.encode('utf-8')
        except UnicodeError:
            raise WakeRefused('encodable wake literal required') from None
        if number(self.poll_seconds) <= 0 or number(self.min_spacing_seconds) < 0:
            raise ValueError('poll interval must be positive; spacing must be nonnegative')
        for key in ('max_pokes', 'max_files', 'max_bytes'):
            value = getattr(self, key)
            if type(value) is not int or value < (0 if key == 'max_pokes' else 1):
                raise ValueError('invalid wake count or observation bound')
        if (self.max_pokes > 64 or self.after_failure != 'stop' or self.after_cap != 'stop'
                or self.on_observation_failure != 'retry-until-deadline'):
            raise ValueError('unsupported wake cap/failure policy')
        if self.after_unconfirmed != 'wait-for-change-or-deadline':
            raise ValueError('unsupported unconfirmed-poke policy')
        if self.max_files > MAX_FILES or self.max_bytes > MAX_BYTES:
            raise WakeRefused('wake observation exceeds technical bounds')

    @property
    def digest(self) -> str:
        return 'sha256:' + hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Poke:
    role: str
    session: str
    revision: str
    nonce: str

    def __post_init__(self) -> None:
        _role(self.role)
        _session(self.session)
        _digest(self.revision)
        _nonce(self.nonce)


def parse_revision(value: object) -> Revision:
    if type(value) is not dict or set(value) != {'files', 'refs'}:
        raise WakeRefused('closed wake revision required')
    return Revision(value['files'], value['refs'])


def parse_poke(value: object) -> Poke:
    if type(value) is not dict or set(value) != {'role', 'session', 'revision', 'nonce'}:
        raise WakeRefused('closed controller poke required')
    return Poke(**value)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise WakeRefused('duplicate wake JSON member')
        result[key] = value
    return result


def parse_policy(value: object) -> WakePolicy:
    """Closed declaration field; every behavior is explicit, including defaults."""
    keys = set(WakePolicy.__dataclass_fields__)
    if (type(value) is not dict or set(value) != keys | {'version'}
            or type(value['version']) is not int or value['version'] != 1):
        raise WakeRefused('closed version-1 controller_wake object required')
    try:
        return WakePolicy(**{key: value[key] for key in keys})
    except ValueError:
        raise WakeRefused('invalid controller_wake policy') from None


def _canonical(value: object) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError):
        raise WakeRefused('JSON wake declaration required') from None
    if len(raw) > MAX_DECLARATION:
        raise WakeRefused('wake declaration exceeds technical bound')
    return raw


@dataclass(frozen=True)
class WakeBinding:
    """Whole declaration bytes and the trusted caller's independently approved hash.

    Consistency only: this is not an approval issuer or live launch authority.
    The caller owns its declaration schema beyond roles/controller_wake.
    """

    declaration: bytes
    approved_digest: str

    def verify(self) -> tuple[tuple[str, ...], WakePolicy]:
        _digest(self.approved_digest)
        if type(self.declaration) is not bytes or not 0 < len(self.declaration) <= MAX_DECLARATION:
            raise WakeRefused('bounded bound declaration required')
        if 'sha256:' + hashlib.sha256(self.declaration).hexdigest() != self.approved_digest:
            raise WakeRefused('wake declaration differs from caller approval')
        try:
            value = json.loads(self.declaration, object_pairs_hook=_pairs)
        except (ValueError, RecursionError):
            raise WakeRefused('bound wake declaration unavailable') from None
        if type(value) is not dict or _canonical(value) != self.declaration:
            raise WakeRefused('canonical whole wake declaration required')
        return _roles(value.get('roles')), parse_policy(value.get('controller_wake'))


def bind_declaration(value: object, approved_digest: object) -> WakeBinding:
    """Verify a projection against a hash held by the trusted approving caller."""
    bound = WakeBinding(_canonical(value), _digest(approved_digest))
    bound.verify()
    return bound


def parse_binding(value: object) -> WakeBinding:
    """Validate the trusted caller's in-memory binding envelope, not a checkpoint."""
    if type(value) is not dict or set(value) != {'declaration', 'approved_digest'}:
        raise WakeRefused('closed caller wake binding required')
    bound = WakeBinding(**value)
    bound.verify()
    return bound


@dataclass
class Slot:
    phase: str = 'running'
    session: str | None = None
    watermark: str | None = None
    pokes: int = 0
    last_attempt: float | None = None
    pending: Poke | None = None
    end: str | None = None
    active_nonce: str | None = None
    compatible: bool = True


@dataclass
class WakeState:
    """Pure transition engine; caller supplies controller observations, never mail."""

    policy: WakePolicy
    roles: tuple[str, ...]
    slots: dict[str, Slot] = field(init=False)
    events: list[dict[str, Any]] = field(default_factory=list)
    journal: Callable[[Mapping[str, Any]], None] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.policy) is not WakePolicy:
            raise WakeRefused('validated wake policy required')
        parse_policy({'version': 1, **asdict(self.policy)})
        self.roles = _roles(self.roles)
        self.slots = {role: Slot() for role in self.roles}

    def target(self, role: object, now: object) -> Slot:
        """Refuse an invalid target before any lookup or state mutation."""
        tick = _time(now)
        try:
            name = _role(role)
            if name not in self.slots:
                raise WakeRefused('undeclared wake role')
        except WakeRefused:
            self.record('poke-refused', '-', tick, reason='undeclared-role', nonce=None)
            raise
        return self.slots[name]

    def record(self, event: str, role: str, now: float, **fields: Any) -> None:
        self.events.append({'seq': len(self.events) + 1, 'event': event, 'role': role,
                            'time': _time(now), **fields})
        if self.journal is not None:
            self.journal(self.events[-1])

    def ended(self, role: str, session: str | None, result: ExecuteResult,
              revision: Revision | None, now: float) -> None:
        slot = self.target(role, now)
        if (type(result) is not ExecuteResult or type(result.reason) is not str
                or not result.reason or (result.exit_code is not None
                and (type(result.exit_code) is not int or not -(1 << 31) <= result.exit_code < (1 << 31)))):
            raise WakeRefused('complete turn result required')
        if revision is not None and type(revision) is not Revision:
            raise WakeRefused('observed wake revision required')
        try:
            if not isinstance(session, str):
                raise ct.TurnsRefused('session not observed')
            ct.resume_argv('codex', ('controller',), session, self.policy.literal)
        except ct.TurnsRefused:
            session = None
        slot.pending = None
        if slot.session is None:
            slot.session = session
        elif slot.session != session:
            slot.compatible = False
        slot.watermark = revision.identity if revision is not None else None
        self.record('turn-ended', role, now, reason=result.reason, exit_code=result.exit_code,
                    session=session, binding_session=slot.session,
                    revision=slot.watermark, nonce=slot.active_nonce)
        slot.active_nonce = None
        reason = None
        if result.reason != 'exited' or result.exit_code != 0:
            reason = 'turn-' + result.reason if result.reason != 'exited' else 'nonzero-exit'
        elif not slot.compatible:
            reason = 'session-incompatible'
        elif session is None:
            reason = 'session-unavailable'
        elif slot.pokes >= self.policy.max_pokes:
            reason = 'max-pokes'
        slot.phase = 'terminal' if reason else 'idle'
        slot.end = reason
        if reason:
            self.record('role-ended', role, now, reason=reason)

    def offer(self, role: str, revision: Revision, now: float) -> Poke | None:
        slot = self.target(role, now)
        now = _time(now)
        if type(revision) is not Revision:
            raise WakeRefused('observed wake revision required')
        if (slot.phase != 'idle' or slot.session is None or slot.watermark is None
                or slot.watermark == revision.identity or slot.pending is not None):
            return None
        if slot.last_attempt is not None and now - slot.last_attempt < self.policy.min_spacing_seconds:
            return None
        if slot.pokes >= self.policy.max_pokes:
            slot.phase, slot.end = 'terminal', 'max-pokes'
            self.record('role-ended', role, now, reason='max-pokes')
            return None
        poke = Poke(role, slot.session, revision.identity, secrets.token_hex(16))
        slot.pending = poke
        return poke

    def dispatch(self, poke: Poke, revision: Revision, *, current_role: str,
                 current_session: str | None, idle: bool | None, live: bool | None, now: float) -> bool:
        _time(now)
        if type(poke) is not Poke or type(revision) is not Revision:
            self.record('poke-refused', '-', now, reason='invalid-poke-or-revision', nonce=None)
            return False
        slot = self.slots.get(poke.role)
        reason = None
        if slot is None or slot.pending != poke or current_role != poke.role:
            reason = 'wrong-role-or-token'
        elif current_session != poke.session or slot.session != poke.session:
            reason = 'stale-session'
        elif idle is not True or slot.phase != 'idle':
            reason = 'not-confirmed-idle'
        elif live is not True:
            reason = 'not-confirmed-live'
        elif revision.identity != poke.revision:
            reason = 'stale-revision'
        if reason:
            self.record('poke-refused', poke.role, now, reason=reason, nonce=poke.nonce)
            if slot is not None and slot.pending == poke:
                slot.pending = None
            return False
        assert slot is not None
        slot.pending = None
        slot.watermark, slot.last_attempt = poke.revision, _time(now)
        slot.pokes += 1
        slot.phase = 'running'
        slot.active_nonce = poke.nonce
        self.record('poke-attempt', poke.role, now, revision=poke.revision, session=poke.session,
                    nonce=poke.nonce, poke=slot.pokes)
        return True

    def suppressed(self, poke: Poke, now: float) -> None:
        # Attempt is not receipt. Consuming the revision prevents repeated
        # attempts on unchanged state, but suppressing it cannot complete a role.
        _time(now)
        if type(poke) is not Poke:
            raise WakeRefused('controller poke required')
        slot = self.target(poke.role, now)
        if slot.phase != 'running' or slot.active_nonce != poke.nonce:
            self.record('poke-refused', poke.role, now, reason='inactive-poke', nonce=poke.nonce)
            raise WakeRefused('only an active poke can be suppressed')
        self.slots[poke.role].phase = 'idle'
        self.slots[poke.role].active_nonce = None
        self.record('poke-unconfirmed', poke.role, now, nonce=poke.nonce)

    def report(self, outcome: str) -> dict[str, Any]:
        results = {e['nonce']: e for e in self.events if e['event'] == 'turn-ended' and e['nonce'] is not None}
        refusals = {(e['role'], e['nonce']): e for e in self.events if e['event'] == 'poke-refused'}
        pokes = [{**event, 'result': results.get(event['nonce']),
                  'refusal': refusals.get((event['role'], event['nonce']))}
                 for event in self.events if event['event'] == 'poke-attempt']
        return {'version': 1, 'outcome': outcome, 'policy_digest': self.policy.digest,
                'poke_count': sum(slot.pokes for slot in self.slots.values()),
                'poke_counts': [{'role': role, 'session_id': slot.session,
                                 'pokes': slot.pokes if slot.session is not None and slot.compatible else None}
                                for role, slot in self.slots.items()],
                'pokes': pokes,
                'roles': {role: asdict(slot) for role, slot in self.slots.items()},
                'events': list(self.events), 'native_wake': 'UNOBSERVED',
                'scope': 'controller-turns-only-not-task-verdict'}


def parse_state(value: object) -> WakeState:
    """A new state only; never restore mutable slots or counters from input."""
    if type(value) is not dict or set(value) != {'policy', 'roles'}:
        raise WakeRefused('closed new wake state required')
    return WakeState(parse_policy(value['policy']), _roles(value['roles']))


def observe(wave: Any, policy: WakePolicy) -> Revision:
    """Run fixed controller source in its own helper, never in a role shell."""
    if wave.remote is None:
        raise BackendUnavailable('wave observation helper absent')
    source = Path(__file__).with_name('wave_snapshot.py').read_text()
    payload = wave._call(['exec', '-u', '0', '--', wave._name(wave.remote), 'python3', '-I', '-S',
                          '-c', source, WAVE_ROOT, '/fixture/repo.git',
                          str(policy.max_files), str(policy.max_bytes)])
    try:
        if type(payload) is not bytes or len(payload) > MAX_DECLARATION:
            raise WakeRefused('bounded observer response required')
        return parse_revision(json.loads(payload, object_pairs_hook=_pairs))
    except (TypeError, ValueError, RecursionError) as exc:
        raise BackendUnavailable('shared observation unavailable') from exc


def drive(wave: Any, policy: WakePolicy, *, read_revision: Callable[[], Revision] | None = None,
          deliver: Callable[[Poke], bool] | None = None, clock: Callable[[], float] = time.monotonic,
          sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Drive all roles to declared caps/failures or the wave's ORIGINAL deadline.

    Test doubles may supply an observer or suppress transport. Production uses
    the fixed controller helper and fenced DockerWave.turn. No client runs here
    outside the backend, and no message content or CPP revision enters policy.
    """
    # The caller retains approval authority. A generated runtime declaration
    # cannot approve its own policy or replace that independently held binding.
    bound = getattr(wave, 'approved_wake', None)
    if type(bound) is not WakeBinding or type(policy) is not WakePolicy:
        raise WakeRefused('caller-approved wake binding required before preparation')
    names, approved_policy = bound.verify()
    parse_policy({'version': 1, **asdict(policy)})
    population = getattr(wave, 'roles', None)
    if type(population) not in (tuple, list):
        raise WakeRefused('complete declared runtime role population required')
    assert isinstance(population, (tuple, list))
    if (not 1 <= len(population) <= MAX_ROLES
            or any(type(getattr(role, 'resume_texts', None)) is not tuple for role in population)):
        raise WakeRefused('complete declared runtime role population required')
    roles = _roles(tuple(getattr(role, 'name', None) for role in population))
    if roles != names or policy.digest != approved_policy.digest:
        raise WakeRefused('wake policy or population differs from caller approval')
    if any(role.resume_texts for role in wave.roles):
        raise ValueError('fixed resumed turns and wake policy cannot both own turns')
    if wave.closed or (wave.root / 'wake-declaration.json').exists():
        raise ValueError('wake driver is single-use for an owned wave')
    state = WakeState(policy, roles)
    state.journal = lambda event: wave._write('wake-events.json', state.events)
    declaration = {'version': 1, 'policy': asdict(policy), 'policy_digest': policy.digest,
                   'approved_declaration_digest': bound.approved_digest,
                   'trigger': 'controller-file-and-ref-digests', 'roles': roles,
                   'attempt_id': wave.attempt_id,
                   'clock': 'monotonic' if clock is time.monotonic else 'injected-policy-only'}
    declaration_bytes = json.dumps(declaration, sort_keys=True).encode()
    declaration_digest = 'sha256:' + hashlib.sha256(declaration_bytes).hexdigest()
    pool: ThreadPoolExecutor | None = None
    futures: dict[str, Future[ExecuteResult]] = {}
    read = read_revision or (lambda: observe(wave, policy))
    outcome = 'UNKNOWN'
    last_revision: Revision | None = None
    errors: list[BaseException] = []
    missed = 0
    cleanup: dict[str, Any] = {}
    stopped_roles: set[str] = set()

    def sample() -> Revision | None:
        nonlocal missed
        try:
            revision = read()
            if type(revision) is not Revision:
                raise SnapshotUnavailable('complete controller revision required')
        except (BackendUnavailable, SnapshotUnavailable):
            missed += 1
            if missed == 1:
                state.record('observation-unavailable', '-', clock())
            return None
        if missed:
            state.record('observation-restored', '-', clock(), missed=missed)
            missed = 0
        return revision

    def stop_terminal(role: str) -> None:
        if state.slots[role].phase == 'terminal' and not wave.closed and role not in stopped_roles:
            current = wave.states[role]
            stopped_roles.add(role)
            current.backend.end_attempt(current.handle)
            state.record('role-stop-requested', role, clock())

    def ended(role: str, result: ExecuteResult, revision: Revision | None) -> None:
        current = wave.states[role]
        session = None if 'resume-header-disagrees' in current.unknown else current.session_id
        state.ended(role, session, result, revision, clock())
        stop_terminal(role)

    def completed(role: str, future: Future[ExecuteResult], revision: Revision | None) -> None:
        try:
            result = future.result()
        except ct.TurnsRefused:
            slot = state.slots[role]
            state.record('poke-refused', role, clock(), reason='turn-fenced', nonce=slot.active_nonce)
            slot.phase, slot.end = 'terminal', 'turn-fenced'
            stop_terminal(role)
        else:
            ended(role, result, revision)

    try:
        wave._write('wake-declaration.json', {**declaration, 'digest': declaration_digest})
        pool = ThreadPoolExecutor(max_workers=len(roles))
        if not wave._prepared:
            wave.prepare()
        while last_revision is None:
            wave.deadline.remaining(policy.poll_seconds)
            last_revision = sample()
            if last_revision is None:
                sleep(wave.deadline.remaining(policy.poll_seconds))
        for role in roles:
            futures[role] = pool.submit(wave.turn, role)
        while True:
            wave.deadline.remaining(policy.poll_seconds)
            previous_revision = last_revision
            finished = {role: future for role, future in futures.items() if future.done()}
            revision = sample()
            if revision is None:
                sleep(wave.deadline.remaining(policy.poll_seconds))
                continue
            last_revision = revision
            now = number(clock())
            for role, future in finished.items():
                # Do not absorb a sibling write made after this turn returned
                # but before the current sample. A conservative extra poke is
                # observable; a silently missed wake would be a false deadline.
                completed(role, future, previous_revision)
                del futures[role]
            if all(slot.phase == 'terminal' for slot in state.slots.values()):
                outcome = 'STOPPED'
                break
            for role in roles:
                poke = state.offer(role, revision, now)
                if poke is None:
                    stop_terminal(role)
                    continue
                current = wave.states[role]
                fresh = sample()  # Re-observe at acting, never a stale queued revision.
                if fresh is None:
                    state.slots[role].pending = None
                    state.record('poke-refused', role, clock(), reason='observation-unavailable', nonce=poke.nonce)
                    continue
                idle = role not in futures and not current.busy.locked()
                stopped = current.backend.confirm_stopped(current.handle)
                live = True if stopped is Confirmation.NOT_CONFIRMED else False if stopped is Confirmation.CONFIRMED else None
                wave.deadline.remaining(policy.poll_seconds)
                if not state.dispatch(poke, fresh, current_role=role,
                                      current_session=current.session_id, idle=idle, live=live, now=clock()):
                    continue
                if deliver is not None and not deliver(poke):
                    state.suppressed(poke, clock())
                    continue
                futures[role] = pool.submit(wave.turn, role, policy.literal, expected_session=poke.session)
            sleep(wave.deadline.remaining(policy.poll_seconds))
    except CompletionUnavailable:
        timing = wave.deadline.qualify(wave.deadline.marker('wake-driver'), False)
        elapsed = timing.get('elapsed')
        outcome = ('DEADLINE' if isinstance(elapsed, (int, float))
                   and elapsed >= wave.deadline.end - wave.deadline.start else 'UNKNOWN')
    except BaseException as exc:  # noqa: BLE001 - retain original after owned cleanup
        errors.append(exc)
        try:
            state.record('driver-unavailable', '-', clock(), reason=type(exc).__name__)
        except BaseException as record_error:  # noqa: BLE001 - failed journal cannot bypass cleanup
            errors.append(record_error)
    finally:
        # Close kills active roles, waits for their controller capture and confirms
        # every resource; no executor join may leave a live turn behind.
        try:
            cleanup = wave.close()
        except BaseException as exc:  # noqa: BLE001 - preserve first error
            errors.append(exc)
        if pool is not None:
            try:
                pool.shutdown(wait=True)
            except BaseException as exc:  # noqa: BLE001 - cleanup already attempted
                errors.append(exc)
        for role, future in futures.items():
            try:
                # Cleanup can finish a turn after the observation endpoint.
                # Its exit is known, but no fresh end watermark is fabricated.
                completed(role, future, None)
            except BaseException as exc:  # noqa: BLE001 - account all futures
                errors.append(exc)
        completion = cleanup.get('completion', {})
        if completion.get('cleanup_confirmed') is not True or ('elapsed' in completion and completion['elapsed'] is None):
            outcome = 'UNKNOWN'
        elif completion.get('on_time') is not True:
            outcome = 'DEADLINE'
        if errors:
            outcome = 'UNKNOWN'
        report = state.report(outcome)
        report['attempt_id'] = wave.attempt_id
        for row in report['poke_counts']:
            if wave.states[row['role']].session_id != row['session_id']:
                row['pokes'] = None
        report['completion'] = completion
        report['declaration_digest'] = declaration_digest
        report['unavailable_samples_at_end'] = missed
        report['final_decision_emission'] = 'after-cleanup-observation'
        try:
            wave._write('wake-report.json', report)
        except BaseException as exc:  # noqa: BLE001 - preserve first error after resource retirement
            errors.append(exc)
    if errors:
        raise errors[0]
    return report
