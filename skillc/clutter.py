"""Controller-owned before/after residue inventory (#619).

Only ADDED surviving logical items are clutter candidates. Changes/removals
of pre-existing state are separate preservation observations (#278), never
credits against clutter. A missing or incomplete surface is UNKNOWN, not an
empty successful scan. No arm name or CPP-presence preference enters grading.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1
SETTLE_POINT = 'after-completion-before-teardown'
CPP_KINDS = ('registry', 'mailboxes', 'cursors', 'heartbeats', 'locks', 'claims')
ROLE_KINDS = ('worktrees', 'local-branches', 'remote-branches', 'stashes', 'workspace',
              *(f'cpp-{kind}' for kind in CPP_KINDS), 'processes', 'temp')
MAX_ITEMS = 20_000
MAX_BYTES = 32 * 1024 * 1024
MAX_DEPTH = 64


class Refused(ValueError):
    """A declaration or capture cannot support this instrument."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(value: object) -> str:
    return 'sha256:' + hashlib.sha256(canonical(value)).hexdigest()


def _name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 128 or any(
            c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in value):
        raise Refused('logical names must be bounded ASCII identifiers')
    return value


def _path(value: object) -> str:
    if (not isinstance(value, str) or not value.startswith('/') or value == '/'
            or '\0' in value or any(part in ('', '.', '..') for part in value.split('/')[1:])):
        raise Refused('scope paths must be absolute, non-root and in normal form')
    return value


def _paths(value: object) -> None:
    if not isinstance(value, list) or len(value) > 64 or len(set(map(str, value))) != len(value):
        raise Refused('scope roots must be a bounded distinct list')
    for path in value:
        _path(path)


@dataclass(frozen=True)
class Policy:
    """The exact common-arm declaration, including scope and allowed products."""

    data: dict[str, Any]

    @property
    def identity(self) -> str:
        return digest(self.data)

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(sorted(self.data['roles']))

    @property
    def surfaces(self) -> frozenset[str]:
        return frozenset({'shared', 'containers', 'networks'} | {
            f'{role}/{kind}' for role in self.roles for kind in ROLE_KINDS})

    def selected(self, category: str) -> frozenset[tuple[str, str]]:
        return frozenset((row['surface'], row['key']) for row in self.data[category])


def parse_policy(raw: object) -> Policy:
    if not isinstance(raw, dict) or set(raw) != {
        'schema_version', 'roles', 'shared_roots', 'settle_point', 'settle_seconds',
        'delivered', 'declared_allowed', 'daemon_scope',
    } or type(raw.get('schema_version')) is not int or raw['schema_version'] != SCHEMA_VERSION:
        raise Refused('clutter must follow the closed inventory schema version 1')
    if raw['settle_point'] != SETTLE_POINT:
        raise Refused('clutter settle point must follow completion and precede teardown')
    seconds = raw['settle_seconds']
    if (type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 30):
        raise Refused('clutter settle seconds must be finite and between 0 and 30')
    if raw['daemon_scope'] not in ('controller-isolated', 'unobservable'):
        raise Refused('daemon scope must declare controller isolation or unavailable observation')
    roles = raw['roles']
    if not isinstance(roles, dict) or not 1 <= len(roles) <= 32:
        raise Refused('clutter must declare every role; an empty role population cannot certify')
    for role, scope in roles.items():
        _name(role)
        if not isinstance(scope, dict) or set(scope) != {'checkout', 'gitdir', 'remotes', 'cpp', 'temp_roots'}:
            raise Refused('each role needs checkout, gitdir, fixture remotes, all CPP roots and temp roots')
        _path(scope['checkout'])
        _path(scope['gitdir'])
        if not isinstance(scope['remotes'], dict) or not scope['remotes'] or len(scope['remotes']) > 32:
            raise Refused('fixture remote scope must be explicit and nonempty')
        for name, path in scope['remotes'].items():
            _name(name)
            _path(path)
        if not isinstance(scope['cpp'], dict) or set(scope['cpp']) != set(CPP_KINDS):
            raise Refused('all CPP state families must be declared, including on a baseline')
        for roots in scope['cpp'].values():
            _paths(roots)
            if not roots:
                raise Refused('CPP roots are explicit even when the baseline contains no CPP state')
        _paths(scope['temp_roots'])
        if not scope['temp_roots']:
            raise Refused('temporary directory scope must not be empty')
    _paths(raw['shared_roots'])
    if len(roles) > 1 and not raw['shared_roots']:
        raise Refused('multiple roles require a shared wave-state scope')
    # Copy through canonical JSON: mutable caller data cannot alter an approval
    # after parsing, and non-JSON values/non-finite values are refused.
    try:
        policy = Policy(json.loads(canonical(raw)))
    except (TypeError, ValueError, OverflowError) as exc:
        raise Refused('clutter policy is not canonical JSON') from exc
    selections: list[set[tuple[str, str]]] = []
    for category in ('delivered', 'declared_allowed'):
        rows = policy.data[category]
        if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
            raise Refused('clutter product selectors must be a bounded list')
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {'surface', 'key'}
                    or not isinstance(row.get('surface'), str) or row['surface'] not in policy.surfaces
                    or not isinstance(row.get('key'), str)
                    or not row['key'] or len(row['key']) > 4096 or '\0' in row['key']):
                raise Refused('clutter selectors must name an exact declared surface and logical key')
            key = (row['surface'], row['key'])
            if key in seen:
                raise Refused('duplicate clutter selector')
            seen.add(key)
        selections.append(seen)
    if selections[0] & selections[1]:
        raise Refused('delivered and declared-allowed products must be disjoint')
    return policy


