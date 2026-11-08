"""Synthetic memory-only references over benign local files. No host operations."""
from __future__ import annotations

import base64
import copy
import json
import os
import secrets
import traceback
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote_from_bytes

import pytest
from conftest import stamp_approval
from test_calibration import ROOT
from test_remnant_scan_declaration import data

from skillc import calibration
from skillc import remnant_scan as rs
from skillc.git_snapshot import Unreadable

CASES = json.loads((ROOT / 'controls/remnant-scan/cases.json').read_text())
ENCODINGS = ('raw', 'json-ascii', 'json-utf8', 'json-solidus', 'json-second',
             'json-second-utf8-ascii', 'json-second-utf8-utf8', 'json-second-solidus',
             'base64', 'base64-unpadded', 'base64url', 'base64url-unpadded',
             'hex-lower', 'hex-upper', 'percent', 'percent-lower', 'percent-full',
             'percent-full-lower', 'utf16le', 'utf16be')


def encode(value: bytes, kind: str) -> bytes:
    """Independent fixture encoders; the production pattern compiler is not used."""
    if kind == 'raw':
        return value
    if kind.startswith('json'):
        escaped = json.dumps(value.decode(), ensure_ascii=kind not in (
            'json-utf8', 'json-second-utf8-ascii', 'json-second-utf8-utf8'))[1:-1]
        if kind in ('json-solidus', 'json-second-solidus'):
            escaped = escaped.replace('/', r'\/')
        if kind.startswith('json-second'):
            escaped = json.dumps(escaped, ensure_ascii=kind != 'json-second-utf8-utf8')[1:-1]
        return escaped.encode()
    if kind.startswith('base64'):
        encoded = (base64.urlsafe_b64encode if kind.startswith('base64url') else base64.b64encode)(value)
        return encoded.rstrip(b'=') if kind.endswith('unpadded') else encoded
    if kind.startswith('hex'):
        return (value.hex().upper() if kind.endswith('upper') else value.hex()).encode()
    if kind.startswith('percent'):
        percent = (''.join(f'%{b:02X}' for b in value) if 'full' in kind
                   else quote_from_bytes(value, safe=''))
        if kind.endswith('lower'):
            # Lowercase escape digits only, not unescaped reference bytes.
            import re
            percent = re.sub(r'%[0-9A-F]{2}', lambda m: m[0].lower(), percent)
        return percent.encode()
    return value.decode().encode('utf-16le' if kind == 'utf16le' else 'utf-16be')


@dataclass(repr=False)
class OutputAudit:
    refs: list[rs.References] = field(default_factory=list, repr=False)

    def __repr__(self) -> str:
        return '<OutputAudit redacted>'


ACTIVE_AUDIT: ContextVar[OutputAudit | None] = ContextVar('remnant_test_output_audit', default=None)


