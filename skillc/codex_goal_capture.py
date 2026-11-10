"""Controller-owned goal custody (#637), following wave_wake_capture's pattern.

Independently retained Context and Reference bind append-only, fsynced bytes.
CAPTURED certifies custody, not process stop, declaration approval, model
stability, task delivery, or completeness of a caller's rollout.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_CAPTURE = 64 * 1024 * 1024
# One bounded read beyond the maximum permitted transport frame is retained.
MAX_FRAME = 16 * 1024 * 1024 + 65536
MAX_RECORDS = 65536
ZERO = '0' * 64
KINDS = {'request', 'response', 'goal-state', 'goal-cleared', 'model-rerouted',
         'client-error', 'usage-limited', 'protocol-error'}


class CaptureUnavailable(ValueError):
    """Missing, failed, malformed or misbound goal custody."""


def _text(value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 4000 or '\x00' in value:
        raise CaptureUnavailable('bounded nonempty capture text required')
    return value


def _digest(value: object) -> None:
    if type(value) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}', value) is None:
        raise CaptureUnavailable('capture digest required')


def _integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CaptureUnavailable('bounded capture integer required')
    return value


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise CaptureUnavailable('closed capture object required')
    return value


def _json(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise CaptureUnavailable('JSON capture required') from None


def _hash(raw: bytes) -> str:
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in pairs:
        if key in row:
            raise CaptureUnavailable('duplicate capture member')
        row[key] = value
    return row


@dataclass(frozen=True)
class Context:
    attempt_id: str
    approved_declaration_digest: str
    client_version: str
    model: str
    objective: str
    recorded_token_budget: int

    def __post_init__(self) -> None:
        for value in (self.attempt_id, self.client_version, self.model, self.objective):
            _text(value)
        _digest(self.approved_declaration_digest)
        _integer(self.recorded_token_budget, 1, (1 << 63) - 1)

    @property
    def digest(self) -> str:
        return _hash(_json(asdict(self)))


def parse_context(value: object) -> Context:
    return Context(**_object(value, set(Context.__dataclass_fields__)))


@dataclass(frozen=True)
class Reference:
    version: int
    context_digest: str
    digest: str
    size: int

    def __post_init__(self) -> None:
        _integer(self.version, 1, 1)
        _digest(self.context_digest)
        _digest(self.digest)
        _integer(self.size, 1, MAX_CAPTURE)


def parse_reference(value: object) -> Reference:
    return Reference(**_object(value, set(Reference.__dataclass_fields__)))


def _sync_directory(root: Path) -> None:
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Capture:
    """One exclusive connection/session; a failed write permanently poisons it.

    Seal after the caller stops/drains its contained process. A seal records
    the caller's closure and cannot independently witness that process stop.
    """

    def __init__(self, root: Path, context: Context) -> None:
        if not isinstance(root, Path) or type(context) is not Context:
            raise CaptureUnavailable('owned capture root/context required')
        self.context = parse_context(asdict(context))
        self.root = root
        self.count = self.size = self.events = self.frames = 0
        self.previous = ZERO
        self.failed = self.sealed = self.transport_bound = self.session_bound = False
        root.mkdir(mode=0o700, exist_ok=False)
        (root / 'objects').mkdir(mode=0o700)
        fd = os.open(root / 'events.tmp', os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.stream = os.fdopen(fd, 'w+b', buffering=0)
        try:
            self._append({'kind': 'capture-start', 'version': 1, 'context': asdict(self.context)})
            _sync_directory(root / 'objects')
            _sync_directory(root)
            _sync_directory(root.parent)
        except BaseException:
            self.close()
            raise

    def _append(self, row: dict[str, Any]) -> None:
        try:
            if self.failed or self.sealed or self.count >= MAX_RECORDS:
                raise CaptureUnavailable('capture closed, failed or over record bound')
            raw = _json({'seq': self.count + 1, 'prev_hash': self.previous, **row})
            if self.size + len(raw) > MAX_CAPTURE:
                raise CaptureUnavailable('capture byte bound exceeded')
            if self.stream.write(raw) != len(raw):
                raise CaptureUnavailable('incomplete capture write')
            os.fsync(self.stream.fileno())
            self.count += 1
            self.size += len(raw)
            self.previous = hashlib.sha256(raw).hexdigest()
        except BaseException:
            self.failed = True
            raise

    def bind_transport(self) -> None:
        if self.transport_bound:
            self.failed = True
            raise CaptureUnavailable('exclusive capture transport required')
        self._append({'kind': 'transport-bound'})
        self.transport_bound = True

    def bind_session(self, *, client_version: str, model: str, objective: str, budget: int) -> None:
        for value in (client_version, model, objective):
            _text(value)
        _integer(budget, 1, (1 << 63) - 1)
        if (self.session_bound or not self.transport_bound
                or (client_version, model, objective, budget) != (
                    self.context.client_version, self.context.model,
                    self.context.objective, self.context.recorded_token_budget)):
            self.failed = True
            raise CaptureUnavailable('capture session context differs')
        self._append({'kind': 'session-bound'})
        self.session_bound = True

    def frame(self, direction: str, raw: bytes) -> None:
        try:
            if not self.session_bound:
                raise CaptureUnavailable('bound capture session required')
            _frame(direction, raw)
            self._append({'kind': 'frame', 'direction': direction,
                          'base64': base64.b64encode(raw).decode('ascii')})
            self.frames += 1
        except BaseException:
            self.failed = True
            raise

    def event(self, event: dict[str, Any]) -> None:
        try:
            if not self.session_bound:
                raise CaptureUnavailable('bound capture session required')
            _event(event, self.events + 1)
            self._append({'kind': 'event', 'event': event})
            self.events += 1
        except BaseException:
            self.failed = True
            raise

    def seal(self) -> Reference:
        try:
            if not self.session_bound or not self.events:
                raise CaptureUnavailable('nonempty bound goal capture required')
            self._append({'kind': 'capture-seal', 'records': self.count,
                          'events': self.events, 'frames': self.frames})
            self.sealed = True
            self.stream.seek(0)
            raw = self.stream.read(MAX_CAPTURE + 1)
            self.stream.close()
            ref = Reference(1, self.context.digest, _hash(raw), self.size)
            _decode(raw, ref, self.context)
            target = self.root / 'objects' / ref.digest[7:]
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                if stream.write(raw) != len(raw):
                    raise CaptureUnavailable('incomplete sealed object write')
                stream.flush()
                os.fchmod(stream.fileno(), 0o400)
                os.fsync(stream.fileno())
            _sync_directory(self.root / 'objects')
            _read(self.root, ref)
            (self.root / 'events.tmp').unlink()
            _sync_directory(self.root)
            return ref
        except BaseException:
            self.failed = True
            raise
        finally:
            self.stream.close()

    def close(self) -> None:
        self.failed = True
        self.stream.close()


def _frame(direction: object, raw: object) -> None:
    if (type(direction) is not str or direction not in ('sent', 'received', 'received-partial', 'received-chunk')
            or type(raw) is not bytes or not 0 < len(raw) <= MAX_FRAME
            or direction in ('sent', 'received') and (not raw.endswith(b'\n') or b'\n' in raw[:-1])):
        raise CaptureUnavailable('bounded exact frame or received fragment required')


def _event(value: object, order: int) -> None:
    if (type(value) is not dict or type(value.get('seq')) is not int or value['seq'] != order
            or type(value.get('kind')) is not str or value['kind'] not in KINDS):
        raise CaptureUnavailable('contiguous declared goal event required')
    _json(value)


def _read(root: Path, ref: Reference) -> bytes:
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        objects = os.open('objects', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            fd = os.open(ref.digest[7:], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=objects)
        finally:
            os.close(objects)
    finally:
        os.close(directory)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != ref.size:
            raise CaptureUnavailable('capture object type/size differs')
        raw = stream.read(ref.size + 1)
        after = os.fstat(stream.fileno())
    if (len(raw) != ref.size or _hash(raw) != ref.digest
            or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns)):
        raise CaptureUnavailable('capture object changed or hash differs')
    return raw


def _decode(raw: bytes, ref: Reference, expected: Context) -> dict[str, Any]:
    if (len(raw) != ref.size or _hash(raw) != ref.digest or not raw.endswith(b'\n')
            or ref.context_digest != expected.digest):
        raise CaptureUnavailable('complete bound goal capture required')
    lines = raw.splitlines(keepends=True)
    if not 5 <= len(lines) <= MAX_RECORDS:
        raise CaptureUnavailable('nonempty sealed capture required')
    rows = []
    previous = ZERO
    for index, line in enumerate(lines, 1):
        row = json.loads(line, object_pairs_hook=_pairs)
        if (type(row) is not dict or type(row.get('seq')) is not int or row['seq'] != index
                or row.get('prev_hash') != previous):
            raise CaptureUnavailable('capture chain/order differs')
        previous = hashlib.sha256(line).hexdigest()
        rows.append({key: val for key, val in row.items() if key not in ('seq', 'prev_hash')})
    start = _object(rows[0], {'kind', 'version', 'context'})
    if (start['kind'] != 'capture-start' or type(start['version']) is not int or start['version'] != 1
            or parse_context(start['context']) != expected
            or rows[1] != {'kind': 'transport-bound'} or rows[2] != {'kind': 'session-bound'}):
        raise CaptureUnavailable('capture context/binding differs')
    events: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    for stored in rows[3:-1]:
        if stored.get('kind') == 'event':
            row = _object(stored, {'kind', 'event'})
            _event(row['event'], len(events) + 1)
            events.append(row['event'])
        else:
            row = _object(stored, {'kind', 'direction', 'base64'})
            if row['kind'] != 'frame' or type(row['base64']) is not str:
                raise CaptureUnavailable('declared capture record required')
            frame = base64.b64decode(row['base64'], validate=True)
            _frame(row['direction'], frame)
            frames.append({'direction': row['direction'], 'raw': frame})
    seal = _object(rows[-1], {'kind', 'records', 'events', 'frames'})
    if (seal['kind'] != 'capture-seal' or not events
            or _integer(seal['records'], 1, MAX_RECORDS) != len(rows) - 1
            or _integer(seal['events'], 1, MAX_RECORDS) != len(events)
            or _integer(seal['frames'], 0, MAX_RECORDS) != len(frames)):
        raise CaptureUnavailable('capture seal differs')
    return {'status': 'CAPTURED', 'context_digest': expected.digest, 'events': events, 'frames': frames}


def verify(root: object, reference: object, expected: object) -> dict[str, Any]:
    """Verify independently held bindings; failed/unsealed custody is UNKNOWN."""
    try:
        if not isinstance(root, Path) or type(reference) is not Reference or type(expected) is not Context:
            raise CaptureUnavailable('independently held capture binding required')
        reference = parse_reference(asdict(reference))
        expected = parse_context(asdict(expected))
        return _decode(_read(root, reference), reference, expected)
    except (OSError, ValueError, RecursionError, UnicodeError):
        return {'status': 'UNKNOWN', 'reason': 'goal custody unavailable or unverifiable'}
