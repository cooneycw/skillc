"""Bounded, exact-byte detection over explicit controller-owned surfaces (#630).

References are supplied transient bytes held in memory, never discovered from
the population under test. The root mapping, reader and observation generation
are TRUST INPUTS; this is no host observer or authenticated collection adapter.
CLEAN is conditional on that complete declared scope and the fixed encodings.
It is a release prerequisite, never task credit or #619 zero-clutter evidence.
No export, deletion, teardown, custody or dispatch operation is implemented.
The later stop/cleanup/release controller must compose this with those steps;
wave_export.freeze and leak.scan_path retain their existing behaviour.

No reference bytes, lengths, hashes, excerpts, offsets or paths enter results or
errors. Redacted reprs reduce accidental disclosure; arbitrary Python inspection,
debugger locals and process memory are outside this in-process trust boundary.
There is no claim of cryptographic memory erasure.
"""
from __future__ import annotations

import base64
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_from_bytes

from . import vm_admission, wave_export
from .git_snapshot import SafeTree, Unreadable

if TYPE_CHECKING:
    from .calibration import CalibrationDeclaration

LIMITS = {'entries': 4096, 'depth': 32, 'file_bytes': 8 * 1024 * 1024,
          'total_bytes': 64 * 1024 * 1024}
MAX_REFERENCES = 8
MAX_REFERENCE_BYTES = 64 * 1024
MAX_PATTERN_BYTES = 1024 * 1024
CLASSES = ('staging', 'home', 'vault', 'stdout', 'transcript', 'cache-log', 'export-payload')
ROLE_CLASSES = CLASSES[1:6]
ENCODINGS = ('raw', 'json', 'json-solidus', 'json-second', 'base64', 'base64url',
             'hex', 'percent', 'utf16le', 'utf16be')


class ScanRefused(ValueError):
    """Invalid public declaration; no sensitive input is interpolated."""


def _require(ok: object) -> None:
    if not ok:
        raise ScanRefused('remnant_scan: invalid declared scan policy')


def _logical(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value) is not None


def validate_plan(data: Mapping[str, object]) -> dict[str, Any]:
    """Derive required classes from approved wave/role names, never scan input."""
    try:
        admission = vm_admission.validate(data)
    except vm_admission.AdmissionRefused:
        raise ScanRefused('remnant_scan: VM admission declaration is required') from None
    raw = data.get('remnant_scan')
    _require(isinstance(raw, dict) and set(raw) == {'version', 'waves', 'limits'})
    assert isinstance(raw, dict)
    _require(type(raw['version']) is int and raw['version'] == 1)
    limits = raw['limits']
    _require(isinstance(limits, dict) and set(limits) == set(LIMITS))
    for key, ceiling in LIMITS.items():
        _require(type(limits[key]) is int and 0 < limits[key] <= ceiling)
    waves = raw['waves']
    _require(isinstance(waves, list) and bool(waves))
    ids = []
    count = 1 + int('wave_export' in data)
    normalized = []
    for row in waves:
        _require(isinstance(row, dict) and set(row) == {'wave_id', 'roles'})
        _require(_logical(row['wave_id']))
        roles = row['roles']
        _require(isinstance(roles, list) and bool(roles) and all(_logical(r) for r in roles))
        _require(len(roles) == len(set(roles)))
        ids.append(row['wave_id'])
        normalized.append({'wave_id': row['wave_id'], 'roles': list(roles)})
        count += len(roles) * len(ROLE_CLASSES)
        _require(count <= limits['entries'])
    _require(ids == admission['planned_waves'])
    if 'wave_export' in data:
        try:
            export = wave_export.validate_plan(data)
        except wave_export.ExportRefused:
            raise ScanRefused('remnant_scan: invalid export population') from None
        _require(normalized == [{'wave_id': w['wave_id'], 'roles': w['roles']} for w in export['waves']])
    return {'version': 1, 'waves': normalized, 'limits': dict(limits)}


