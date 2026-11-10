"""Sealed controller wake bytes; projections and participant claims are not authority.

The caller retains Reference separately, just as final-wave snapshot custody
retains an expected manifest hash. Neither a report nor this module issues
approval. Native wake and task achievement remain unobserved here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .live_wave import PokeCount

from . import wave_wake as ww

MAX_CAPTURE = 8 * 1024 * 1024
MAX_EVENTS = 32768
ZERO = '0' * 64
COMMON = {'seq', 'prev_hash', 'event'}
EVENT_FIELDS = {
    'turn-ended': {'reason', 'exit_code', 'session', 'binding_session', 'revision', 'files', 'refs', 'nonce'},
    'poke-attempt': {'revision', 'files', 'refs', 'session', 'nonce', 'poke'},
    'poke-refused': {'reason', 'nonce'},
    'poke-unconfirmed': {'nonce'},
    'role-ended': {'reason'},
    'role-stop-requested': set(),
    'observation-unavailable': set(),
    'observation-restored': {'missed'},
    'driver-unavailable': {'reason'},
}


class CaptureUnavailable(ValueError):
    """Incomplete, malformed or misbound controller custody."""


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise CaptureUnavailable('closed wake capture object required')
    return value


def _integer(value: object, minimum: int = 0, maximum: int = (1 << 63) - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CaptureUnavailable('bounded wake capture integer required')
    return value


def _json(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    except (ValueError, TypeError, RecursionError):
        raise CaptureUnavailable('serializable wake capture required') from None


def _hash(raw: bytes) -> str:
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Context:
    attempt_id: str
    approved_declaration_digest: str
    policy_digest: str
    roles: tuple[str, ...]
    deadline_digest: str
    clock: str

    def __post_init__(self) -> None:
        ww._role(self.attempt_id)
        for value in (self.approved_declaration_digest, self.policy_digest, self.deadline_digest):
            ww._digest(value)
        if type(self.roles) is not tuple or ww._roles(self.roles) != self.roles:
            raise CaptureUnavailable('immutable capture role population required')
        if self.clock not in ('monotonic', 'injected-policy-only'):
            raise CaptureUnavailable('declared capture clock required')

    @property
    def digest(self) -> str:
        return _hash(_json(asdict(self)))


def parse_context(value: object) -> Context:
    row = _object(value, set(Context.__dataclass_fields__))
    return Context(**{**row, 'roles': ww._roles(row['roles'])})


@dataclass(frozen=True)
class Reference:
    version: int
    context_digest: str
    digest: str
    size: int

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            raise CaptureUnavailable('wake capture reference version required')
        ww._digest(self.context_digest)
        ww._digest(self.digest)
        _integer(self.size, 1, MAX_CAPTURE)


def parse_reference(value: object) -> Reference:
    return Reference(**_object(value, set(Reference.__dataclass_fields__)))


def _read(root: Path, digest: str, size: int) -> bytes:
    ww._digest(digest)
    _integer(size, 1, MAX_CAPTURE)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        objects = os.open('objects', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            fd = os.open(digest[7:], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=objects)
        finally:
            os.close(objects)
    finally:
        os.close(directory)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != size:
            raise CaptureUnavailable('wake object size/type differs')
        raw = stream.read(size + 1)
        after = os.fstat(stream.fileno())
    if len(raw) != size or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
        raise CaptureUnavailable('wake object changed while reading')
    if _hash(raw) != digest:
        raise CaptureUnavailable('wake object hash differs')
    return raw


class Capture:
    """Single-use private writer. Each transition is fsynced before dispatch."""

    def __init__(self, root: Path, context: Context, origin: float) -> None:
        if not isinstance(root, Path) or type(context) is not Context:
            raise CaptureUnavailable('owned capture root/context required')
        self.context = parse_context(asdict(context))
        self.origin = ww._time(origin)
        self.root = root
        self.count = self.size = 0
        self.previous = ZERO
        self.sealed = self.failed = False
        root.mkdir(mode=0o700, exist_ok=False)
        (root / 'objects').mkdir(mode=0o700)
        fd = os.open(root / 'events.tmp', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.stream = os.fdopen(fd, 'w+b', buffering=0)
        try:
            self._append({'event': 'capture-start', 'version': 1, 'context': asdict(self.context)})
        except BaseException:
            self.stream.close()
            raise

    def _append(self, row: dict[str, Any]) -> None:
        if self.sealed or self.failed or self.count >= MAX_EVENTS + 2:
            raise CaptureUnavailable('capture closed, failed or over bound')
        try:
            raw = _json({'seq': self.count + 1, 'prev_hash': self.previous, **row})
            if self.size + len(raw) > MAX_CAPTURE:
                raise CaptureUnavailable('wake capture byte bound exceeded')
            if self.stream.write(raw) != len(raw):
                raise CaptureUnavailable('incomplete capture write')
            os.fsync(self.stream.fileno())
            self.count += 1
            self.size += len(raw)
            self.previous = hashlib.sha256(raw).hexdigest()
        except BaseException:
            self.failed = True
            raise

    def append(self, event: dict[str, Any]) -> None:
        try:
            if type(event) is not dict or event.get('seq') != self.count:
                raise CaptureUnavailable('contiguous controller event required')
            row = {key: value for key, value in event.items() if key not in ('seq', 'time')}
            row.update(order=event['seq'], elapsed=ww._time(event.get('time')) - self.origin)
            _event(row, self.context.roles)
            self._append(row)
        except BaseException:
            self.failed = True
            raise

    def seal(self, outcome: str, final_sessions: object) -> Reference:
        try:
            _final_sessions(final_sessions, self.context.roles)
            if outcome not in ('STOPPED', 'DEADLINE', 'UNKNOWN'):
                raise CaptureUnavailable('declared driver outcome required')
            self._append({'event': 'capture-seal', 'events': self.count - 1,
                          'last_hash': self.previous, 'outcome': outcome, 'final_sessions': final_sessions})
            self.sealed = True
            self.stream.seek(0)
            raw = self.stream.read(MAX_CAPTURE + 1)
            self.stream.close()
            ref = Reference(1, self.context.digest, _hash(raw), self.size)
            # Validate our own complete stream before it can become retained evidence.
            _decode(raw, ref, self.context)
            directory = os.open(self.root / 'objects', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                fd = os.open(ref.digest[7:], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            finally:
                os.close(directory)
            with os.fdopen(fd, 'wb') as target:
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
                os.fchmod(target.fileno(), 0o400)
            directory = os.open(self.root / 'objects', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            _read(self.root, ref.digest, ref.size)
            (self.root / 'events.tmp').unlink()
            return ref
        finally:
            self.stream.close()

    def close(self) -> None:
        self.stream.close()
        self.failed = True


def _optional_session(value: object) -> None:
    if value is not None:
        ww._session(value)


def _final_sessions(value: object, roles: tuple[str, ...]) -> dict[str, str | None]:
    if type(value) is not list or len(value) != len(roles):
        raise CaptureUnavailable('complete final session population required')
    sessions = {}
    for name, entry in zip(roles, value, strict=True):
        row = _object(entry, {'role', 'session_id'})
        if row['role'] != name:
            raise CaptureUnavailable('final session role mismatch')
        _optional_session(row['session_id'])
        sessions[name] = row['session_id']
    return sessions


def _event(value: object, roles: tuple[str, ...]) -> dict[str, Any]:
    if type(value) is not dict or type(value.get('event')) is not str or value['event'] not in EVENT_FIELDS:
        raise CaptureUnavailable('declared wake event required')
    row = _object(value, {'event', 'role', 'elapsed', 'order'} | EVENT_FIELDS[value['event']])
    _integer(row['order'], 1, MAX_EVENTS)
    ww._time(row['elapsed'])
    system = row['event'] in ('observation-unavailable', 'observation-restored', 'driver-unavailable')
    if (system and row['role'] != '-' or not system and row['role'] not in roles
            and not (row['event'] == 'poke-refused' and row['role'] == '-')):
        raise CaptureUnavailable('declared event role required')
    if 'reason' in row and (type(row['reason']) is not str
                          or re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,127}', row['reason']) is None):
        raise CaptureUnavailable('bounded controller reason required')
    for key in ('session', 'binding_session'):
        if key in row:
            _optional_session(row[key])
    if 'nonce' in row and row['nonce'] is not None:
        ww._nonce(row['nonce'])
    if row['event'] in ('poke-attempt', 'poke-unconfirmed') and row['nonce'] is None:
        raise CaptureUnavailable('poke identity required')
    if 'poke' in row:
        _integer(row['poke'], 1, 64)
        ww._session(row['session'])
    if 'missed' in row:
        _integer(row['missed'], 1)
    if 'exit_code' in row and row['exit_code'] is not None:
        _integer(row['exit_code'], -(1 << 31), (1 << 31) - 1)
    if 'revision' in row:
        if row['revision'] is None:
            if row['event'] != 'turn-ended' or row['files'] is not None or row['refs'] is not None:
                raise CaptureUnavailable('complete revision tuple required')
        elif ww.Revision(row['files'], row['refs']).identity != row['revision']:
            raise CaptureUnavailable('event revision digest mismatch')
    return row


def _decode(raw: bytes, ref: Reference, expected: Context) -> dict[str, Any]:
    if (type(raw) is not bytes or not 0 < len(raw) <= MAX_CAPTURE or len(raw) != ref.size
            or _hash(raw) != ref.digest or not raw.endswith(b'\n') or ref.context_digest != expected.digest):
        raise CaptureUnavailable('complete bound capture required')
    lines = raw.splitlines(keepends=True)
    if not 2 <= len(lines) <= MAX_EVENTS + 2:
        raise CaptureUnavailable('bounded sealed event population required')
    previous = ZERO
    rows = []
    for index, line in enumerate(lines, 1):
        row = json.loads(line, object_pairs_hook=ww._pairs)
        if (type(row) is not dict or type(row.get('seq')) is not int or row['seq'] != index
                or row.get('prev_hash') != previous):
            raise CaptureUnavailable('wake event chain differs')
        previous = hashlib.sha256(line).hexdigest()
        rows.append(row)
    start = _object(rows[0], COMMON | {'version', 'context'})
    if (start['event'] != 'capture-start' or type(start['version']) is not int or start['version'] != 1
            or parse_context(start['context']) != expected):
        raise CaptureUnavailable('capture context mismatch')
    seal = _object(rows[-1], COMMON | {'events', 'last_hash', 'outcome', 'final_sessions'})
    if (seal['event'] != 'capture-seal' or _integer(seal['events']) != len(rows) - 2
            or seal['last_hash'] != seal['prev_hash'] or seal['outcome'] not in ('STOPPED', 'DEADLINE', 'UNKNOWN')):
        raise CaptureUnavailable('wake seal differs')
    finals = _final_sessions(seal['final_sessions'], expected.roles)
    states: dict[str, dict[str, Any]] = {role: {'session': None, 'observed': False, 'compatible': True,
        'count': 0, 'active': None, 'idle': False, 'terminal': False} for role in expected.roles}
    nonces: set[str] = set()
    attempts: dict[str, dict[str, Any]] = {}
    elapsed = 0.0
    for order, stored in enumerate(rows[1:-1], 1):
        row = _event({key: value for key, value in stored.items() if key not in ('seq', 'prev_hash')}, expected.roles)
        if row['order'] != order or row['elapsed'] < elapsed:
            raise CaptureUnavailable('wake event order/time differs')
        elapsed = row['elapsed']
        role = row['role']
        if role == '-':
            continue
        state = states[role]
        event = row['event']
        if event == 'turn-ended':
            if row['nonce'] != state['active'] or state['observed'] and state['active'] is None:
                raise CaptureUnavailable('unmatched turn exit')
            if not state['observed']:
                state['session'] = row['session']
                state['observed'] = True
            if row['binding_session'] != state['session']:
                raise CaptureUnavailable('initial session binding changed')
            state['compatible'] &= row['session'] == state['session']
            state['idle'] = (row['reason'] == 'exited' and row['exit_code'] == 0
                             and row['session'] is not None and state['compatible'] and row['revision'] is not None)
            if row['nonce'] is not None:
                attempts[row['nonce']]['result'] = dict(row)
            state['active'] = None
        elif event == 'poke-attempt':
            if (not state['idle'] or state['terminal'] or state['active'] is not None
                    or row['session'] != state['session'] or row['nonce'] in nonces
                    or row['poke'] != state['count'] + 1):
                raise CaptureUnavailable('unbound or repeated poke attempt')
            state['count'] += 1
            state['active'] = row['nonce']
            state['idle'] = False
            nonces.add(row['nonce'])
            attempts[row['nonce']] = {**row, 'result': None, 'refusal': None, 'unconfirmed': None}
        elif event == 'poke-unconfirmed':
            if row['nonce'] != state['active']:
                raise CaptureUnavailable('unmatched unconfirmed poke')
            state['active'] = None
            state['idle'] = True
            attempts[row['nonce']]['unconfirmed'] = dict(row)
        elif event == 'poke-refused' and row['nonce'] == state['active'] and row['nonce'] is not None:
            state['active'] = None
            state['idle'] = False
            state['terminal'] = row['reason'] == 'turn-fenced'
            attempts[row['nonce']]['refusal'] = dict(row)
        elif event == 'role-ended':
            state['terminal'] = True
            state['idle'] = False
    if any(state['active'] is not None for state in states.values()):
        raise CaptureUnavailable('unresolved poke outcome')
    if seal['outcome'] == 'STOPPED' and not all(state['terminal'] for state in states.values()):
        raise CaptureUnavailable('unwitnessed policy stop')
    counts = [{'role': role, 'session_id': state['session'],
               'pokes': state['count'] if state['observed'] and state['session'] is not None
               and state['compatible'] and finals[role] == state['session'] else None}
              for role, state in states.items()]
    return {'status': 'CAPTURED', 'complete': all(row['pokes'] is not None for row in counts),
            'poke_count': sum(state['count'] for state in states.values()), 'poke_counts': counts,
            'pokes': list(attempts.values()), 'outcome': seal['outcome'], 'context_digest': expected.digest}


def verify(root: object, reference: object, expected: object) -> dict[str, Any]:
    """Expected reference/context come from the trusted caller, never a report."""
    try:
        if not isinstance(root, Path) or type(reference) is not Reference or type(expected) is not Context:
            raise CaptureUnavailable('independently held capture binding required')
        reference = parse_reference(asdict(reference))
        expected = parse_context(asdict(expected))
        return _decode(_read(root, reference.digest, reference.size), reference, expected)
    except (OSError, ValueError, RecursionError):
        return {'status': 'UNKNOWN', 'complete': False, 'reason': 'wake capture unavailable or unverifiable'}


def poke_counts(root: Path, reference: Reference, expected: Context) -> tuple[PokeCount, ...]:
    """The existing #620 typed seam, derived exclusively from verified bytes."""
    from .live_wave import PokeCount
    result = verify(root, reference, expected)
    if result['status'] != 'CAPTURED' or result['complete'] is not True:
        raise CaptureUnavailable('complete retained poke count evidence required')
    return tuple(PokeCount(**row) for row in result['poke_counts'])
