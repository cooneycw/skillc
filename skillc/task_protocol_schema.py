"""Closed request and receipt schema for the task-protocol stream (#620 PR-B, B1).

See `docs/specs/evaluation-facility/task-protocol-stream.md`, section 1, accepted
2026-11-17 with its recommended defaults. This module is pure: it parses and
encodes bytes and holds no socket, journal, lease, clock or state.

A REQUEST CARRIES NO IDENTITY AND NO CLOCK. The controller learns who sent a
request from the endpoint's lease (B4/B5), never from the payload. A payload
that names a role, attempt, session, wave, task, generation, revision, nonce or
sender is rejected as `identity-field-supplied`. One that names a sequence, a
time or an outcome is rejected as `controller-field-supplied`. Neither is
honoured or stripped, because silently dropping a field would turn a lying
request into an accepted one.

INVALID BYTES ARE NEVER RETAINED. A rejection keeps a closed reason code, the
byte length and a SHA-256 of at most `MAX_REQUEST_BYTES` of input, nothing that
could carry participant-chosen text into a journal or a reply.

Offer IDs are public correlation data issued by the controller. They confer no
identity authority, so this module checks only their shape.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

VERSION = 1
#: Decision 7's request bound: 4 KiB, counted on the raw bytes before parsing.
MAX_REQUEST_BYTES = 4096
MAX_REQUEST_NUMBER = (1 << 31) - 1

OPERATIONS = ("offer", "ack", "complete", "refuse")

#: A role's own refusal reasons. Closed, with no free text: a refusal is
#: retained as a refusal, never as a diagnosis of anything.
REFUSAL_REASONS = ("cannot-complete", "blocked", "not-my-task", "other")

#: Fields a request may never carry, by why. Any other unknown key is
#: `unknown-field`.
IDENTITY_FIELDS = frozenset({
    "role", "attempt", "attempt_id", "session", "session_id", "wave", "wave_id",
    "task", "generation", "revision", "nonce", "sender", "principal", "actor",
})
CONTROLLER_FIELDS = frozenset({
    "seq", "sequence", "elapsed", "elapsed_ns", "time", "timestamp", "clock", "deadline",
    "ok", "success", "decision", "event", "normalized", "receipt", "accepted",
})

#: Rejections decided here, from the bytes alone.
SCHEMA_REJECTIONS = (
    "oversize", "not-utf8", "malformed-json", "duplicate-key", "not-object",
    "identity-field-supplied", "controller-field-supplied", "unknown-field",
    "unsupported-version", "unknown-op", "bad-request-number",
    "missing-offer-id", "unexpected-offer-id", "bad-offer-id",
    "missing-reason", "unexpected-reason", "unknown-reason",
)
#: Rejections the controller decides later (lease, state, journal). Listed here
#: so the receipt schema is closed once, for the client and the journal alike.
CONTROLLER_REJECTIONS = (
    "unauthenticated-peer", "revoked-lease", "no-current-offer", "wrong-offer",
    "stale-offer", "ack-before-offer", "complete-before-ack", "after-complete",
    "protocol-conflict", "late", "fenced", "capacity", "unavailable",
)
REJECTIONS = SCHEMA_REJECTIONS + CONTROLLER_REJECTIONS

#: What a receipt may say. A retry returns the ORIGINAL decision, so there is
#: no separate retry decision here; the journal records the retry itself.
DECISIONS = ("offered", "acknowledged", "completion-claimed", "refusal-retained", "rejected")

_OFFER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_MAX_DIGITS = 19


class SchemaError(ValueError):
    """An internal guard, never surfaced as text to a participant."""


@dataclass(frozen=True)
class Request:
    """One well-formed request. `digest` is the SHA-256 of its canonical
    encoding, which is what idempotence compares: the same request number with
    the same digest is a retry, with a different digest a conflict (B3)."""

    op: str
    request: int
    offer_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.op not in OPERATIONS:
            raise SchemaError("unknown operation")
        if type(self.request) is not int or not 1 <= self.request <= MAX_REQUEST_NUMBER:
            raise SchemaError("bad request number")
        if (self.op == "offer") != (self.offer_id is None):
            raise SchemaError("offer id presence")
        if self.offer_id is not None and not _OFFER_ID.fullmatch(self.offer_id):
            raise SchemaError("bad offer id")
        if (self.op == "refuse") != (self.reason is not None):
            raise SchemaError("reason presence")
        if self.reason is not None and self.reason not in REFUSAL_REASONS:
            raise SchemaError("unknown reason")

    def fields(self) -> dict[str, Any]:
        out: dict[str, Any] = {"version": VERSION, "op": self.op, "request": self.request}
        if self.offer_id is not None:
            out["offer_id"] = self.offer_id
        if self.reason is not None:
            out["reason"] = self.reason
        return out

    def canonical(self) -> bytes:
        return json.dumps(self.fields(), sort_keys=True, separators=(",", ":")).encode()

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical()).hexdigest()


@dataclass(frozen=True)
class Rejected:
    """A schema rejection: a closed reason, the raw length, and a digest of at
    most `MAX_REQUEST_BYTES` of the raw bytes. Never the bytes themselves."""

    reason: str
    length: int
    digest: str

    def __post_init__(self) -> None:
        if self.reason not in SCHEMA_REJECTIONS:
            raise SchemaError("unknown schema rejection")
        if type(self.length) is not int or self.length < 0:
            raise SchemaError("bad length")
        if not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise SchemaError("bad digest")


def encode_request(request: Request) -> bytes:
    """The client's framing: one canonical JSON line."""
    return request.canonical() + b"\n"


