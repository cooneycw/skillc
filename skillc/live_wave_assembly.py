"""Bounded offline assembly of controller-held wave evidence (Refs #620).

Frozen expectations and grader bindings are trusted caller inputs. Neither a
matching digest nor this reader authenticates their provenance or launches work.
The semantic protocol producer is deliberately absent; authored protocol bytes
qualify this boundary only. Missing producer evidence cannot become success.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import controller_turns, live_wave, wave_capture, wave_export, wave_wake_capture
from .git_snapshot import SafeTree, Unreadable

MAX_METADATA = 4 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 256
MAX_VALUE = (1 << 63) - 1


class AssemblyRefused(ValueError):
    """No complete frozen expectation can be established; never task failure."""


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise AssemblyRefused(reason)


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == keys, 'closed assembly object required')
    assert isinstance(value, dict)
    return value


def _name(value: object) -> str:
    _require(type(value) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value) is not None,
             'logical assembly identity required')
    assert isinstance(value, str)
    return value


def _digest(value: object) -> str:
    _require(type(value) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', value) is not None,
             'assembly digest required')
    assert isinstance(value, str)
    return value


def _path(value: object) -> str:
    _require(type(value) is str and 0 < len(value) <= 512, 'bounded relative capture path required')
    assert isinstance(value, str)
    parts = PurePosixPath(value).parts
    _require(not value.startswith('/') and str(PurePosixPath(value)) == value and len(parts) <= 32
             and all(p not in ('.', '..') for p in parts) and '\\' not in value
             and not any(ord(c) < 32 for c in value), 'safe relative capture path required')
    return value


def _integer(value: object, minimum: int = 0, maximum: int = MAX_VALUE) -> int:
    _require(type(value) is int and minimum <= value <= maximum, 'bounded assembly integer required')
    assert isinstance(value, int)
    return value


def _number(value: object, *, positive: bool = False) -> float:
    _require(type(value) in (int, float), 'finite assembly time required')
    assert isinstance(value, (int, float))
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise AssemblyRefused('finite assembly time required') from None
    _require(math.isfinite(number) and 0 <= number <= MAX_VALUE and (not positive or number > 0),
             'finite assembly time required')
    return number


def _optional(value: object, check: Callable[[Any], object]) -> None:
    if value is not None:
        check(value)


def _boolean(value: object) -> None:
    _require(type(value) is bool, 'explicit assembly boolean required')


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate assembly JSON member')
        result[key] = value
    return result


def _canonical(value: object) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise AssemblyRefused('bounded assembly JSON required') from None
    _require(len(raw) <= MAX_METADATA, 'assembly metadata exceeds technical bound')
    return raw


def _json(raw: object) -> Any:
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_METADATA, 'bounded assembly bytes required')
    assert isinstance(raw, bytes)
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise AssemblyRefused('assembly JSON unavailable') from None
    _canonical(value)
    return value


def _reference(raw: object) -> None:
    row = _object(raw, {'slot', 'path', 'sha256', 'size'})
    _name(row['slot'])
    _path(row['path'])
    _digest(row['sha256'])
    _integer(row['size'], 0, MAX_FILE)


def _population(value: object, *, empty: bool = False) -> list[Any]:
    _require(type(value) is list and len(value) <= MAX_ROWS and (empty or bool(value)),
             'explicit bounded assembly population required')
    assert isinstance(value, list)
    return value


def _plan(raw: object) -> live_wave.WavePlan:
    row = _object(raw, {'wave_id', 'roles', 'integrator', 'deadline'})
    names, sessions, attempts = [], [], []
    roles = []
    for raw_role in _population(row['roles']):
        role = _object(raw_role, {'role', 'attempt_id', 'session_id', 'task', 'generation',
                                  'revision', 'nonce', 'required_artifacts'})
        for key in ('role', 'attempt_id', 'task', 'nonce'):
            _name(role[key])
        _optional(role['session_id'], _name)
        _integer(role['generation'])
        _integer(role['revision'], 1)
        artifacts = [_path(p) for p in _population(role['required_artifacts'])]
        _require(len(artifacts) == len(set(artifacts)), 'duplicate required artifact')
        names.append(role['role'])
        attempts.append(role['attempt_id'])
        if role['session_id'] is not None:
            sessions.append(role['session_id'])
        roles.append(live_wave.RoleBinding(**{**role, 'required_artifacts': tuple(artifacts)}))
    _require(len(names) == len(set(names)) and len(attempts) == len(set(attempts))
             and len(sessions) == len(set(sessions)), 'ambiguous frozen role population')
    return live_wave.WavePlan(_name(row['wave_id']), tuple(roles), _name(row['integrator']),
                              _number(row['deadline'], positive=True))


def _contract(value: object, exported: wave_export.FrozenExport) -> dict[str, Any]:
    raw = _object(value, {'version', 'declaration_digest', 'waves'})
    _require(type(raw['version']) is int and raw['version'] == 1, 'assembly version required')
    _require(_digest(raw['declaration_digest']) == exported.declaration_digest, 'export declaration differs')
    expected_plan = _object(_json(exported.plan), {'version', 'waves'})
    export_waves = _population(expected_plan['waves'])
    rows = _population(raw['waves'])
    ids = []
    for row in rows:
        _object(row, {'plan', 'budget_digest', 'clock', 'grader_digest', 'observation', 'roles', 'wake', 'final'})
        plan = _plan(row['plan'])
        ids.append(plan.wave_id)
        _digest(row['budget_digest'])
        _digest(row['grader_digest'])
        _require(row['clock'] in ('monotonic', 'injected-policy-only'), 'declared assembly clock required')
        _optional(row['observation'], _reference)
        roles = _population(row['roles'])
        _require([r.get('role') if type(r) is dict else None for r in roles] == [r.role for r in plan.roles],
                 'frozen capture role population differs')
        for role in roles:
            _object(role, {'role', 'startup', 'observation', 'transcript', 'protocol', 'artifacts'})
            for key in ('startup', 'observation', 'transcript', 'protocol'):
                _optional(role[key], _reference)
            if role['artifacts'] is not None:
                _require(type(role['artifacts']) is dict and len(role['artifacts']) <= MAX_ROWS,
                         'bounded explicit artifact population required')
                for path, ref in role['artifacts'].items():
                    _path(path)
                    _reference(ref)
        if row['wake'] is not None:
            wake = _object(row['wake'], {'root', 'reference', 'context'})
            _path(wake['root'])
            reference = wave_wake_capture.parse_reference(wake['reference'])
            context = wave_wake_capture.parse_context(wake['context'])
            _require(reference.context_digest == context.digest and context.attempt_id == plan.wave_id
                     and context.approved_declaration_digest == raw['declaration_digest']
                     and context.roles == tuple(r.role for r in plan.roles)
                     and context.deadline_digest == row['budget_digest'] and context.clock == row['clock'],
                     'wake context differs from frozen wave')
        if row['final'] is not None:
            final = _object(row['final'], {'root', 'sha256'})
            _path(final['root'])
            _digest(final['sha256'])
    _require(ids == [r.get('wave_id') if type(r) is dict else None for r in export_waves]
             and len(ids) == len(set(ids)), 'original planned wave denominator differs')
    for row, exported_wave in zip(rows, export_waves, strict=True):
        _object(exported_wave, {'wave_id', 'roles', 'empty_capture_roles'})
        _require([r['role'] for r in row['roles']] == exported_wave['roles'], 'export role population differs')
    return raw


@dataclass(frozen=True)
class Expected:
    """Keep separately from arriving bytes; consistency is not approval."""

    data: bytes
    exported: wave_export.FrozenExport


def freeze(value: object, exported: object) -> Expected:
    _require(type(exported) is wave_export.FrozenExport, 'independently held export expectation required')
    assert isinstance(exported, wave_export.FrozenExport)
    _digest(exported.manifest_sha256)
    _digest(exported.declaration_digest)
    _json(exported.outcomes)
    raw = _contract(value, exported)
    return Expected(_canonical(raw), exported)


@dataclass(frozen=True)
class Grader:
    """Trusted caller pins the callable AND its original clock, never a report.

    The hash is a consistency join, not authentication of arbitrary Python code.
    The callable measures its completion in that original clock domain; replay
    cannot manufacture an earlier live grading endpoint.
    """

    digest: str
    budget_digest: str
    clock: str
    grade: live_wave.ArtifactGrader


class _Reader:
    def __init__(self, root: Path, catalogue: dict[str, Any], wave_id: str) -> None:
        self.tree = SafeTree(root)
        self.total = 0
        waves = [w for w in catalogue['waves'] if w['wave_id'] == wave_id]
        _require(len(waves) == 1, 'catalogue wave binding unavailable')
        self.records = waves[0]['records']
        self.entries = catalogue['entries']

    def blob(self, reference: object, role: str | None, kind: str) -> live_wave.Blob | None:
        if reference is None:
            return None
        try:
            _reference(reference)
            assert isinstance(reference, dict)
            slots = [r for r in self.records if r['id'] == reference['slot']]
            _require(len(slots) == 1 and slots[0]['role'] == role and slots[0]['kind'] == kind
                     and slots[0]['availability'] == 'CAPTURED' and slots[0]['path'] == reference['path'],
                     'capture slot role or kind differs')
            entry = self.entries[reference['path']]
            _require(entry['kind'] == 'file' and entry['sha256'] == reference['sha256']
                     and entry['bytes'] == reference['size'], 'capture inventory reference differs')
            raw, _mode = self.tree.read(reference['path'], min(MAX_FILE, MAX_BYTES - self.total))
            self.total += len(raw)
            _require(len(raw) == reference['size'] and self.total <= MAX_BYTES
                     and 'sha256:' + hashlib.sha256(raw).hexdigest() == reference['sha256'],
                     'capture bytes differ from independently held reference')
            return live_wave.Blob(raw, reference['sha256'][7:])
        except (OSError, ValueError, KeyError, TypeError, Unreadable):
            return None

    def metadata(self, reference: object, role: str | None, kind: str) -> dict[str, Any]:
        blob = self.blob(reference, role, kind)
        _require(blob is not None, 'controller observation unavailable')
        assert blob is not None
        return _json(blob.data)

    def capture_root(self, path: str) -> bool:
        return any(r['kind'] == 'capture' and r['availability'] == 'CAPTURED'
                   and (path == r['path'] or path.startswith(r['path'] + '/')) for r in self.records)


def _observation(raw: object, row: dict[str, Any], *, role: live_wave.RoleBinding | None = None) -> dict[str, Any]:
    common = {'version', 'wave_id', 'budget_digest', 'clock'}
    fields = ({'role', 'attempt_id', 'session_id', 'started', 'stopped', 'cleanup_confirmed',
               'capture_complete', 'stop_reason', 'exit_code', 'stop_elapsed', 'tokens', 'wall_seconds'}
              if role is not None else {'status', 'completion_elapsed', 'cleanup_confirmed',
                                       'infrastructure_failed_at', 'deadline_witnessed_at', 'abandonment'})
    obj = _object(raw, common | fields)
    _require(type(obj['version']) is int and obj['version'] == 1
             and obj['wave_id'] == row['plan']['wave_id'] and obj['budget_digest'] == row['budget_digest']
             and obj['clock'] == row['clock'], 'controller observation binding differs')
    _boolean(obj['cleanup_confirmed'])
    if role is not None:
        _require((obj['role'], obj['attempt_id']) == (role.role, role.attempt_id), 'role observation binding differs')
        _optional(obj['session_id'], _name)
        for field in ('started', 'stopped', 'capture_complete'):
            _boolean(obj[field])
        _require(obj['stop_reason'] in ('exited', 'deadline', 'launch-failed', 'infrastructure-cancelled',
                                       'operator-cancelled', 'unavailable'), 'explicit role stop cause required')
        if obj['exit_code'] is not None:
            _integer(obj['exit_code'], -(1 << 31), (1 << 31) - 1)
        _optional(obj['stop_elapsed'], _number)
        _optional(obj['tokens'], _integer)
        _optional(obj['wall_seconds'], _number)
    else:
        _require(obj['status'] in ('PASS', 'FAIL', 'UNKNOWN'), 'closed wave projection status required')
        for field in ('completion_elapsed', 'infrastructure_failed_at', 'deadline_witnessed_at'):
            _optional(obj[field], _number)
        _optional(obj['abandonment'], _boolean)
    return obj


def _grade(binding: object, row: dict[str, Any]) -> live_wave.ArtifactGrader:
    def checked(plan: live_wave.WavePlan, artifacts: Mapping[str, Mapping[str, bytes]]) -> live_wave.DeliveryGrade:
        _require(type(binding) is Grader, 'pinned grader unavailable')
        assert isinstance(binding, Grader)
        _require(binding.digest == row['grader_digest'] and binding.budget_digest == row['budget_digest']
                 and binding.clock == row['clock'] and callable(binding.grade), 'pinned grader or clock differs')
        result = binding.grade(plan, artifacts)
        _require(type(result) is live_wave.DeliveryGrade and result.status in ('PASS', 'FAIL', 'UNKNOWN'),
                 'grader verdict unavailable')
        _optional(result.completed_elapsed, _number)
        _require(type(result.reasons) is tuple, 'grader reason identities required')
        for reason in result.reasons:
            _name(reason)
        return result
    return checked


def _assemble(row: dict[str, Any], payload: Path, grader: object, catalogue: dict[str, Any]) -> dict[str, Any]:
    plan = _plan(row['plan'])
    reader = _Reader(payload, catalogue, plan.wave_id)
    roles = []
    try:
        wave = _observation(reader.metadata(row['observation'], None, 'wave-report'), row)
    except AssemblyRefused:
        wave = {'completion_elapsed': None, 'cleanup_confirmed': False, 'infrastructure_failed_at': None,
                'deadline_witnessed_at': None, 'abandonment': None}
    counts: dict[str, live_wave.PokeCount] = {}
    if row['wake'] is not None:
        try:
            wake = row['wake']
            _require(reader.capture_root(wake['root']), 'wake capture root belongs to another wave')
            counts = {p.role: p for p in wave_wake_capture.poke_counts(
                payload / wake['root'], wave_wake_capture.parse_reference(wake['reference']),
                wave_wake_capture.parse_context(wake['context']))}
        except (ValueError, OSError):
            pass
    final_complete = False
    if row['final'] is not None:
        final = row['final']
        final_complete = (reader.capture_root(final['root'])
                          and wave_capture.verify(payload / final['root'], final['sha256'][7:])['status'] == 'CAPTURED')
    for binding, capture in zip(plan.roles, row['roles'], strict=True):
        try:
            observed = _observation(reader.metadata(capture['observation'], binding.role, 'role-report'), row, role=binding)
        except AssemblyRefused:
            continue
        startup = reader.blob(capture['startup'], binding.role, 'stderr')
        session = controller_turns.session_id_from_header(startup.data) if startup is not None else None
        if session != observed['session_id']:
            session = None
        transcript = reader.blob(capture['transcript'], binding.role, 'transcript')
        protocol = reader.blob(capture['protocol'], binding.role, 'protocol')
        artifacts = None
        if capture['artifacts'] is not None:
            blobs = {name: reader.blob(ref, binding.role, 'artifact') for name, ref in capture['artifacts'].items()}
            if all(b is not None for b in blobs.values()):
                artifacts = {name: b for name, b in blobs.items() if b is not None}
        complete = observed['capture_complete'] and transcript is not None and protocol is not None and artifacts is not None
        roles.append(live_wave.RoleEvidence(binding.role, binding.attempt_id, session, transcript, protocol, artifacts,
            counts.get(binding.role), observed['started'], complete, observed['stopped'], observed['cleanup_confirmed'],
            observed['stop_reason'], observed['exit_code'], observed['stop_elapsed'], observed['tokens'], observed['wall_seconds']))
    evidence = live_wave.WaveEvidence(plan.wave_id, tuple(roles), wave['completion_elapsed'],
        wave['cleanup_confirmed'] and final_complete, wave['infrastructure_failed_at'], wave['deadline_witnessed_at'],
        wave['abandonment'])
    return live_wave.verdict(plan, evidence, _grade(grader, row))


def report(arrival: object, expected: object, graders: object) -> dict[str, Any]:
    """Read-only local replay; frozen inputs are never chosen by projections."""
    _require(type(expected) is Expected, 'independently held assembly expectation required')
    assert isinstance(expected, Expected)
    frozen = freeze(_json(expected.data), expected.exported)
    raw = _json(frozen.data)
    _require(type(arrival) is Path or isinstance(arrival, Path), 'local arrival path required')
    assert isinstance(arrival, Path)
    _require(isinstance(graders, Mapping), 'trusted grader map required')
    assert isinstance(graders, Mapping)
    export = wave_export.verify_arrival(arrival, frozen.exported)
    catalogue = None
    try:
        manifest, _mode = SafeTree(arrival).read(wave_export.MANIFEST, MAX_METADATA)
        _require('sha256:' + hashlib.sha256(manifest).hexdigest() == frozen.exported.manifest_sha256,
                 'independent export manifest identity differs')
        catalogue = _json(manifest)['catalogue']
    except (OSError, ValueError, KeyError, TypeError, Unreadable):
        pass
    waves = []
    for row in raw['waves']:
        try:
            _require(catalogue is not None, 'export catalogue unavailable')
            assert isinstance(catalogue, dict)
            result = _assemble(row, arrival / 'payload', graders.get(row['plan']['wave_id']), catalogue)
        except (OSError, ValueError, KeyError, TypeError, Unreadable, RecursionError):
            result = live_wave.verdict(_plan(row['plan']), None, _grade(None, row))
        if export['export_status'] != 'VERIFIED':
            result['unknown'] = sorted(set(result['unknown']) | {'export-custody-unavailable'})
            if result['status'] == 'PASS':
                result['status'] = 'UNKNOWN'
                result['primary']['completed'] = 0
        waves.append(result)
    return {'version': 1, 'scope': 'offline-controller-capture-assembly-only',
            'declaration_digest': raw['declaration_digest'], 'export_status': export['export_status'],
            'primary': {'unit': 'wave', 'planned': len(waves), 'completed': sum(w['status'] == 'PASS' for w in waves),
                        **{s.lower(): sum(w['status'] == s for w in waves) for s in ('PASS', 'FAIL', 'UNKNOWN')}},
            'waves': waves, 'coverage': {'semantic_protocol_producer': 'caller-supplied-captured-bytes',
                'handoff_timings': 'deferred', 'clutter_lifecycle': 'not-joined', 'live_authority': False}}