def surfaces(data: Mapping[str, object]) -> dict[str, str]:
    """Logical private mapping keys; public results only use fixed classes."""
    plan = validate_plan(data)
    out = {'staging': 'staging'}
    for row in plan['waves']:
        for role in row['roles']:
            for kind in ROLE_CLASSES:
                out['/'.join((row['wave_id'], role, kind))] = kind
    if 'wave_export' in data:
        out['export-payload'] = 'export-payload'
    return out


@dataclass(frozen=True, repr=False)
class References:
    """Opaque, explicit memory-only references. No file resolver exists."""

    _values: tuple[bytes, ...] = field(repr=False)

    def __repr__(self) -> str:
        return '<References redacted>'


@dataclass(frozen=True, repr=False)
class _Patterns:
    values: tuple[tuple[str, bytes], ...] = field(repr=False)

    def __repr__(self) -> str:
        return '<Patterns redacted>'


def _compile(references: References) -> _Patterns | None:
    if (not isinstance(references, References) or type(references._values) is not tuple
            or not 0 < len(references._values) <= MAX_REFERENCES
            or any(type(v) is not bytes or not v for v in references._values)
            or sum(map(len, references._values)) > MAX_REFERENCE_BYTES):
        return None
    patterns: set[tuple[str, bytes]] = set()

    def add(kind: str, value: bytes) -> None:
        patterns.add((kind, value))

    for value in references._values:
        add('raw', value)
        for kind, encode in [('base64', base64.b64encode), ('base64url', base64.urlsafe_b64encode)]:
            encoded = encode(value)
            add(kind, encoded)
            add(kind, encoded.rstrip(b'='))
        for encoded in (value.hex().encode(), value.hex().upper().encode()):
            add('hex', encoded)
        percent = quote_from_bytes(value, safe='').encode()
        full = b''.join(b'%%%02X' % b for b in value)
        for encoded in (percent, full):
            add('percent', encoded)
            add('percent', re.sub(rb'%[0-9A-F]{2}', lambda m: m[0].lower(), encoded))
        try:
            text = value.decode('utf-8')
        except UnicodeError:
            continue
        for ascii_only in (True, False):
            escaped = json.dumps(text, ensure_ascii=ascii_only)[1:-1]
            for kind, variant in [('json', escaped), ('json-solidus', escaped.replace('/', r'\/'))]:
                add(kind, variant.encode())
                for second_ascii in (True, False):
                    add('json-second', json.dumps(variant, ensure_ascii=second_ascii)[1:-1].encode())
        add('utf16le', text.encode('utf-16le'))
        add('utf16be', text.encode('utf-16be'))
    if sum(len(value) for _, value in patterns) > MAX_PATTERN_BYTES:
        return None  # Never drop a pattern to fit the budget.
    return _Patterns(tuple(sorted(patterns)))


class BoundedTree(SafeTree):
    """Same no-follow reader, with the stricter scan directory-listing cap."""

    def listdir(self, rel: str) -> list[tuple[str, str]]:
        fd = self._open_dir(self._parts(rel))
        try:
            out = []
            with os.scandir(fd) as entries:
                for entry in entries:
                    self.entries_listed += 1
                    if self.entries_listed > LIMITS['entries']:
                        raise Unreadable('scan directory population exceeds bound')
                    info = entry.stat(follow_symlinks=False)
                    kind = ('file' if stat.S_ISREG(info.st_mode) else
                            'dir' if stat.S_ISDIR(info.st_mode) else 'other')
                    out.append((entry.name, kind))
            return sorted(out)
        finally:
            os.close(fd)


Reader = Callable[[Path], SafeTree]


@dataclass(frozen=True, repr=False)
class ScanResult:
    """Sanitized evidence with a private scope/generation binding, no task grade."""

    status: str
    _public: bytes = field(repr=False)
    _binding: tuple[Any, ...] | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return '<ScanResult ' + self.status + '>'

    def public(self) -> dict[str, Any]:
        return json.loads(self._public)

    def matches(self, declaration: CalibrationDeclaration, roots: Mapping[str, Path],
                generation: object) -> bool:
        """In-process composition guard, not authentication or current freshness."""
        current = _binding(declaration, roots, generation)
        return (self._binding is not None and current is not None
                and self._binding[:-1] == current[:-1] and self._binding[-1] is generation)