def _rejected(reason: str, raw: bytes) -> Rejected:
    return Rejected(reason, len(raw), hashlib.sha256(raw[:MAX_REQUEST_BYTES]).hexdigest())


class _Duplicate(ValueError):
    pass


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise _Duplicate(key)
        out[key] = value
    return out


def _parse_int(text: str) -> int:
    if len(text.lstrip("-")) > _MAX_DIGITS:
        raise ValueError("integer too long")
    return int(text)


def _reject_constant(_name: str) -> Any:
    raise ValueError("non-finite number")


def _classify_keys(keys: set[str]) -> str | None:
    if keys & IDENTITY_FIELDS:
        return "identity-field-supplied"
    if keys & CONTROLLER_FIELDS:
        return "controller-field-supplied"
    if keys - {"version", "op", "request", "offer_id", "reason"}:
        return "unknown-field"
    return None


def parse_request(raw: object) -> Request | Rejected:
    """Bytes in, a `Request` or a `Rejected` out; never an exception for any
    `bytes` input. A trailing newline is the framing and is removed once.
    Anything that is not `bytes` is a programming error and raises."""
    if type(raw) is not bytes:
        raise TypeError("parse_request takes bytes")
    if len(raw) > MAX_REQUEST_BYTES:
        return _rejected("oversize", raw)
    body = raw[:-1] if raw.endswith(b"\n") else raw
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return _rejected("not-utf8", raw)
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_int=_parse_int,
                           parse_constant=_reject_constant)
    except _Duplicate:
        return _rejected("duplicate-key", raw)
    except (ValueError, RecursionError):
        return _rejected("malformed-json", raw)
    if type(value) is not dict:
        return _rejected("not-object", raw)
    problem = _classify_keys(set(value))
    if problem is not None:
        return _rejected(problem, raw)
    if value.get("version") != VERSION or type(value.get("version")) is not int:
        return _rejected("unsupported-version", raw)
    op = value.get("op")
    if type(op) is not str or op not in OPERATIONS:
        return _rejected("unknown-op", raw)
    number = value.get("request")
    if type(number) is not int or not 1 <= number <= MAX_REQUEST_NUMBER:
        return _rejected("bad-request-number", raw)
    offer_id = value.get("offer_id")
    if op == "offer":
        if "offer_id" in value:
            return _rejected("unexpected-offer-id", raw)
    elif "offer_id" not in value:
        return _rejected("missing-offer-id", raw)
    elif type(offer_id) is not str or not _OFFER_ID.fullmatch(offer_id):
        return _rejected("bad-offer-id", raw)
    reason = value.get("reason")
    if op != "refuse":
        if "reason" in value:
            return _rejected("unexpected-reason", raw)
    elif "reason" not in value:
        return _rejected("missing-reason", raw)
    elif type(reason) is not str or reason not in REFUSAL_REASONS:
        return _rejected("unknown-reason", raw)
    return Request(op, number, offer_id, reason)


@dataclass(frozen=True)
class Receipt:
    """The controller's reply. `offer_id` is present on `offered` and echoes
    the request's offer otherwise; `reason` is present only on `rejected`.
    A receipt is sent only after its decision is durable (B2/B5)."""

    request: int | None
    decision: str
    offer_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in DECISIONS:
            raise SchemaError("unknown decision")
        if self.request is not None and (type(self.request) is not int
                                         or not 1 <= self.request <= MAX_REQUEST_NUMBER):
            raise SchemaError("bad request number")
        if (self.decision == "rejected") != (self.reason is not None):
            raise SchemaError("reason presence")
        if self.reason is not None and self.reason not in REJECTIONS:
            raise SchemaError("unknown rejection")
        if self.decision == "offered" and self.offer_id is None:
            raise SchemaError("offer without id")
        if self.offer_id is not None and not _OFFER_ID.fullmatch(self.offer_id):
            raise SchemaError("bad offer id")
        if self.decision != "rejected" and self.request is None:
            raise SchemaError("decision without request")

    def encode(self) -> bytes:
        out: dict[str, Any] = {"version": VERSION, "decision": self.decision,
                               "request": self.request}
        if self.offer_id is not None:
            out["offer_id"] = self.offer_id
        if self.reason is not None:
            out["reason"] = self.reason
        return json.dumps(out, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def parse_receipt(raw: object) -> Receipt | None:
    """The client's reader. Anything not exactly a receipt is None, which the
    client reports as an unavailable reply, never as a decision."""
    if type(raw) is not bytes or len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
        return None
    try:
        value = json.loads(raw[:-1].decode("utf-8"), object_pairs_hook=_pairs,
                           parse_int=_parse_int, parse_constant=_reject_constant)
    except (_Duplicate, ValueError, UnicodeDecodeError, RecursionError):
        return None
    if type(value) is not dict or not {"version", "decision", "request"} <= set(value):
        return None
    if set(value) - {"version", "decision", "request", "offer_id", "reason"}:
        return None
    if type(value["version"]) is not int or value["version"] != VERSION:
        return None
    try:
        receipt = Receipt(value["request"], value["decision"], value.get("offer_id"),
                          value.get("reason"))
    except (SchemaError, TypeError):
        return None
    return receipt if receipt.encode() == raw else None
