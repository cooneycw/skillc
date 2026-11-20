"""`skillc-task-protocol`: the role-facing task-protocol client (#620 PR-B, B5a).

See `docs/specs/evaluation-facility/task-protocol-stream.md`, section 1. The
controller copies THESE BYTES, unchanged, into every session sandbox in both
arms, at a root-owned path the candidate cannot write. So this file is
standalone: standard library only, and it imports nothing from `skillc`. A
test compares its vocabulary with `skillc.task_protocol_schema`, so the two
cannot drift silently.

    skillc-task-protocol offer --request 1
    skillc-task-protocol ack --request 2 --offer <offer id>
    skillc-task-protocol complete --request 3 --offer <offer id>
    skillc-task-protocol refuse --request 4 --offer <offer id> --reason blocked

The endpoint is fixed. No argument, environment variable or file can name
another socket, a role, a session or a clock; who is asking is decided by the
controller from the endpoint, never by this client. The reply is printed as
the controller's receipt line.

Exit codes: 0 the controller decided something other than a rejection; 3 it
rejected the request; 4 no valid receipt arrived (no endpoint, refused
connection, timeout, malformed or missing reply), which says nothing about
the task; 2 usage.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from typing import Any

ENDPOINT = "/run/skillc-task-protocol/channel.sock"
VERSION = 1
MAX_BYTES = 4096
MAX_REQUEST_NUMBER = (1 << 31) - 1
TIMEOUT_SECONDS = 30.0
OPERATIONS = ("offer", "ack", "complete", "refuse")
REFUSAL_REASONS = ("cannot-complete", "blocked", "not-my-task", "other")
DECISIONS = ("offered", "acknowledged", "completion-claimed", "refusal-retained", "rejected")
REJECTIONS = (
    "oversize", "not-utf8", "malformed-json", "duplicate-key", "not-object",
    "identity-field-supplied", "controller-field-supplied", "unknown-field",
    "unsupported-version", "unknown-op", "bad-request-number",
    "missing-offer-id", "unexpected-offer-id", "bad-offer-id",
    "missing-reason", "unexpected-reason", "unknown-reason",
    "unauthenticated-peer", "revoked-lease", "no-current-offer", "wrong-offer",
    "stale-offer", "ack-before-offer", "complete-before-ack", "after-complete",
    "protocol-conflict", "late", "fenced", "capacity", "unavailable",
)
_OFFER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
EXIT_DECIDED, EXIT_USAGE, EXIT_REJECTED, EXIT_UNAVAILABLE = 0, 2, 3, 4


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def request_fields(op: str, request: int, offer_id: str | None = None,
                   reason: str | None = None) -> dict[str, Any]:
    """The closed request, or ValueError. Never carries identity or time."""
    if op not in OPERATIONS:
        raise ValueError("unknown operation")
    if type(request) is not int or not 1 <= request <= MAX_REQUEST_NUMBER:
        raise ValueError("request number out of range")
    if (op == "offer") != (offer_id is None):
        raise ValueError("an offer id is required except for offer")
    if offer_id is not None and not _OFFER_ID.fullmatch(offer_id):
        raise ValueError("malformed offer id")
    if (op == "refuse") != (reason is not None):
        raise ValueError("a reason is required for refuse only")
    if reason is not None and reason not in REFUSAL_REASONS:
        raise ValueError("unknown refusal reason")
    fields: dict[str, Any] = {"version": VERSION, "op": op, "request": request}
    if offer_id is not None:
        fields["offer_id"] = offer_id
    if reason is not None:
        fields["reason"] = reason
    return fields


def encode(fields: dict[str, Any]) -> bytes:
    return _canonical(fields) + b"\n"


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def parse_receipt(raw: bytes) -> dict[str, Any] | None:
    """The receipt exactly as the controller encodes it, or None."""
    if type(raw) is not bytes or len(raw) > MAX_BYTES or not raw.endswith(b"\n"):
        return None
    try:
        value = json.loads(raw[:-1].decode("utf-8"), object_pairs_hook=_pairs)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    if type(value) is not dict or not {"version", "decision", "request"} <= set(value):
        return None
    if set(value) - {"version", "decision", "request", "offer_id", "reason"}:
        return None
    if type(value["version"]) is not int or value["version"] != VERSION:
        return None
    decision, number = value["decision"], value["request"]
    offer_id, reason = value.get("offer_id"), value.get("reason")
    if type(decision) is not str or decision not in DECISIONS:
        return None
    if number is not None and (type(number) is not int
                               or not 1 <= number <= MAX_REQUEST_NUMBER):
        return None
    if decision != "rejected" and number is None:
        return None
    if (decision == "rejected") != (reason is not None):
        return None
    if reason is not None and (type(reason) is not str or reason not in REJECTIONS):
        return None
    if decision == "offered" and offer_id is None:
        return None
    if offer_id is not None and (type(offer_id) is not str or not _OFFER_ID.fullmatch(offer_id)):
        return None
    return value if _canonical(value) + b"\n" == raw else None


def call(fields: dict[str, Any], endpoint: str = ENDPOINT,
         timeout: float = TIMEOUT_SECONDS) -> dict[str, Any] | None:
    """Send one request and read one receipt. None means no valid receipt."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(endpoint)
            client.sendall(encode(fields))
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = client.recv(MAX_BYTES + 1)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_BYTES or chunk.endswith(b"\n"):
                    break
    except OSError:
        return None
    return parse_receipt(b"".join(chunks))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skillc-task-protocol",
                                     description="Report task protocol events to the controller.")
    sub = parser.add_subparsers(dest="op", required=True)
    for op in OPERATIONS:
        command = sub.add_parser(op)
        command.add_argument("--request", type=int, required=True)
        if op != "offer":
            command.add_argument("--offer", required=True)
        if op == "refuse":
            command.add_argument("--reason", required=True, choices=REFUSAL_REASONS)
    return parser


def main(argv: list[str] | None = None, endpoint: str = ENDPOINT) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_DECIDED if exc.code == 0 else EXIT_USAGE
    try:
        fields = request_fields(args.op, args.request, getattr(args, "offer", None),
                                getattr(args, "reason", None))
        if len(encode(fields)) > MAX_BYTES:
            raise ValueError("request exceeds the controller's size bound")
    except ValueError as exc:
        print(f"skillc-task-protocol: {exc}", file=sys.stderr)
        return EXIT_USAGE
    receipt = call(fields, endpoint)
    if receipt is None:
        print("skillc-task-protocol: no valid receipt from the controller", file=sys.stderr)
        return EXIT_UNAVAILABLE
    sys.stdout.write(_canonical(receipt).decode() + "\n")
    return EXIT_REJECTED if receipt["decision"] == "rejected" else EXIT_DECIDED


if __name__ == "__main__":
    sys.exit(main())