@dataclass(frozen=True)
class Surface:
    items: Mapping[str, str]
    complete: bool = True
    error: str | None = None
    deleted_cwds: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        return {'items': dict(self.items), 'complete': self.complete, 'error': self.error,
                'deleted_cwds': list(self.deleted_cwds)}


@dataclass(frozen=True)
class Snapshot:
    scope_id: str
    phase: str
    policy_digest: str
    surfaces: Mapping[str, Surface]
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> dict[str, object]:
        return {'schema_version': self.schema_version, 'scope_id': self.scope_id, 'phase': self.phase,
                'policy_digest': self.policy_digest,
                'surfaces': {name: row.to_json() for name, row in sorted(self.surfaces.items())}}


def _surface_problem(row: Surface) -> str | None:
    if type(row.complete) is not bool or row.complete is not True or row.error is not None:
        return row.error or 'inventory coverage incomplete'
    if (not isinstance(row.items, Mapping) or len(row.items) > MAX_ITEMS or any(not isinstance(k, str) or not k or not isinstance(v, str)
                                         or not v for k, v in row.items.items())):
        return 'malformed inventory items'
    return None


def classify(policy: Policy, before: Snapshot, after: Snapshot) -> dict[str, Any]:
    """Classify additions exactly once; preservation and uncertainty stay visible."""
    unknown: list[dict[str, str]] = []
    bins: dict[str, list[dict[str, str]]] = {key: [] for key in ('delivered', 'declared-allowed', 'clutter')}
    preservation: dict[str, list[dict[str, str]]] = {key: [] for key in ('changed', 'removed', 'deleted-cwd')}
    identity_ok = (type(before.schema_version) is int and type(after.schema_version) is int
                   and before.schema_version == after.schema_version == SCHEMA_VERSION
                   and before.policy_digest == after.policy_digest == policy.identity
                   and before.phase == 'before' and after.phase == 'after'
                   and bool(before.scope_id) and before.scope_id == after.scope_id)
    if not identity_ok:
        unknown.append({'surface': '*', 'reason': 'capture schema, scope, phase or declaration identity disagrees'})
    extra = (set(before.surfaces) | set(after.surfaces)) - policy.surfaces
    if extra:
        unknown.append({'surface': '*', 'reason': 'capture contains undeclared surfaces'})
    delivered, allowed = policy.selected('delivered'), policy.selected('declared_allowed')
    for surface in sorted(policy.surfaces):
        left, right = before.surfaces.get(surface), after.surfaces.get(surface)
        if left is None or right is None:
            unknown.append({'surface': surface, 'reason': 'required before/after surface absent'})
            continue
        problems = [p for p in (_surface_problem(left), _surface_problem(right)) if p]
        if problems:
            unknown.append({'surface': surface, 'reason': '; '.join(problems)})
            continue
        if not identity_ok:
            continue
        for key in sorted(right.items.keys() - left.items.keys()):
            item = {'surface': surface, 'key': key, 'value': right.items[key]}
            selected = (surface, key)
            category = 'delivered' if selected in delivered else 'declared-allowed' if selected in allowed else 'clutter'
            bins[category].append(item)
        for key in sorted(left.items.keys() - right.items.keys()):
            preservation['removed'].append({'surface': surface, 'key': key, 'before': left.items[key]})
        for key in sorted(left.items.keys() & right.items.keys()):
            if left.items[key] != right.items[key]:
                preservation['changed'].append({'surface': surface, 'key': key,
                                                'before': left.items[key], 'after': right.items[key]})
        for key in right.deleted_cwds:
            preservation['deleted-cwd'].append({'surface': surface, 'key': key})
    status = 'NOT_CLEAN' if bins['clutter'] else 'UNKNOWN' if unknown else 'CLEAN'
    return {'schema_version': SCHEMA_VERSION, 'policy_digest': policy.identity, 'scope_id': before.scope_id,
            'status': status, 'clean': False if status == 'NOT_CLEAN' else None if status == 'UNKNOWN' else True,
            'counts': {key: len(items) for key, items in bins.items()}, 'additions': bins,
            'preservation': preservation, 'unknown': unknown,
            'blind_spots': ['Final snapshots cannot see state created and removed between observations.',
                           'Process evidence covers only the declared, controller-visible namespaces.',
                           ('A surviving controller-started process is also an added clutter candidate; '
                            'only the observer itself is excluded. Docker process collection has only fake qualification.'),
                           'Only declared roots are covered; captures across surfaces are not atomic.',
                           'Daemon attribution requires the declared isolated controller namespace.',
                           'Preservation observations are separate from the clutter verdict; see #278.']}


