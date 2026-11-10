"""Bounded client-reported wave usage, never a token limiter or live authority.

Inputs are authored/retained numeric captures, not a credential or transcript
reader. The caller must retain the expected receipt and context independently.
Custody proves which client-reported counters were captured, not their truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any

from . import wave_wake as wake

MAX_BYTES = 8 * 1024 * 1024
MAX_COUNT = (1 << 63) - 1
MAX_SAMPLES = 32768
FORMAT = 'cumulative-session-total-v1'


class UsageRefused(ValueError):
    """Fixed diagnostics; unknown input values are never echoed."""


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise UsageRefused('closed wave accounting object required')
    return value


def _integer(value: object, minimum: int = 0, maximum: int = MAX_COUNT) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise UsageRefused('bounded nonboolean accounting integer required')
    return value


def _number(value: object, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise UsageRefused('finite accounting time required')
    try:
        number = float(value)  # type: ignore[arg-type]
    except (ValueError, OverflowError):
        raise UsageRefused('finite accounting time required') from None
    if not math.isfinite(number) or number < 0 or positive and number == 0:
        raise UsageRefused('finite nonnegative accounting time required')
    return number


def _json(value: object) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise UsageRefused('bounded JSON accounting input required') from None
    if not 0 < len(raw) <= MAX_BYTES:
        raise UsageRefused('accounting byte bound exceeded')
    return raw


def _hash(raw: bytes) -> str:
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _turns(value: object) -> tuple[str, ...]:
    if type(value) not in (tuple, list):
        raise UsageRefused('complete bounded turn population required')
    assert isinstance(value, (tuple, list))
    if not 1 <= len(value) <= 65:
        raise UsageRefused('complete bounded turn population required')
    if value[0] != 'initial':
        raise UsageRefused('initial turn identity required')
    for nonce in value[1:]:
        wake._nonce(nonce)
    if len(set(value)) != len(value):
        raise UsageRefused('unique turn identities required')
    return tuple(value)


@dataclass(frozen=True)
class RoleBinding:
    role: str
    session_id: str
    turns: tuple[str, ...]

    def __post_init__(self) -> None:
        wake._role(self.role)
        wake._session(self.session_id)
        if type(self.turns) is not tuple:
            raise UsageRefused('immutable turn population required')
        _turns(self.turns)


@dataclass(frozen=True)
class Context:
    wave_id: str
    declaration_digest: str
    deadline_digest: str
    deadline_seconds: float
    clock: str
    client_version: str
    roles: tuple[RoleBinding, ...]

    def __post_init__(self) -> None:
        wake._role(self.wave_id)
        wake._digest(self.declaration_digest)
        wake._digest(self.deadline_digest)
        _number(self.deadline_seconds, positive=True)
        if self.clock not in ('monotonic', 'injected-policy-only'):
            raise UsageRefused('explicit accounting clock required')
        if (type(self.client_version) is not str or len(self.client_version) > 64
                or re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9]+)*', self.client_version) is None):
            raise UsageRefused('pinned accounting client version required')
        if (type(self.roles) is not tuple or not 1 <= len(self.roles) <= 64
                or any(type(role) is not RoleBinding for role in self.roles)):
            raise UsageRefused('immutable accounting role population required')
        wake._roles(tuple(role.role for role in self.roles))
        for role in self.roles:
            RoleBinding(role.role, role.session_id, role.turns)
        if len({role.session_id for role in self.roles}) != len(self.roles):
            raise UsageRefused('distinct accounting sessions required')

    @property
    def digest(self) -> str:
        return _hash(_json(asdict(self)))


def parse_context(value: object) -> Context:
    row = _object(value, set(Context.__dataclass_fields__))
    roles = row['roles']
    if type(roles) not in (tuple, list) or not 1 <= len(roles) <= 64:
        raise UsageRefused('bounded accounting role population required')
    bindings = []
    for entry in roles:
        role = _object(entry, {'role', 'session_id', 'turns'})
        bindings.append(RoleBinding(role['role'], role['session_id'], _turns(role['turns'])))
    return Context(**{**row, 'roles': tuple(bindings)})


@dataclass(frozen=True)
class Reference:
    version: int
    context_digest: str
    digest: str
    size: int

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            raise UsageRefused('accounting reference version required')
        wake._digest(self.context_digest)
        wake._digest(self.digest)
        _integer(self.size, 1, MAX_BYTES)


def parse_reference(value: object) -> Reference:
    return Reference(**_object(value, set(Reference.__dataclass_fields__)))


def reference(raw: bytes, context: Context) -> Reference:
    """Consistency receipt only. The trusted caller owns retention/provenance."""
    if type(context) is not Context:
        raise UsageRefused('accounting context required')
    context = parse_context(asdict(context))
    if type(raw) is not bytes:
        raise UsageRefused('retained accounting bytes required')
    return Reference(1, context.digest, _hash(raw), len(raw))


def _last_counter(samples: list[int]) -> int:
    if not samples:
        raise UsageRefused('usage counter unobserved')
    previous = 0
    for sample in samples:
        _integer(sample)
        if sample < previous:
            raise UsageRefused('usage counter reset or ambiguity')
        previous = sample
    return samples[-1]


def _role_usage(value: object, binding: RoleBinding) -> dict[str, Any]:
    row = _object(value, {'role', 'session_id', 'turns'})
    if row['role'] != binding.role or row['session_id'] != binding.session_id:
        raise UsageRefused('accounting session binding differs')
    turns = row['turns']
    if type(turns) is not list or len(turns) != len(binding.turns):
        raise UsageRefused('accounting turn coverage incomplete')
    samples: list[int] = []
    durations = []
    previous = 0.0
    first = None
    for turn_id, entry in zip(binding.turns, turns, strict=True):
        turn = _object(entry, {'turn_id', 'started_at', 'ended_at', 'samples'})
        if turn['turn_id'] != turn_id:
            raise UsageRefused('accounting turn identity differs')
        start, end = _number(turn['started_at']), _number(turn['ended_at'])
        if start < previous or end < start:
            raise UsageRefused('accounting role clock inconsistent')
        previous = end
        if first is None:
            first = start
        durations.append(end - start)
        if type(turn['samples']) is not list or not turn['samples']:
            raise UsageRefused('usage sample coverage incomplete')
        if len(samples) + len(turn['samples']) > MAX_SAMPLES:
            raise UsageRefused('usage sample bound exceeded')
        samples.extend(turn['samples'])
    assert first is not None
    return {'role': binding.role, 'session_id': binding.session_id, 'status': 'COMPLETE',
            'tokens': _last_counter(samples), 'active_seconds': _number(sum(durations)),
            'session_elapsed': _number(previous - first), 'last_ended_at': previous,
            'turns': len(turns)}


def _project(data: object, context: Context) -> dict[str, Any]:
    row = _object(data, {'version', 'wave_id', 'declaration_digest', 'deadline_digest', 'clock',
                         'client_version', 'counter_format', 'roles', 'completion_elapsed'})
    if (type(row['version']) is not int or row['version'] != 1 or row['counter_format'] != FORMAT
            or any(row[key] != getattr(context, key) for key in (
                'wave_id', 'declaration_digest', 'deadline_digest', 'clock', 'client_version'))):
        raise UsageRefused('accounting capture context differs')
    roles = row['roles']
    if type(roles) is not list or len(roles) > 64:
        raise UsageRefused('bounded captured role population required')
    names = []
    for role in roles:
        obj = _object(role, {'role', 'session_id', 'turns'})
        names.append(wake._role(obj['role']))
    population_complete = names == [role.role for role in context.roles]
    records: list[dict[str, Any]] = []
    for binding in context.roles:
        item: dict[str, Any] = {'role': binding.role, 'session_id': binding.session_id, 'status': 'UNKNOWN',
                'tokens': None, 'active_seconds': None, 'session_elapsed': None, 'last_ended_at': None,
                'turns': None}
        if names.count(binding.role) == 1:
            try:
                item = _role_usage(roles[names.index(binding.role)], binding)
            except ValueError:
                pass
        records.append(item)
    complete = population_complete and all(role['status'] == 'COMPLETE' for role in records)
    known = [role['tokens'] for role in records if role['tokens'] is not None]
    subtotal = sum(known) if known else None
    if subtotal is not None and subtotal > MAX_COUNT:
        complete, subtotal = False, None
    completion = row['completion_elapsed']
    if completion is not None:
        completion = _number(completion)
        if any(role['last_ended_at'] is not None and role['last_ended_at'] > completion for role in records):
            raise UsageRefused('accounting completion clock inconsistent')
    return {'version': 1, 'status': 'COMPLETE' if complete and completion is not None else 'UNKNOWN',
            'wave_id': context.wave_id, 'source': 'client-reported-not-provider-attested',
            'tokens_complete': bool(complete), 'tokens': subtotal if complete else None,
            'known_tokens_subtotal': subtotal, 'known_roles': len(known), 'planned_roles': len(context.roles),
            'roles': records, 'wall_seconds': completion,
            'role_active_seconds': _number(sum(role['active_seconds'] for role in records)) if complete else None,
            'deadline_exceeded': completion > context.deadline_seconds if completion is not None else None,
            'enforcement_authority': False, 'admission_authority': False}


def evaluate(raw: object, receipt: object, expected: object) -> dict[str, Any]:
    """Pure retained-byte reader; never choose the expected hash from a report."""
    try:
        if type(raw) is not bytes or type(receipt) is not Reference or type(expected) is not Context:
            raise UsageRefused('independently held accounting binding required')
        receipt = parse_reference(asdict(receipt))
        expected = parse_context(asdict(expected))
        if (not 0 < len(raw) <= MAX_BYTES or len(raw) != receipt.size or _hash(raw) != receipt.digest
                or receipt.context_digest != expected.digest):
            raise UsageRefused('accounting byte custody differs')
        return _project(json.loads(raw, object_pairs_hook=wake._pairs), expected)
    except (ValueError, RecursionError):
        return {'version': 1, 'status': 'UNKNOWN', 'tokens_complete': False, 'tokens': None,
                'known_tokens_subtotal': None, 'known_roles': 0,
                'enforcement_authority': False, 'admission_authority': False,
                'reason': 'accounting capture unavailable or unverifiable'}
