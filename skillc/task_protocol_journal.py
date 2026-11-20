"""Controller-held custody for the task-protocol stream (#620 PR-B, B2).

See `docs/specs/evaluation-facility/task-protocol-stream.md`, section 3, and
decision 7's limits, accepted 2026-11-17. This module is the ordered journal
only: it assigns the global sequence and the controller's integer elapsed
nanoseconds under one lock, makes every record durable before returning, seals
the result as a read-only content-addressed object, and verifies it later
against an independently held `Reference` and `Context`.

CUSTODY, NOT TRUTH. A verified journal proves which records the controller
wrote, in which order, and that nothing was altered, truncated, reordered or
bound to another attempt. It does not decide whether an ack was valid or a
completion was correct; B3's state machine and the independent artifact grader
own those. This module checks record SHAPE and closed field sets, and leaves
the protocol vocabulary to its callers.

DURABLE BEFORE ANY RECEIPT. `append` writes one canonical newline record and
fsyncs the file (and, for the first record, the directory) before it returns.
A failed or short write or fsync POISONS the journal: it raises, and every
later append raises, so no successful receipt can follow an uncommitted
decision. Capacity is different: a full journal refuses the append with
`CapacityExceeded`, stays healthy, and keeps a reserve so the caller can still
record the capacity event, revocations, the fence and the seal. A capacity
event makes coverage UNKNOWN; it is not a task, time or token cap.

The verifier returns UNKNOWN for anything it cannot prove, never a partial pass.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

VERSION = 1
ZERO = "0" * 64
#: Decision 7's defaults, bound into every `Context` digest.
DEFAULT_LIMITS = {
    "request_bytes": 4096,
    "decisions_per_principal": 256,
    "max_bytes": 64 * 1024 * 1024,
    "max_records": 32768,
    "closure_reserve_records": 256,
    "closure_reserve_bytes": 256 * 1024,
}
_LIMIT_CEILING = {
    "request_bytes": 1 << 20, "decisions_per_principal": 1 << 16, "max_bytes": 1 << 30,
    "max_records": 1 << 20, "closure_reserve_records": 1 << 16, "closure_reserve_bytes": 1 << 24,
}

COMMON = frozenset({"seq", "prev_hash", "kind", "elapsed_ns"})
#: Closed field sets per record kind. Values are checked by `_check_row`.
KINDS: dict[str, frozenset[str]] = {
    "capture-start": frozenset({"version", "context"}),
    "binding": frozenset({"principal", "evidence_digest"}),
    "barrier": frozenset({"bindings_digest", "slots"}),
    "decision": frozenset({"principal", "request", "op", "offer_id", "request_digest",
                           "decision", "reason"}),
    "retry": frozenset({"principal", "request", "request_digest", "original_seq"}),
    "rejection": frozenset({"principal", "reason", "length", "content_digest"}),
    "revocation": frozenset({"principal", "reason"}),
    "capacity": frozenset({"principal", "scope"}),
    "fence": frozenset({"reason"}),
    "capture-seal": frozenset({"records", "last_hash", "coverage", "outcome"}),
}
#: Kinds counted against `decisions_per_principal`.
COUNTED = frozenset({"decision", "retry", "rejection"})
#: Kinds that may draw on the closure reserve.
CLOSURE = frozenset({"revocation", "capacity", "fence", "capture-seal"})
#: Kinds still accepted after a fence; a late request is a rejection row.
AFTER_FENCE = frozenset({"rejection", "revocation", "capacity", "fence", "capture-seal"})
SLOT_STATES = ("bound", "unstarted", "unavailable")
CAPACITY_SCOPES = ("records", "bytes", "principal")
COVERAGE = ("complete", "unknown")
OUTCOMES = ("CLOSED", "UNKNOWN")

_TOKEN = re.compile(r"[a-z][a-z0-9-]{0,63}")
_PRINCIPAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_HEX = re.compile(r"[0-9a-f]{64}")
_MAX_INT = (1 << 63) - 1


class JournalUnavailable(ValueError):
    """Custody cannot be established or continued. Never a task failure."""


class CapacityExceeded(JournalUnavailable):
    """The append would exceed a declared limit. The journal stays healthy."""


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise JournalUnavailable(reason)


def _int(value: object, minimum: int = 0, maximum: int = _MAX_INT) -> int:
    _require(type(value) is int and minimum <= value <= maximum, "bounded integer required")
    assert isinstance(value, int)
    return value


def _hex(value: object) -> str:
    _require(type(value) is str and _HEX.fullmatch(value), "sha256 hex required")
    assert isinstance(value, str)
    return value


def _ref_digest(value: object) -> str:
    _require(type(value) is str and value.startswith("sha256:"), "sha256 reference required")
    assert isinstance(value, str)
    return "sha256:" + _hex(value[7:])


def _token(value: object) -> str:
    _require(type(value) is str and _TOKEN.fullmatch(value), "closed token required")
    assert isinstance(value, str)
    return value


def _principal(value: object) -> str:
    _require(type(value) is str and _PRINCIPAL.fullmatch(value), "principal reference required")
    assert isinstance(value, str)
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise JournalUnavailable("canonical record required") from None


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in out, "duplicate record field")
        out[key] = value
    return out


@dataclass(frozen=True)
class Context:
    """What the journal is bound to. The caller holds it independently and
    hands the same value to `verify`; a journal for another attempt, another
    population or other limits does not verify against it."""

    attempt_id: str
    declaration_digest: str
    population_digest: str
    deadline_digest: str
    producer_version: str
    principals: tuple[str, ...]
    clock: str = "monotonic-ns"
    limits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LIMITS))

    def __post_init__(self) -> None:
        _principal(self.attempt_id)
        for value in (self.declaration_digest, self.population_digest, self.deadline_digest):
            _ref_digest(value)
        _require(type(self.producer_version) is str
                 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", self.producer_version),
                 "producer version required")
        _require(type(self.principals) is tuple and self.principals
                 and len(set(self.principals)) == len(self.principals),
                 "nonempty unique planned principals required")
        for principal in self.principals:
            _principal(principal)
        _require(self.clock == "monotonic-ns", "controller monotonic clock required")
        _require(type(self.limits) is dict and set(self.limits) == set(DEFAULT_LIMITS),
                 "complete declared limits required")
        for key, value in self.limits.items():
            _int(value, 1, _LIMIT_CEILING[key])
        _require(self.limits["closure_reserve_records"] < self.limits["max_records"]
                 and self.limits["closure_reserve_bytes"] < self.limits["max_bytes"],
                 "closure reserve must leave capacity")
        _require(len(self.principals) <= self.limits["max_records"], "population over bound")

    def fields(self) -> dict[str, Any]:
        return {**asdict(self), "principals": list(self.principals)}

    @property
    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(_canonical(self.fields())).hexdigest()


def parse_context(value: object) -> Context:
    _require(type(value) is dict and set(value) == set(Context.__dataclass_fields__),
             "closed context required")
    assert isinstance(value, dict)
    _require(type(value["principals"]) is list, "principal list required")
    _require(type(value["limits"]) is dict, "limits required")
    return Context(**{**value, "principals": tuple(value["principals"]),
                      "limits": dict(value["limits"])})


@dataclass(frozen=True)
class Reference:
    """Held by the caller apart from the journal directory."""

    version: int
    context_digest: str
    digest: str
    size: int
    records: int

    def __post_init__(self) -> None:
        _require(type(self.version) is int and self.version == VERSION, "reference version")
        _ref_digest(self.context_digest)
        _ref_digest(self.digest)
        _int(self.size, 1)
        _int(self.records, 2)


def parse_reference(value: object) -> Reference:
    _require(type(value) is dict and set(value) == set(Reference.__dataclass_fields__),
             "closed reference required")
    assert isinstance(value, dict)
    return Reference(**value)


def _check_row(row: dict[str, Any], context: Context) -> None:
    """Closed shape for one stored record, including its common fields."""
    kind = row.get("kind")
    _require(type(kind) is str and kind in KINDS, "declared record kind required")
    assert isinstance(kind, str)
    _require(set(row) == COMMON | KINDS[kind], "closed record fields required")
    _int(row["seq"], 1)
    _hex(row["prev_hash"])
    _int(row["elapsed_ns"])
    planned = set(context.principals)

    def member(value: object, *, optional: bool = False) -> None:
        if optional and value is None:
            return
        _require(_principal(value) in planned, "planned principal required")

    if kind == "capture-start":
        _require(type(row["version"]) is int and row["version"] == VERSION, "journal version")
        _require(parse_context(row["context"]) == context, "journal bound to another context")
    elif kind == "binding":
        member(row["principal"])
        _ref_digest(row["evidence_digest"])
    elif kind == "barrier":
        _ref_digest(row["bindings_digest"])
        slots = row["slots"]
        _require(type(slots) is list and len(slots) == len(context.principals),
                 "complete barrier population required")
        for name, slot in zip(context.principals, slots, strict=True):
            _require(type(slot) is dict and set(slot) == {"principal", "state"}
                     and slot["principal"] == name and slot["state"] in SLOT_STATES,
                     "barrier slot in planned order required")
    elif kind == "decision":
        member(row["principal"])
        _int(row["request"], 1)
        _token(row["op"])
        if row["offer_id"] is not None:
            _principal(row["offer_id"])
        _ref_digest(row["request_digest"])
        _token(row["decision"])
        if row["reason"] is not None:
            _token(row["reason"])
    elif kind == "retry":
        member(row["principal"])
        _int(row["request"], 1)
        _ref_digest(row["request_digest"])
        _int(row["original_seq"], 1)
    elif kind == "rejection":
        member(row["principal"], optional=True)
        _token(row["reason"])
        _int(row["length"])
        _ref_digest(row["content_digest"])
    elif kind == "revocation":
        member(row["principal"])
        _token(row["reason"])
    elif kind == "capacity":
        member(row["principal"], optional=True)
        _require(row["scope"] in CAPACITY_SCOPES, "declared capacity scope required")
    elif kind == "fence":
        _token(row["reason"])
    elif kind == "capture-seal":
        _int(row["records"])
        _hex(row["last_hash"])
        coverage = row["coverage"]
        _require(type(coverage) is dict and set(coverage) == planned
                 and all(v in COVERAGE for v in coverage.values()),
                 "complete per-principal coverage required")
        _require(row["outcome"] in OUTCOMES, "declared seal outcome required")


class _Os:
    """The only filesystem calls the writer makes, so a test can fail one."""

    write = staticmethod(os.write)
    fsync = staticmethod(os.fsync)


class Journal:
    """Single-use private writer for one planned attempt.

    `origin_ns` is the attempt's ONE common monotonic origin, established
    before launch; no resume, reconnect or retry restarts it. `clock_ns`
    defaults to `time.monotonic_ns` and is injectable for tests only."""

    def __init__(self, root: Path, context: Context, origin_ns: int, *,
                 clock_ns: Callable[[], int] = time.monotonic_ns, fs: Any = None) -> None:
        _require(isinstance(root, Path) and type(context) is Context, "owned root/context required")
        self.context = parse_context(context.fields())
        self.origin_ns = _int(origin_ns)
        self.clock_ns, self.fs = clock_ns, fs or _Os()
        self.root = root
        self.lock = threading.Lock()
        self.count = self.size = self.last_elapsed = 0
        self.previous = ZERO
        self.per_principal: dict[str, int] = dict.fromkeys(self.context.principals, 0)
        self.fenced = self.sealed = self.failed = False
        self.capacity_seen = False
        root.mkdir(mode=0o700, exist_ok=False)
        (root / "objects").mkdir(mode=0o700)
        self.fd = os.open(root / "journal.tmp",
                          os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_APPEND, 0o600)
        try:
            self._append_locked("capture-start", {"version": VERSION,
                                                  "context": self.context.fields()})
            self._sync_dir(root)
        except BaseException:
            self.failed = True
            self._close_fd()
            raise

    def _sync_dir(self, path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self.fs.fsync(fd)
        finally:
            os.close(fd)

    def _elapsed(self) -> int:
        now = self.clock_ns()
        _require(type(now) is int, "integer controller clock required")
        elapsed = now - self.origin_ns
        _require(elapsed >= self.last_elapsed, "controller clock went backwards")
        return elapsed

    def _capacity(self, kind: str, fields: dict[str, Any], size: int) -> None:
        limits = self.context.limits
        closure = kind in CLOSURE
        records = limits["max_records"] - (0 if closure else limits["closure_reserve_records"])
        budget = limits["max_bytes"] - (0 if closure else limits["closure_reserve_bytes"])
        if self.count + 1 > records:
            raise CapacityExceeded("records")
        if self.size + size > budget:
            raise CapacityExceeded("bytes")
        principal = fields.get("principal")
        if kind in COUNTED and principal is not None:
            if self.per_principal.get(principal, 0) + 1 > limits["decisions_per_principal"]:
                raise CapacityExceeded("principal")

    def _append_locked(self, kind: str, fields: dict[str, Any]) -> tuple[int, int]:
        if self.failed:
            raise JournalUnavailable("journal poisoned")
        if self.sealed:
            raise JournalUnavailable("journal sealed")
        if self.fenced and kind not in AFTER_FENCE:
            raise JournalUnavailable("ingress fenced")
        elapsed = self._elapsed()
        row = {"seq": self.count + 1, "prev_hash": self.previous, "kind": kind,
               "elapsed_ns": elapsed, **fields}
        _check_row(row, self.context)
        raw = _canonical(row) + b"\n"
        self._capacity(kind, fields, len(raw))
        try:
            written = self.fs.write(self.fd, raw)
            if written != len(raw):
                raise OSError("short journal write")
            self.fs.fsync(self.fd)
        except BaseException:
            self.failed = True
            raise
        self.count += 1
        self.size += len(raw)
        self.last_elapsed = elapsed
        self.previous = hashlib.sha256(raw).hexdigest()
        if kind in COUNTED and fields.get("principal") is not None:
            self.per_principal[fields["principal"]] += 1
        if kind == "fence":
            self.fenced = True
        if kind == "capacity":
            self.capacity_seen = True
        return row["seq"], elapsed

    def append(self, kind: str, **fields: Any) -> tuple[int, int]:
        """Durably append one record; return its (sequence, elapsed_ns).
        `capture-start` and `capture-seal` are written only by this class."""
        _require(kind in KINDS and kind not in ("capture-start", "capture-seal"),
                 "caller record kind required")
        with self.lock:
            return self._append_locked(kind, fields)

    def seal(self, coverage: dict[str, str]) -> Reference:
        """Seal after the caller has fenced ingress, drained in-flight work
        and confirmed writer stop. A capacity event forces UNKNOWN. A missing
        fence or a malformed coverage map is refused without poisoning."""
        with self.lock:
            _require(not self.failed and not self.sealed, "journal poisoned or sealed")
            _require(self.fenced, "seal requires a fence")
            _require(type(coverage) is dict and set(coverage) == set(self.context.principals)
                     and all(v in COVERAGE for v in coverage.values()),
                     "complete per-principal coverage required")
            try:
                complete = (not self.capacity_seen
                            and all(v == "complete" for v in coverage.values()))
                self._append_locked("capture-seal", {
                    "records": self.count - 1, "last_hash": self.previous,
                    "coverage": dict(coverage), "outcome": "CLOSED" if complete else "UNKNOWN"})
                self.sealed = True
                raw = os.pread(self.fd, self.size + 1, 0)
                reference = Reference(VERSION, self.context.digest,
                                      "sha256:" + hashlib.sha256(raw).hexdigest(), self.size,
                                      self.count)
                _decode(raw, reference, self.context)
                objects = os.open(self.root / "objects",
                                  os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    fd = os.open(reference.digest[7:], os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | os.O_NOFOLLOW, 0o600, dir_fd=objects)
                    try:
                        view = memoryview(raw)
                        while view:
                            written = self.fs.write(fd, view)
                            _require(type(written) is int and written > 0, "object write failed")
                            view = view[written:]
                        self.fs.fsync(fd)
                        os.fchmod(fd, 0o400)
                    finally:
                        os.close(fd)
                    self.fs.fsync(objects)
                finally:
                    os.close(objects)
                _read(self.root, reference)
                self._close_fd()
                (self.root / "journal.tmp").unlink()
                self._sync_dir(self.root)
                return reference
            except BaseException:
                self.failed = True
                raise

    def _close_fd(self) -> None:
        # Never close a descriptor number twice: it may already be reused.
        fd, self.fd = self.fd, -1
        if fd >= 0:
            os.close(fd)

    def close(self) -> None:
        """Abandon an unsealed journal; it can never verify. After a seal it
        changes nothing: the sealed object stays verifiable."""
        with self.lock:
            if not self.sealed:
                self.failed = True
            self._close_fd()


def _read(root: Path, reference: Reference) -> bytes:
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        objects = os.open("objects", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            fd = os.open(reference.digest[7:], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=objects)
        finally:
            os.close(objects)
    finally:
        os.close(directory)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size == reference.size,
                 "journal object size/type differs")
        _require(stat.S_IMODE(before.st_mode) & 0o222 == 0, "journal object is writable")
        raw = stream.read(reference.size + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) == reference.size
             and (before.st_mtime_ns, before.st_ctime_ns) == (after.st_mtime_ns, after.st_ctime_ns),
             "journal object changed while reading")
    _require("sha256:" + hashlib.sha256(raw).hexdigest() == reference.digest,
             "journal object hash differs")
    return raw


def _decode(raw: bytes, reference: Reference, context: Context) -> dict[str, Any]:
    _require(type(raw) is bytes and len(raw) == reference.size and raw.endswith(b"\n"),
             "complete journal bytes required")
    _require("sha256:" + hashlib.sha256(raw).hexdigest() == reference.digest, "journal hash")
    _require(reference.context_digest == context.digest, "journal bound to another context")
    limits = context.limits
    _require(len(raw) <= limits["max_bytes"], "journal over byte bound")
    lines = raw.splitlines(keepends=True)
    _require(2 <= len(lines) == reference.records <= limits["max_records"],
             "journal record population differs")
    previous, elapsed = ZERO, 0
    fenced = capacity = False
    counts = dict.fromkeys(context.principals, 0)
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines, 1):
        try:
            row = json.loads(line, object_pairs_hook=_pairs)
        except (ValueError, RecursionError):
            raise JournalUnavailable("journal record unreadable") from None
        _require(type(row) is dict, "journal record object required")
        _require(_canonical(row) + b"\n" == line, "journal record not canonical")
        _check_row(row, context)
        _require(row["seq"] == index and row["prev_hash"] == previous, "journal chain differs")
        _require(row["elapsed_ns"] >= elapsed, "journal time went backwards")
        kind = row["kind"]
        _require((kind == "capture-start") == (index == 1), "capture-start must open the journal")
        _require((kind == "capture-seal") == (index == len(lines)), "seal must close the journal")
        _require(not fenced or kind in AFTER_FENCE, "record after fence")
        if kind in COUNTED and row["principal"] is not None:
            counts[row["principal"]] += 1
            _require(counts[row["principal"]] <= limits["decisions_per_principal"],
                     "principal decision bound exceeded")
        if kind == "retry":
            _require(row["original_seq"] < index, "retry must follow its original")
            original = rows[row["original_seq"] - 1]
            _require(original["kind"] == "decision" and original["principal"] == row["principal"]
                     and original["request"] == row["request"]
                     and original["request_digest"] == row["request_digest"],
                     "retry must match its original decision")
        fenced = fenced or kind == "fence"
        capacity = capacity or kind == "capacity"
        elapsed, previous = row["elapsed_ns"], hashlib.sha256(line).hexdigest()
        rows.append(row)
    seal = rows[-1]
    _require(fenced, "unfenced seal")
    _require(seal["records"] == len(rows) - 2 and seal["last_hash"] == seal["prev_hash"],
             "seal does not cover the journal")
    complete = not capacity and all(v == "complete" for v in seal["coverage"].values())
    _require(seal["outcome"] == ("CLOSED" if complete else "UNKNOWN"),
             "seal outcome inconsistent with coverage")
    return {"status": "CAPTURED", "context_digest": context.digest, "outcome": seal["outcome"],
            "coverage": dict(seal["coverage"]), "records": rows[1:-1]}


def verify(root: object, reference: object, expected: object) -> dict[str, Any]:
    """`reference` and `expected` come from the trusted caller, never from the
    journal directory or a report. Anything unprovable is UNKNOWN."""
    try:
        _require(isinstance(root, Path) and type(reference) is Reference
                 and type(expected) is Context, "independently held binding required")
        assert isinstance(root, Path) and isinstance(reference, Reference)
        assert isinstance(expected, Context)
        reference = parse_reference(asdict(reference))
        expected = parse_context(expected.fields())
        assert isinstance(reference, Reference) and isinstance(expected, Context)
        return _decode(_read(root, reference), reference, expected)
    except (OSError, ValueError, TypeError, KeyError, IndexError, RecursionError):
        return {"status": "UNKNOWN", "reason": "journal unavailable or unverifiable"}