def no_forbidden_side_effect(report: Mapping[str, Any], preservation_outcome: str) -> str:
    """Compose #619 with an INDEPENDENT #278 preservation criterion.

    Clutter-clean alone does not establish preservation. Callers must supply
    the separate grader's outcome; an unavailable assessment remains UNKNOWN.
    A removed live cwd is already witnessed damage, regardless of clutter.
    """
    if preservation_outcome not in ('SATISFIED', 'VIOLATED', 'UNKNOWN'):
        raise Refused('preservation must be an independent criterion outcome')
    preservation = report.get('preservation')
    deleted = preservation.get('deleted-cwd') if isinstance(preservation, dict) else None
    if report.get('status') == 'NOT_CLEAN' or preservation_outcome == 'VIOLATED' or deleted:
        return 'VIOLATED'
    if report.get('status') != 'CLEAN' or preservation_outcome != 'SATISFIED':
        return 'UNKNOWN'
    return 'SATISFIED'


def snapshot_from_json(raw: object) -> Snapshot:
    if (not isinstance(raw, dict) or set(raw) != {'schema_version', 'scope_id', 'phase', 'policy_digest', 'surfaces'}
            or type(raw['schema_version']) is not int or raw['schema_version'] != SCHEMA_VERSION
            or not isinstance(raw['scope_id'], str) or not raw['scope_id']
            or raw['phase'] not in ('before', 'after') or not isinstance(raw['policy_digest'], str)
            or not isinstance(raw['surfaces'], dict)):
        raise Refused('malformed controller snapshot')
    surfaces: dict[str, Surface] = {}
    for name, row in raw['surfaces'].items():
        if (not isinstance(name, str) or not isinstance(row, dict)
                or set(row) != {'items', 'complete', 'error', 'deleted_cwds'}
                or type(row['complete']) is not bool or not isinstance(row['items'], dict)
                or row['error'] is not None and not isinstance(row['error'], str)
                or not isinstance(row['deleted_cwds'], list)
                or not all(isinstance(key, str) for key in row['deleted_cwds'])):
            raise Refused('malformed controller surface')
        surface = Surface(row['items'], row['complete'], row['error'], tuple(row['deleted_cwds']))
        if surface.complete and _surface_problem(surface):
            raise Refused('malformed controller surface items')
        surfaces[name] = surface
    return Snapshot(raw['scope_id'], raw['phase'], raw['policy_digest'], surfaces, raw['schema_version'])


def strict_json(data: bytes | str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate inventory JSON key')
            out[key] = value
        return out

    def nonfinite(_value: str) -> Any:
        raise ValueError('non-finite inventory JSON value')
    return json.loads(data, object_pairs_hook=unique, parse_constant=nonfinite)
