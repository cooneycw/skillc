"""The #620 PR-B request/receipt schema (skillc/task_protocol_schema.py, B1).

The committed cases in controls/task-protocol-schema/cases.json were written by
hand, not derived by running the parser, so they can disagree with it. Each
blind parser variant below must disagree with them."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from skillc import task_protocol_schema as schema
from skillc.task_protocol_schema import Receipt, Rejected, Request

ROOT = Path(__file__).resolve().parent.parent
CASES = json.loads((ROOT / "controls" / "task-protocol-schema" / "cases.json").read_text())
REQUESTS: list[dict[str, Any]] = CASES["requests"]
RECEIPTS: list[dict[str, Any]] = CASES["receipts"]

Parser = Callable[[bytes], Request | Rejected]


def _raw(case: dict[str, Any]) -> bytes:
    return bytes.fromhex(case["raw_hex"]) if "raw_hex" in case else case["raw"].encode("utf-8")


def _outcome(parsed: Request | Rejected) -> str:
    return "accepted" if isinstance(parsed, Request) else "rejected:" + parsed.reason


def _disagreements(parse: Parser) -> set[str]:
    return {c["name"] for c in REQUESTS if _outcome(parse(_raw(c))) != c["expect"]}


@pytest.mark.parametrize("case", REQUESTS, ids=lambda c: c["name"])
def test_each_committed_request_gets_its_declared_outcome(case: dict[str, Any]) -> None:
    raw = _raw(case)
    parsed = schema.parse_request(raw)
    assert _outcome(parsed) == case["expect"]
    if isinstance(parsed, Request):
        assert parsed.canonical().decode() == case["canonical"]
        assert schema.parse_request(schema.encode_request(parsed)) == parsed
    else:
        assert parsed.length == len(raw)
        assert parsed.digest == hashlib.sha256(raw[:schema.MAX_REQUEST_BYTES]).hexdigest()


def test_the_cases_reach_every_schema_rejection() -> None:
    """A floor: a rejection no case reaches is a rejection nothing shows can fire."""
    reached = {c["expect"].split(":", 1)[1] for c in REQUESTS if c["expect"] != "accepted"}
    assert reached == set(schema.SCHEMA_REJECTIONS)
    accepted_ops = {json.loads(c["canonical"])["op"] for c in REQUESTS if c["expect"] == "accepted"}
    assert accepted_ops == set(schema.OPERATIONS)


def test_a_rejection_never_retains_participant_text() -> None:
    planted = [c for c in REQUESTS if "CANARY" in c.get("raw", "")]
    assert planted
    for case in planted:
        parsed = schema.parse_request(_raw(case))
        assert isinstance(parsed, Rejected)
        assert "CANARY" not in repr(parsed) and "CANARY" not in json.dumps(vars(parsed))


def test_identity_and_controller_fields_are_rejected_never_stripped() -> None:
    honest = schema.parse_request(b'{"version":1,"op":"ack","request":2,"offer_id":"o-1"}')
    assert isinstance(honest, Request)
    for field in sorted(schema.IDENTITY_FIELDS | schema.CONTROLLER_FIELDS):
        raw = json.dumps({"version": 1, "op": "ack", "request": 2, "offer_id": "o-1",
                          field: "x"}).encode()
        parsed = schema.parse_request(raw)
        assert isinstance(parsed, Rejected), field
        expected = ("identity-field-supplied" if field in schema.IDENTITY_FIELDS
                    else "controller-field-supplied")
        assert parsed.reason == expected, field


def test_deep_nesting_is_rejected_without_raising() -> None:
    """Whether CPython's decoder raises RecursionError at this depth depends on
    its version, so either rejection is acceptable; an exception is not."""
    parsed = schema.parse_request(b"[" * 2000 + b"]" * 2000)
    assert isinstance(parsed, Rejected) and parsed.reason in {"malformed-json", "not-object"}


def test_arbitrary_bytes_never_raise() -> None:
    rng = random.Random(620)
    alphabet = b'{}[]":,0123456789-.eEtrufalsn \\\nopversiqckmldfy_' + bytes(range(256))
    for _ in range(3000):
        raw = bytes(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
        assert isinstance(schema.parse_request(raw), (Request, Rejected))


def test_a_non_bytes_input_is_a_programming_error() -> None:
    with pytest.raises(TypeError):
        schema.parse_request('{"version":1}')


def test_the_retry_digest_is_the_normalized_content() -> None:
    a = schema.parse_request(b'{"version":1,"op":"ack","request":7,"offer_id":"o-1"}\n')
    b = schema.parse_request(b' {"offer_id":"o-1", "request":7, "op":"ack", "version":1} ')
    c = schema.parse_request(b'{"version":1,"op":"complete","request":7,"offer_id":"o-1"}')
    assert isinstance(a, Request) and isinstance(b, Request) and isinstance(c, Request)
    assert a.digest == b.digest and a.digest != c.digest and a.request == c.request


@pytest.mark.parametrize("kwargs", [
    {"op": "fetch", "request": 1},
    {"op": "offer", "request": 0},
    {"op": "offer", "request": True},
    {"op": "offer", "request": 1, "offer_id": "o-1"},
    {"op": "ack", "request": 1},
    {"op": "ack", "request": 1, "offer_id": "-x"},
    {"op": "refuse", "request": 1, "offer_id": "o-1"},
    {"op": "ack", "request": 1, "offer_id": "o-1", "reason": "blocked"},
    {"op": "refuse", "request": 1, "offer_id": "o-1", "reason": "free text"},
])
def test_a_request_cannot_be_constructed_outside_the_schema(kwargs: dict[str, Any]) -> None:
    with pytest.raises(schema.SchemaError):
        Request(**kwargs)


def test_the_rejection_vocabularies_are_closed_and_disjoint() -> None:
    assert len(set(schema.REJECTIONS)) == len(schema.REJECTIONS)
    assert not set(schema.SCHEMA_REJECTIONS) & set(schema.CONTROLLER_REJECTIONS)
    assert not schema.IDENTITY_FIELDS & schema.CONTROLLER_FIELDS
    assert not (schema.IDENTITY_FIELDS | schema.CONTROLLER_FIELDS) & {
        "version", "op", "request", "offer_id", "reason"}
    with pytest.raises(schema.SchemaError):
        Rejected("late", 0, "0" * 64)


# Blind variants: each must disagree with the committed cases.


def _accept_any_object(raw: bytes) -> Request | Rejected:
    try:
        value = json.loads(raw)
    except ValueError:
        return schema.parse_request(raw)
    return Request("offer", 1) if isinstance(value, dict) else schema.parse_request(raw)


def _strip_identity(raw: bytes) -> Request | Rejected:
    try:
        value = json.loads(raw)
    except ValueError:
        return schema.parse_request(raw)
    if isinstance(value, dict):
        value = {k: v for k, v in value.items()
                 if k not in schema.IDENTITY_FIELDS | schema.CONTROLLER_FIELDS}
        return schema.parse_request(json.dumps(value).encode())
    return schema.parse_request(raw)


def _size_blind(raw: bytes) -> Request | Rejected:
    parsed = schema.parse_request(raw)
    if isinstance(parsed, Rejected) and parsed.reason == "oversize":
        return schema.parse_request(raw.strip())
    return parsed


def _last_duplicate_wins(raw: bytes) -> Request | Rejected:
    try:
        value = json.loads(raw)
    except ValueError:
        return schema.parse_request(raw)
    return schema.parse_request(json.dumps(value).encode()) if isinstance(value, dict) else (
        schema.parse_request(raw))


@pytest.mark.parametrize("blind,must_miss", [
    (lambda raw: Request("offer", 1), "4097-bytes"),
    (lambda raw: Rejected("malformed-json", len(raw), "0" * 64), "offer"),
    (_accept_any_object, "identity-role"),
    (_strip_identity, "identity-session_id"),
    (_strip_identity, "controller-seq"),
    (_size_blind, "4097-bytes"),
    (_last_duplicate_wins, "duplicate-key"),
], ids=["accept-all", "reject-all", "accept-any-object", "strip-identity", "strip-controller",
        "size-blind", "last-duplicate-wins"])
def test_a_blind_parser_disagrees(blind: Parser, must_miss: str) -> None:
    assert must_miss in _disagreements(blind)


# Receipts.


@pytest.mark.parametrize("case", RECEIPTS, ids=lambda c: c["name"])
def test_each_committed_receipt_parses_only_when_declared(case: dict[str, Any]) -> None:
    raw = case["raw"].encode("utf-8")
    parsed = schema.parse_receipt(raw)
    assert (parsed is not None) is case["expect"]
    if parsed is not None:
        assert parsed.encode() == raw


def test_the_receipt_cases_reach_every_decision() -> None:
    decisions = {json.loads(c["raw"])["decision"] for c in RECEIPTS if c["expect"]}
    assert decisions == set(schema.DECISIONS)


def test_every_rejection_round_trips_as_a_receipt() -> None:
    for reason in schema.REJECTIONS:
        receipt = Receipt(None, "rejected", None, reason)
        assert schema.parse_receipt(receipt.encode()) == receipt


def test_a_lenient_receipt_reader_is_caught() -> None:
    """Blind variant: a reader that accepts any JSON object with a decision."""
    def lenient(raw: bytes) -> object:
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, dict) and "decision" in value else None

    wrong = {c["name"] for c in RECEIPTS if (lenient(c["raw"].encode()) is not None) != c["expect"]}
    assert {"unknown-decision", "not-canonical", "extra-field"} <= wrong