@pytest.fixture(autouse=True)
def audit_captured_output(capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Audit every test's captured stdout, stderr and logs against its references."""
    audit = OutputAudit()
    token = ACTIVE_AUDIT.set(audit)
    try:
        yield
    finally:
        output = PrivateOutput(''.join(capsys.readouterr()).encode() + caplog.text.encode())
        ACTIVE_AUDIT.reset(token)
        for refs in audit.refs:
            no_marker(output.data, refs)


def references(*, binary: bool = False, filename: bool = False) -> rs.References:
    # Random values are not test IDs, assertion parameters, files or diagnostics.
    value = b'SYNTHETIC_ONLY_' + secrets.token_hex(20).encode()
    value += b'\xff' if filename else b'"/\\\x00' + (b'\xff\xfb' if binary else '\u00e9'.encode())
    refs = rs.References((value,))
    audit = ACTIVE_AUDIT.get()
    if audit is not None:
        audit.refs.append(refs)
    return refs


def _contains_marker(output: bytes, refs: rs.References) -> bool:
    # Independent of rs._compile: this audit must also see Python's diagnostic
    # renderings, and must not share a production compiler blind spot.
    for value in refs._values:
        variants = {value}
        for kind in ENCODINGS:
            try:
                variants.add(encode(value, kind))
            except UnicodeError:
                pass  # JSON/UTF-16 require a valid UTF-8 reference.
        for variant in variants:
            forms = {variant, repr(variant).encode(), repr(variant)[2:-1].encode()}
            # Both Python quote styles and ASCII escaping of bytes/text.
            escaped_bytes = variant.decode('latin-1').encode('unicode_escape').decode()
            for quote in ("'", '"'):
                interior = escaped_bytes.replace(quote, '\\' + quote)
                forms.update((interior.encode(), ('b' + quote + interior + quote).encode()))
            for decoding in ('utf-8', 'latin-1'):
                try:
                    text = variant.decode(decoding)
                except UnicodeError:
                    continue
                forms.update((repr(text).encode(), repr(text)[1:-1].encode(),
                              ascii(text).encode(), ascii(text)[1:-1].encode(),
                              text.encode('unicode_escape')))
                for quote in ("'", '"'):
                    interior = text.encode('unicode_escape').decode().replace(quote, '\\' + quote)
                    forms.update((interior.encode(), (quote + interior + quote).encode()))
                for ascii_only in (True, False):
                    escaped = json.dumps(text, ensure_ascii=ascii_only)
                    forms.update((escaped.encode(), escaped[1:-1].encode()))
            if any(form and form in output for form in forms):
                return True
    return False


def no_marker(output: bytes, refs: rs.References) -> None:
    leaked = _contains_marker(output, refs)
    output = b''  # The rejecting assertion's own traceback must stay sanitized.
    if leaked:
        raise AssertionError('privacy control refused')


@dataclass(repr=False)
class Fixture:
    declaration: calibration.CalibrationDeclaration
    roots: dict[str, Path] = field(repr=False)
    refs: rs.References = field(repr=False)
    generation: object = field(default_factory=object, repr=False)
    planted_key: str | None = field(default=None, repr=False)
    planted_encoding: str = 'raw'
    bad_read: str | None = None
    bad_listing: str | None = None
    filename: bool = False

    def __repr__(self) -> str:
        return '<SyntheticFixture redacted>'

    def reader(self, root: Path) -> rs.BoundedTree:
        fixture = self

        class Overlay(rs.BoundedTree):
            def __repr__(self) -> str:
                return '<Overlay redacted>'

            def listdir(self, rel: str) -> list[tuple[str, str]]:
                if fixture.bad_listing is not None and root == fixture.roots[fixture.bad_listing]:
                    raise Unreadable('synthetic partial listing')
                if fixture.filename and fixture.planted_key is not None and root == fixture.roots[fixture.planted_key]:
                    return [(os.fsdecode(encode(fixture.refs._values[0], fixture.planted_encoding)), 'file')]
                return super().listdir(rel)

            def kind(self, rel: str) -> str:
                if fixture.filename:
                    return 'file' if rel else 'dir'
                return super().kind(rel)

            def read(self, rel: str, limit: int = rs.LIMITS['file_bytes']) -> tuple[bytes, int]:
                if fixture.bad_read is not None and root == fixture.roots[fixture.bad_read]:
                    # Even exception strings containing a marker must be suppressed.
                    raise PermissionError(fixture.refs._values[0])
                if fixture.planted_key is not None and root == fixture.roots[fixture.planted_key]:
                    payload = b'\x00\xffprefix\x00' + encode(fixture.refs._values[0], fixture.planted_encoding) + b'\x00suffix'
                    return payload, 0o100600
                return super().read(rel, limit)

        return Overlay(root)

    def run(self) -> rs.ScanResult:
        return rs.scan(self.declaration, self.refs, self.roots, generation=self.generation, reader=self.reader)


def fixture(tmp_path: Path, *, export: bool = True, binary: bool = False) -> Fixture:
    raw = data()
    if export:
        raw['wave_export'] = json.loads((ROOT / 'controls/wave-export/plan.json').read_text())['wave_export']
    decl = calibration.parse_declaration(stamp_approval(raw))
    roots = {}
    for index, key in enumerate(rs.surfaces(decl.data)):
        root = tmp_path / str(index)
        root.mkdir(parents=True)
        (root / 'benign.txt').write_bytes(b'benign allowed file\n')
        roots[key] = root
    return Fixture(decl, roots, references(binary=binary))


def apply(case: dict[str, Any], f: Fixture) -> None:
    action = case['action']
    keys = list(f.roots)
    if action == 'plant':
        f.planted_key = next(k for k, c in rs.surfaces(f.declaration.data).items() if c == case['class'])
        f.planted_encoding = case['encoding']
    elif action == 'omit':
        del f.roots[keys[0]]
    elif action == 'empty':
        (f.roots[keys[0]] / 'benign.txt').unlink()
    elif action == 'unreadable':
        f.bad_read = keys[0]
    elif action == 'partial':
        f.bad_listing = keys[0]
    elif action == 'empty-references':
        f.refs = rs.References(())
    elif action == 'missing':
        f.roots[keys[0]] = f.roots[keys[0]] / 'missing'
    elif action == 'extra':
        f.roots['extra'] = f.roots[keys[0]]
    elif action == 'alias':
        f.roots[keys[0]] = f.roots[keys[1]]
    elif action == 'symlink':
        (f.roots[keys[0]] / 'link').symlink_to('benign.txt')
    elif action == 'fifo':
        os.mkfifo(f.roots[keys[0]] / 'pipe')
    elif action.endswith('-bound'):
        raw: dict[str, Any] = copy.deepcopy(dict(f.declaration.data))
        name = {'file-bound': 'file_bytes', 'total-bound': 'total_bytes',
                'entry-bound': 'entries', 'depth-bound': 'depth'}[action]
        raw['remnant_scan']['limits'][name] = 1 if name != 'entries' else len(f.roots)
        f.declaration = calibration.parse_declaration(stamp_approval(raw))
        if action == 'depth-bound':
            nested = f.roots[keys[0]] / 'nested'
            nested.mkdir()
            (nested / 'deep.txt').write_bytes(b'benign')


@pytest.mark.parametrize('case', CASES['cases'], ids=lambda c: c['name'])
def test_committed_cases(tmp_path: Path, case: dict[str, Any]) -> None:
    f = fixture(tmp_path, binary=case.get('binary', False))
    apply(case, f)
    result = f.run()
    assert result.status == case['expected']
    no_marker(json.dumps(result.public()).encode(), f.refs)


@pytest.mark.parametrize('encoding', ENCODINGS)
def test_fixed_encodings_are_detected(tmp_path: Path, encoding: str) -> None:
    f = fixture(tmp_path)
    f.planted_key = 'staging'
    f.planted_encoding = encoding
    assert f.run().status == 'NOT_CLEAN'


@pytest.mark.parametrize('kind', rs.CLASSES)
def test_every_role_surface_is_scanned(tmp_path: Path, kind: str) -> None:
    f = fixture(tmp_path)
    for key, surface_class in rs.surfaces(f.declaration.data).items():
        if surface_class == kind:
            f.planted_key = key
            assert f.run().status == 'NOT_CLEAN'


def test_known_remnant_takes_precedence_over_missing_coverage(tmp_path: Path) -> None:
    f = fixture(tmp_path)
    f.planted_key = 'staging'
    del f.roots[next(k for k in f.roots if k != 'staging')]
    result = f.run()
    assert result.status == 'NOT_CLEAN' and result.public()['coverage'] == 'UNKNOWN'


@pytest.mark.parametrize('encoding', ['raw', 'hex-lower'])
def test_filename_bytes_are_scanned_in_memory(tmp_path: Path, encoding: str) -> None:
    f = fixture(tmp_path)
    f.refs = references(filename=True)
    f.planted_key = 'staging';f.filename = True;f.planted_encoding = encoding
    assert f.run().status == 'NOT_CLEAN'


@pytest.mark.parametrize('invalid', ['empty-value', 'many', 'bytes', 'patterns', 'wrong-type'])
def test_reference_and_pattern_bounds_are_unknown(tmp_path: Path, invalid: str) -> None:
    f = fixture(tmp_path)
    if invalid == 'empty-value':
        f.refs = rs.References((b'',))
    elif invalid == 'many':
        f.refs = rs.References((b'benign',) * 9)
    elif invalid == 'bytes':
        f.refs = rs.References((b'x' * (rs.MAX_REFERENCE_BYTES + 1),))
    elif invalid == 'patterns':
        f.refs = rs.References((b'\x00' * rs.MAX_REFERENCE_BYTES,))
    else:
        f.refs = rs.References(('invalid',))  # type: ignore[arg-type]
    assert f.run().status == 'UNKNOWN'


def test_clean_complete_scope_preserves_benign_files_and_modes(tmp_path: Path) -> None:
    f = fixture(tmp_path, export=False)
    before = {p: (p.read_bytes(), p.stat().st_mode) for root in f.roots.values() for p in root.iterdir()}
    result = f.run()
    assert result.status == 'CLEAN' and result.public()['coverage'] == 'COMPLETE'
    assert result.matches(f.declaration, f.roots, f.generation)
    assert not result.matches(f.declaration, f.roots, object())
    changed = dict(f.roots);changed['staging'] = tmp_path / 'different'
    assert not result.matches(f.declaration, changed, f.generation)
    assert before == {p: (p.read_bytes(), p.stat().st_mode) for root in f.roots.values() for p in root.iterdir()}


def qualify(checker: Callable[[Fixture], str], tmp_path: Path) -> None:
    for case in CASES['cases']:
        f = fixture(tmp_path / case['name'], binary=case.get('binary', False))
        apply(case, f)
        if checker(f) != case['expected']:
            raise AssertionError('detector qualification refused: ' + case['name'])


def test_detector_qualification(tmp_path: Path) -> None:
    qualify(lambda f: f.run().status, tmp_path)


@pytest.mark.parametrize('control', CASES['qualification_controls'], ids=lambda c: c['checker'])
def test_committed_blind_checker_controls(tmp_path: Path, control: dict[str, str]) -> None:
    def blind(f: Fixture) -> str:
        if control['checker'] == 'always-clean':
            return 'CLEAN'
        # Mutate the expected census itself, as well as the supplied population.
        # A detector which forgets this required class loses its planted witness.
        expected = rs.surfaces(f.declaration.data)
        expected.pop('staging')
        f.roots.pop('staging')
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(rs, 'surfaces', lambda _data: expected)
            return f.run().status

    with pytest.raises(AssertionError, match=control['witness']):
        qualify(blind, tmp_path)


@dataclass(repr=False)
class PrivateOutput:
    data: bytes = field(repr=False)

    def __repr__(self) -> str:
        return '<PrivateOutput redacted>'


def force_failure(f: Fixture, *, leak: str | None = None) -> PrivateOutput:
    """A clean twin and intentional unsafe locals, always captured in memory."""
    private_local = (f.refs._values[0] if leak == 'bytes' else
                     f.refs._values[0].decode() if leak == 'str' else '<redacted>')
    result = f.run()
    try:
        assert result.status == 'CLEAN', 'intentional privacy-control failure'
    except AssertionError as error:
        captured = PrivateOutput(''.join(traceback.TracebackException.from_exception(
            error, capture_locals=True).format()).encode())
        del private_local  # Do not retain the raw witness in an escaping frame.
        return captured
    raise AssertionError('privacy control did not fail')


def test_forced_assertion_failure_cannot_disclose_marker(tmp_path: Path) -> None:
    f = fixture(tmp_path)
    f.planted_key = 'staging'
    output = force_failure(f)
    assert b'intentional privacy-control failure' in output.data
    no_marker(output.data, f.refs)
    no_marker(repr(f.refs).encode(), f.refs)
    no_marker(repr(rs._compile(f.refs)).encode(), f.refs)
    assert b'ScanResult NOT_CLEAN' in output.data and b'SyntheticFixture redacted' in output.data
    with pytest.raises(AssertionError, match='privacy control refused'):
        no_marker(f.refs._values[0], f.refs)


@pytest.mark.parametrize('leak', ['bytes', 'str'])
def test_private_output_audit_rejects_captured_local_disclosure(tmp_path: Path, leak: str) -> None:
    f = fixture(tmp_path);f.planted_key = 'staging'
    output = force_failure(f, leak=leak)
    with pytest.raises(AssertionError, match='privacy control refused'):
        no_marker(output.data, f.refs)
    no_marker(force_failure(f).data, f.refs)


@pytest.mark.parametrize('encoding', ENCODINGS)
def test_private_output_audit_rejects_all_detector_encodings(encoding: str) -> None:
    refs = references()
    output = PrivateOutput(encode(refs._values[0], encoding))
    with pytest.raises(AssertionError, match='privacy control refused'):
        no_marker(output.data, refs)


@pytest.mark.parametrize('kind', ['bytes-repr', 'str-repr', 'str-ascii', 'str-unicode-escape',
                                 'bytes-double-quote', 'str-double-quote'])
def test_private_output_audit_rejects_python_diagnostic_forms(kind: str) -> None:
    refs = references()
    if kind == 'bytes-repr':
        output = PrivateOutput(repr(refs._values[0]).encode())
    elif kind == 'str-repr':
        output = PrivateOutput(repr(refs._values[0].decode()).encode())
    elif kind == 'str-ascii':
        output = PrivateOutput(ascii(refs._values[0].decode()).encode())
    elif kind == 'str-unicode-escape':
        output = PrivateOutput(refs._values[0].decode().encode('unicode_escape'))
    elif kind == 'bytes-double-quote':
        output = PrivateOutput(b'b"' + refs._values[0].decode('latin-1').encode(
            'unicode_escape').replace(b'"', b'\\"') + b'"')
    else:
        output = PrivateOutput(b'"' + refs._values[0].decode().encode(
            'unicode_escape').replace(b'"', b'\\"') + b'"')
    with pytest.raises(AssertionError, match='privacy control refused'):
        no_marker(output.data, refs)


def test_literal_only_audit_blind_mutant_accepts_the_leaked_witness(tmp_path: Path) -> None:
    f = fixture(tmp_path);f.planted_key = 'staging'
    output = force_failure(f, leak='bytes')
    # Exact old no_marker predicate. No leak output or value enters an assertion.
    accepted_by_old_audit = not any(value in output.data for value in f.refs._values)
    assert accepted_by_old_audit
    with pytest.raises(AssertionError, match='privacy control refused'):
        no_marker(output.data, f.refs)


def test_overlay_never_persists_references(tmp_path: Path) -> None:
    f = fixture(tmp_path)
    for key in f.roots:
        f.planted_key = key
        assert f.run().status == 'NOT_CLEAN'
    for root in f.roots.values():
        assert sorted(p.name for p in root.iterdir()) == ['benign.txt']
        for path in root.iterdir():
            no_marker(path.read_bytes(), f.refs)
            assert path.read_bytes() == b'benign allowed file\n'


def test_error_text_is_not_a_public_diagnostic(tmp_path: Path) -> None:
    f = fixture(tmp_path)
    f.bad_read = 'staging'
    result = f.run()
    assert result.status == 'UNKNOWN'
    no_marker(json.dumps(result.public()).encode(), f.refs)


def test_public_projection_has_only_fixed_keys_and_counts(tmp_path: Path) -> None:
    f = fixture(tmp_path);f.planted_key = 'staging'
    result = f.run().public()
    assert set(result) == {'version', 'status', 'coverage', 'classes', 'encodings'}
    assert set(result['classes']) == set(rs.CLASSES) and set(result['encodings']) == set(rs.ENCODINGS)
    for row in result['classes'].values():
        assert set(row) == {'required', 'complete', 'files', 'matches'}
        assert all(type(v) is int and v >= 0 for v in row.values())
    assert all(type(v) is int and v >= 0 for v in result['encodings'].values())
    assert not any(str(root) in json.dumps(result) for root in f.roots.values())


def test_unapproved_or_modified_scope_is_unknown(tmp_path: Path) -> None:
    f = fixture(tmp_path)
    f.declaration.data['remnant_scan']['limits']['depth'] -= 1  # type: ignore[index]
    assert f.run().status == 'UNKNOWN'
