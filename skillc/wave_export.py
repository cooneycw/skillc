"""Complete-wave byte custody, not transport, admission or task grading (#630).

The controller catalogue and independently retained expectation are TRUST
INPUTS. Their authentication/custody belongs to a later trusted adapter; a
self-authored manifest or digest is not physical provenance. No participant
catalogue route, host observer, transfer or source-retirement operation exists.
VERIFIED means export integrity only and never changes task outcomes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from . import vm_admission, vm_identity, wave_capture
from .git_snapshot import SafeTree, Unreadable

if TYPE_CHECKING:
    from .calibration import CalibrationDeclaration

MAX_MANIFEST = 4 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MANIFEST = 'manifest.json'
SCOPE = 'complete-wave-export-integrity-only'
Reader = Callable[[Path], SafeTree]
KINDS = {'wave-report', 'role-report', 'transcript', 'capture', 'turn', 'stdout', 'stderr',
         'protocol', 'artifact', 'operator-receipt'}


class ExportRefused(ValueError):
    """No frozen expectation can be established; never a task FAIL."""


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise ExportRefused('wave_export: ' + reason)


def _object(raw: object, keys: set[str], reason: str) -> dict[str, Any]:
    _require(isinstance(raw, dict) and set(raw) == keys, reason)
    assert isinstance(raw, dict)
    return raw


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise ExportRefused('wave_export: invalid metadata') from exc


def _sha(data: bytes) -> str:
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate metadata key')
        result[key] = value
    return result


def _json(data: bytes) -> Any:
    _require(len(data) <= MAX_MANIFEST, 'metadata exceeds bound')
    try:
        result = json.loads(data, object_pairs_hook=_pairs)
        _canonical(result)  # Refuse JSON's nonstandard NaN/Infinity values.
        return result
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ExportRefused('wave_export: unreadable metadata') from exc


def _logical(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value) is not None


def _names(value: object, *, nonempty: bool = False) -> list[str]:
    _require(isinstance(value, list) and (not nonempty or bool(value)), 'invalid population')
    assert isinstance(value, list)
    _require(len(value) <= wave_capture.MAX_ENTRIES and all(_logical(v) for v in value)
             and len(value) == len(set(value)), 'invalid population')
    return value


def _path(value: object, *, root: bool = False) -> str:
    _require(isinstance(value, str), 'invalid path')
    assert isinstance(value, str)
    if root and value == '':
        return value
    parts = PurePosixPath(value).parts
    _require(bool(parts) and not value.startswith('/') and str(PurePosixPath(value)) == value
             and all(p not in ('.', '..') for p in parts) and '\\' not in value
             and not any(ord(c) < 32 for c in value), 'unsafe path')
    return value


def validate_plan(data: Mapping[str, object]) -> dict[str, Any]:
    """The expected population is approved, never derived from arrival bytes."""
    try:
        admission = vm_admission.validate(data)
    except vm_admission.AdmissionRefused as exc:
        raise ExportRefused('wave_export: VM admission declaration is required') from exc
    plan = _object(data.get('wave_export'), {'version', 'waves'}, 'invalid export plan')
    _require(type(plan['version']) is int and plan['version'] == 1, 'invalid plan version')
    _require(isinstance(plan['waves'], list) and bool(plan['waves']), 'missing planned waves')
    ids = []
    for raw in plan['waves']:
        row = _object(raw, {'wave_id', 'roles', 'empty_capture_roles'}, 'invalid planned wave')
        _require(_logical(row['wave_id']), 'invalid planned wave identity')
        roles = _names(row['roles'], nonempty=True)
        _require(set(_names(row['empty_capture_roles'])) <= set(roles), 'unknown empty-capture role')
        ids.append(row['wave_id'])
    _require(ids == admission['planned_waves'], 'planned wave population differs from admission')
    return copy.deepcopy(plan)


@dataclass(frozen=True)
class ControllerCatalogue:
    """Immutable catalogue bytes supplied by the trusted controller, not arrival."""

    data: bytes

    @classmethod
    def from_controller(cls, records: Mapping[str, object]) -> ControllerCatalogue:
        return cls(_canonical(records))


@dataclass(frozen=True)
class FrozenExport:
    """Retain independently from transfer; carries no dispatch permission."""

    manifest_sha256: str
    declaration_digest: str
    plan: bytes
    outcomes: bytes


def _inventory(root: Path, reader: Reader) -> dict[str, Any]:
    tree = reader(root)
    entries: dict[str, Any] = {}

    def walk(rel: str, depth: int) -> None:
        _require(depth <= wave_capture.MAX_DEPTH and len(entries) < wave_capture.MAX_ENTRIES,
                 'payload inventory bound exceeded')
        kind = tree.kind(rel)
        mode = stat.S_IMODE(os.lstat(root / rel).st_mode)
        if kind == 'dir':
            entries[rel] = {'kind': 'directory', 'mode': mode}
            for name, _ in tree.listdir(rel):
                walk(rel + '/' + name if rel else name, depth + 1)
        elif kind == 'file':
            payload, full_mode = tree.read(rel, min(MAX_FILE, wave_capture.MAX_BYTES - tree.bytes_read))
            _require(tree.bytes_read <= wave_capture.MAX_BYTES, 'payload byte bound exceeded')
            entries[rel] = {'kind': 'file', 'mode': stat.S_IMODE(full_mode),
                            'bytes': len(payload), 'sha256': _sha(payload)}
        else:
            raise ExportRefused('wave_export: unsupported payload entry')

    walk('', 0)
    return entries


def _metadata(root: Path, rel: str, reader: Reader) -> Any:
    raw, _ = reader(root).read(rel, MAX_MANIFEST)
    return _json(raw)


def _catalogue(raw: object, plan: dict[str, Any], declaration_digest: str,
               environment: dict[str, Any]) -> dict[str, Any]:
    cat = _object(raw, {'version', 'declaration_digest', 'window_id', 'vm_binding_digest', 'identity_path',
                        'admission_path', 'admission_report', 'waves', 'entries'}, 'invalid controller catalogue')
    _require(type(cat['version']) is int and cat['version'] == 1
             and cat['declaration_digest'] == declaration_digest
             and cat['window_id'] == environment['window']['id'], 'catalogue binding differs')
    entries = cat['entries']
    _require(isinstance(entries, dict) and 0 < len(entries) <= wave_capture.MAX_ENTRIES, 'missing payload census')
    total = 0
    for path, entry in entries.items():
        _path(path, root=True)
        _require(isinstance(entry, dict) and entry.get('kind') in ('file', 'directory'), 'invalid entry kind')
        keys = {'kind', 'mode'} | ({'bytes', 'sha256'} if entry['kind'] == 'file' else set())
        _object(entry, keys, 'invalid entry fields')
        _require(type(entry['mode']) is int and 0 <= entry['mode'] <= 0o7777, 'invalid entry mode')
        if entry['kind'] == 'file':
            _require(type(entry['bytes']) is int and 0 <= entry['bytes'] <= MAX_FILE
                     and isinstance(entry['sha256'], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', entry['sha256']),
                     'invalid entry identity')
            total += entry['bytes']
    _require(total <= wave_capture.MAX_BYTES and entries.get('', {}).get('kind') == 'directory', 'invalid payload root')
    admission = _object(cat['admission_report'], {'version', 'scope', 'authority', 'declaration_digest',
                         'vm_binding_digest', 'window_id', 'waves'}, 'incomplete admission record')
    _require(type(admission['version']) is int and admission['version'] == 1
             and admission['scope'] == 'operator-receipt-binding-and-admission-only'
             and admission['declaration_digest'] == declaration_digest and admission['window_id'] == cat['window_id']
             and admission['vm_binding_digest'] == cat['vm_binding_digest'], 'admission binding differs')
    _require(isinstance(admission['waves'], list) and isinstance(cat['waves'], list), 'missing wave records')
    ids = [r['wave_id'] for r in plan['waves']]
    _require([r.get('wave_id') for r in admission['waves'] if isinstance(r, dict)] == ids
             and len(admission['waves']) == len(ids)
             and [r.get('wave_id') for r in cat['waves'] if isinstance(r, dict)] == ids
             and len(cat['waves']) == len(ids), 'omitted, extra or wrong wave')
    scopes: list[tuple[str, bool]] = []
    for name in ('identity_path', 'admission_path'):
        path = _path(cat[name])
        _require(entries.get(path, {}).get('kind') == 'file', 'missing identity or admission record')
        scopes.append((path, False))
    paths = [cat['identity_path'], cat['admission_path']]
    for wanted, wave, row in zip(plan['waves'], cat['waves'], admission['waves'], strict=True):
        _object(wave, {'wave_id', 'roles', 'task_status', 'records'}, 'invalid wave catalogue')
        _require(wave['roles'] == wanted['roles'] and wave['task_status'] in ('PASS', 'FAIL', 'UNKNOWN'),
                 'role population or task outcome differs')
        _require(type(row.get('nonstart')) is bool and row.get('task_status') == 'UNKNOWN'
                 and type(row.get('dispatch_recorded')) is bool and isinstance(row.get('events'), list)
                 and row['nonstart'] != row['dispatch_recorded']
                 and row['dispatch_recorded'] == ('DISPATCHED' in row['events']), 'invalid admission outcome')
        _require(not row['nonstart'] or wave['task_status'] == 'UNKNOWN', 'nonstart outcome was changed')
        _require(isinstance(wave['records'], list) and bool(wave['records']), 'missing wave records')
        slots: list[tuple[str, str | None]] = []
        record_ids = []
        for item in wave['records']:
            record = _object(item, {'id', 'kind', 'role', 'availability', 'path', 'reason'}, 'invalid record slot')
            _require(_logical(record['id']) and record['kind'] in KINDS, 'invalid record identity')
            role, kind = record['role'], record['kind']
            _require(role in wanted['roles'] if kind not in ('wave-report', 'operator-receipt') else role is None,
                     'wrong record role')
            slots.append((kind, role))
            record_ids.append(record['id'])
            if record['availability'] == 'UNKNOWN':
                _require(kind not in ('wave-report', 'role-report', 'operator-receipt')
                         and record['path'] is None and isinstance(record['reason'], str) and bool(record['reason']),
                         'unrecorded unavailable slot')
            else:
                _require(record['availability'] == 'CAPTURED' and record['reason'] is None, 'invalid availability')
                path = _path(record['path'])
                entry = entries.get(path, {})
                _require(entry.get('kind') in ('file', 'directory') if kind == 'capture'
                         else entry.get('kind') == 'file', 'missing captured record')
                if kind == 'capture':
                    empty = (not any(x.startswith(path + '/') for x in entries)
                             if entry['kind'] == 'directory' else entry['bytes'] == 0)
                    _require(not empty or role in wanted['empty_capture_roles'], 'undeclared empty capture')
                paths.append(path)
                scopes.append((path, kind == 'capture' and entry['kind'] == 'directory'))
            if row['nonstart'] and kind in ('transcript', 'capture'):
                _require(record['availability'] == 'UNKNOWN', 'nonstart invented captured role evidence')
        _require(len(record_ids) == len(set(record_ids)) and slots.count(('wave-report', None)) == 1,
                 'duplicate or missing wave record')
        for role in wanted['roles']:
            _require(all(slots.count((kind, role)) == 1 for kind in ('role-report', 'transcript', 'capture')),
                     'absent, duplicate or incomplete role')
        receipts = row.get('receipts')
        _require(isinstance(receipts, list), 'missing receipt population')
        actual = [entries[r['path']]['sha256'] for r in wave['records'] if r['kind'] == 'operator-receipt']
        _require(sorted(actual) == sorted(r.get('sha256', '') for r in receipts if isinstance(r, dict))
                 and len(actual) == len(receipts), 'omitted or extra operator receipt')
    _require(len(paths) == len(set(paths)), 'record paths overlap')
    for path in entries:
        _require(path == '' or any(path == p or p.startswith(path + '/') or (directory and path.startswith(p + '/'))
                                   for p, directory in scopes), 'uncatalogued payload entry')
    return cat


def _bindings(root: Path, cat: dict[str, Any], environment: dict[str, Any], reader: Reader) -> None:
    identity = _metadata(root, cat['identity_path'], reader)
    expected = {'version': 1, 'scope': 'binding-and-install-match-only', 'status': 'MATCH',
                'vm': environment['vm'], 'skillc_revision': environment['skillc']['revision'],
                'window': environment['window'], 'install_manifest_digest': _sha(_canonical(environment['skillc']['install_manifest']))}
    unavailable = (isinstance(identity, dict)
                   and set(identity) == {'version', 'scope', 'status', 'reason', 'declaration_digest', 'window_id'}
                   and identity['version'] == 1 and identity['scope'] == expected['scope']
                   and identity['status'] == 'UNKNOWN' and isinstance(identity['reason'], str) and bool(identity['reason'])
                   and identity['declaration_digest'] == cat['declaration_digest'] and identity['window_id'] == cat['window_id'])
    _require(isinstance(identity, dict) and type(identity.get('version')) is int
             and (identity == expected or unavailable) and _sha(_canonical(identity)) == cat['vm_binding_digest'],
             'identity record differs')
    _require(_metadata(root, cat['admission_path'], reader) == cat['admission_report'], 'admission record was changed')
    for wave in cat['waves']:
        for record in wave['records']:
            if record['kind'] in ('wave-report', 'role-report', 'operator-receipt'):
                body = _metadata(root, record['path'], reader)
                _require(isinstance(body, dict) and body.get('wave_id') == wave['wave_id'], 'wrong-wave record bytes')
                if record['kind'] == 'wave-report':
                    _require(body.get('status') == wave['task_status'], 'task outcome was changed')
                elif record['kind'] == 'role-report':
                    _require(body.get('role') == record['role'], 'wrong-role record bytes')
                else:
                    _require(body.get('declaration_digest') == cat['declaration_digest']
                             and body.get('vm_binding_digest') == cat['vm_binding_digest']
                             and body.get('window_id') == cat['window_id'], 'operator receipt binding differs')
                    row = next(r for r in cat['admission_report']['waves'] if r['wave_id'] == wave['wave_id'])
                    refs = [r for r in row['receipts'] if r['sha256'] == cat['entries'][record['path']]['sha256']]
                    _require(len(refs) == 1 and body.get('sequence') == refs[0]['sequence']
                             and body.get('check') == refs[0]['check']
                             and body.get('authority') == cat['admission_report']['authority'],
                             'operator receipt provenance join differs')


def _outcomes(cat: dict[str, Any]) -> list[dict[str, Any]]:
    return [{'wave_id': w['wave_id'], 'task_status': w['task_status'], 'nonstart': a['nonstart']}
            for w, a in zip(cat['waves'], cat['admission_report']['waves'], strict=True)]


def freeze(source: Path, declaration: CalibrationDeclaration, catalogue: ControllerCatalogue,
           fresh_manifest_out: Path, *, reader: Reader = SafeTree) -> FrozenExport:
    """Write manifest ONLY to a fresh disjoint output; never copy/retire source.

    Two reads detect ordinary drift, not an atomic freeze. The operator owns
    custody thereafter and chooses/executes transport. No dispatch admission.
    """
    from . import calibration

    _require(isinstance(catalogue, ControllerCatalogue), 'trusted controller catalogue is required')
    try:
        plan = validate_plan(declaration.data)
        provenance = calibration.approval_record_binding(declaration)
        env = vm_identity.validate(declaration.data['execution_environment'])
        cat = _catalogue(_json(catalogue.data), plan, provenance.declaration_digest, env)
        _require(_inventory(source, reader) == cat['entries'], 'source population or bytes differ')
        _bindings(source, cat, env, reader)
        _require(_inventory(source, reader) == cat['entries'], 'source changed during sealing')
        out, src = fresh_manifest_out.resolve(), source.resolve()
        _require(not fresh_manifest_out.is_symlink() and not out.is_relative_to(src) and not src.is_relative_to(out),
                 'manifest output overlaps source or is a link')
        data = _canonical({'version': 1, 'scope': SCOPE, 'declaration': declaration.data,
                           'provenance': asdict(provenance), 'plan': plan, 'catalogue': cat})
        _require(len(data) <= MAX_MANIFEST, 'manifest exceeds bound')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.mkdir(mode=0o700, exist_ok=False)
        fd = os.open(out / MANIFEST, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return FrozenExport(_sha(data), provenance.declaration_digest, _canonical(plan), _canonical(_outcomes(cat)))
    except (OSError, Unreadable, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ExportRefused('wave_export: source or manifest custody unavailable') from exc


def verify_arrival(arrival: Path, expected: FrozenExport, *, reader: Reader = SafeTree) -> dict[str, Any]:
    """Read actual arrival bytes; all lost integrity is export UNKNOWN only."""
    from . import calibration

    _require(isinstance(expected, FrozenExport), 'independently retained expectation is required')
    plan, outcomes = _json(expected.plan), _json(expected.outcomes)
    _object(plan, {'version', 'waves'}, 'invalid retained plan')
    _require(isinstance(plan['waves'], list) and isinstance(outcomes, list) and bool(outcomes),
             'invalid retained population')
    for row in outcomes:
        _object(row, {'wave_id', 'task_status', 'nonstart'}, 'invalid retained outcome')
        _require(_logical(row['wave_id']) and row['task_status'] in ('PASS', 'FAIL', 'UNKNOWN')
                 and type(row['nonstart']) is bool, 'invalid retained outcome')
    _require(all(isinstance(r, dict) and _logical(r.get('wave_id')) for r in plan['waves'])
             and [r['wave_id'] for r in outcomes] == [r['wave_id'] for r in plan['waves']]
             and len(outcomes) == len({r['wave_id'] for r in outcomes}), 'invalid retained population')
    status = 'UNKNOWN'
    try:
        tree = reader(arrival)
        _require(dict(tree.listdir('')) == {MANIFEST: 'file', 'payload': 'dir'}, 'arrival envelope differs')
        raw, mode = tree.read(MANIFEST, MAX_MANIFEST)
        _require(_sha(raw) == expected.manifest_sha256 and stat.S_IMODE(mode) == 0o600, 'manifest identity differs')
        manifest = _object(_json(raw), {'version', 'scope', 'declaration', 'provenance', 'plan', 'catalogue'},
                           'invalid arrival manifest')
        _require(type(manifest['version']) is int and manifest['version'] == 1 and manifest['scope'] == SCOPE,
                 'unsupported manifest')
        declaration = calibration.parse_declaration(manifest['declaration'])
        provenance = calibration.approval_record_binding(declaration)
        _require(provenance.declaration_digest == expected.declaration_digest
                 and asdict(provenance) == manifest['provenance'] and validate_plan(declaration.data) == plan
                 and manifest['plan'] == plan, 'arrival approval or plan binding differs')
        env = vm_identity.validate(declaration.data['execution_environment'])
        cat = _catalogue(manifest['catalogue'], plan, expected.declaration_digest, env)
        _require(_outcomes(cat) == outcomes, 'arrival outcomes changed')
        _require(_inventory(arrival / 'payload', reader) == cat['entries'], 'arrival population or bytes differ')
        _bindings(arrival / 'payload', cat, env, reader)
        _require(_inventory(arrival / 'payload', reader) == cat['entries'], 'arrival changed during verification')
        status = 'VERIFIED'
    except (OSError, Unreadable, ValueError, TypeError, KeyError, RecursionError):
        pass  # A transport receipt, missing evidence or malformed bytes can never certify arrival.
    return {'version': 1, 'scope': SCOPE, 'export_status': status,
            'declaration_digest': expected.declaration_digest, 'manifest_sha256': expected.manifest_sha256,
            'planned': len(outcomes), 'waves': [{**r, 'export_status': status} for r in outcomes]}