def _binding(declaration: CalibrationDeclaration, roots: Mapping[str, Path],
             generation: object) -> tuple[Any, ...] | None:
    from .calibration import DeclarationRefused, approval_record_binding

    try:
        validate_plan(declaration.data)
        if generation is None:
            return None
        approval = approval_record_binding(declaration)
        return (approval.declaration_digest, tuple(sorted((k, os.fspath(v)) for k, v in roots.items())),
                generation)
    except (DeclarationRefused, ScanRefused, TypeError, ValueError):
        return None


def scan(declaration: CalibrationDeclaration, references: References, roots: Mapping[str, Path],
         *, generation: object, reader: Reader = BoundedTree) -> ScanResult:
    """Read all declared surfaces, sanitizing reader errors and counting matches.

    A match takes precedence over UNKNOWN coverage. Missing/unreadable/empty or
    over-bound populations never produce CLEAN. No payload or reference is
    persisted, returned, hashed or interpolated into a diagnostic.
    """
    rows = {kind: {'required': 0, 'complete': 0, 'files': 0, 'matches': 0} for kind in CLASSES}
    encodings = dict.fromkeys(ENCODINGS, 0)
    complete = True
    binding = None
    files = entries = total = 0

    def finish() -> ScanResult:
        matched = sum(encodings.values()) > 0
        status = 'NOT_CLEAN' if matched else 'CLEAN' if complete else 'UNKNOWN'
        public = {'version': 1, 'status': status, 'coverage': 'COMPLETE' if complete else 'UNKNOWN',
                  'classes': rows, 'encodings': encodings}
        return ScanResult(status, json.dumps(public, sort_keys=True).encode(), binding)

    try:
        plan = validate_plan(declaration.data)
        expected = surfaces(declaration.data)
        binding = _binding(declaration, roots, generation)
        patterns = _compile(references)
        for kind in expected.values():
            rows[kind]['required'] += 1
        if binding is None or patterns is None:
            complete = False
            return finish()
        if set(roots) != set(expected):
            complete = False
        paths = [os.path.abspath(os.fspath(roots[key])) for key in expected if key in roots]
        if len(set(paths)) != len(paths):
            complete = False
    except (ScanRefused, TypeError, ValueError, AttributeError):
        complete = False
        return finish()

    def detect(data: bytes, kind: str) -> None:
        for encoding, pattern in patterns.values:
            if pattern in data:
                rows[kind]['matches'] += 1
                encodings[encoding] += 1

    def walk(tree: SafeTree, rel: str, depth: int, kind: str) -> None:
        nonlocal files, entries, total
        entries += 1
        if entries > plan['limits']['entries'] or depth > plan['limits']['depth']:
            raise Unreadable('scan population exceeds bound')
        # Names are part of the population, including binary filesystem names.
        detect(os.fsencode(rel), kind)
        entry_kind = tree.kind(rel)
        if entry_kind == 'dir':
            children = tree.listdir(rel)
            if len(children) + entries > plan['limits']['entries']:
                raise Unreadable('scan population exceeds bound')
            for name, _ in children:
                walk(tree, rel + '/' + name if rel else name, depth + 1, kind)
        elif entry_kind == 'file':
            limit = min(plan['limits']['file_bytes'], plan['limits']['total_bytes'] - total)
            data, _ = tree.read(rel, limit)
            if type(data) is not bytes or len(data) > limit:
                raise Unreadable('scan file exceeds bound')
            total += len(data)
            files += 1
            rows[kind]['files'] += 1
            detect(data, kind)
        else:
            raise Unreadable('scan entry cannot be read')

    for key, kind in expected.items():
        before = files
        try:
            tree = reader(roots[key])
            if tree.kind('') != 'dir':
                raise Unreadable('scan root cannot be read')
            walk(tree, '', 0, kind)
            if files == before:
                raise Unreadable('scan surface has no readable files')
            rows[kind]['complete'] += 1
        except Exception:  # noqa: BLE001 - sanitize the explicit untrusted reader boundary
            # Reader/plugin error text, paths and exception context are private.
            # Keep scanning other surfaces: a known remnant still blocks release.
            complete = False
    return finish()
