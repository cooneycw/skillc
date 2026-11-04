"""Controller-owned helper operation journal for the closed rehearsal (#626).

Endpoints are issued to controller code, bound to actual role/turn context.
Serialized claims or helper-looking stdout never authorize an observation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .completion import number
from .controller_turns import session_id_from_header
from .decide_reply_channel import DecideReplyChannel
from .git_snapshot import SafeTree, Unreadable


def verify_journal(root: Path, expected_digest: str) -> bool:
    """Only byte custody; this is not protocol coverage or task success."""
    try:
        raw, _ = SafeTree(root).read("journal.json", 16 * 1024 * 1024)
        value = json.loads(raw)
        return (hashlib.sha256(raw).hexdigest() == expected_digest
                and isinstance(value, dict) and value.get("version") == 1
                and isinstance(value.get("rows"), list) and bool(value.get("bindings")))
    except (OSError, Unreadable, ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Binding:
    wave_id: str
    role: str
    attempt_id: str
    session_id: str
    task: str
    generation: int
    revision: int
    nonce: str

    def __post_init__(self) -> None:
        for key in ("wave_id", "role", "attempt_id", "session_id", "task", "nonce"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError("complete bounded binding required")
        if (type(self.generation) is not int or self.generation < 0
                or type(self.revision) is not int or self.revision < 1):
            raise ValueError("nonbool generation/revision required")


class Executor(Protocol):
    """Trusted controller adapter, never a participant-supplied callback."""

    def admitted(self, binding: Binding) -> bool: ...

    def execute(self, binding: Binding, operation: str, nonce: str,
                assignment_rev: int | None, commit: str | None) -> Mapping[str, Any] | None: ...

    def retired(self, binding: Binding) -> bool: ...


@dataclass(frozen=True)
class Endpoint:
    """Unserializable controller capability; the request cannot select it."""

    binding: Binding
    turn_nonce: str
    _capability: object


class HelperTap:
    def __init__(self, bindings: tuple[Binding, ...], helper_pins: Mapping[str, str],
                 executor: Executor, root: Path, *, clock: Callable[[], float] = time.monotonic,
                 origin: float | None = None) -> None:
        if not bindings or len({b.role for b in bindings}) != len(bindings):
            raise ValueError("nonempty unique planned roles required")
        if len({b.wave_id for b in bindings}) != 1 or not helper_pins:
            raise ValueError("one wave and declared helper pins required")
        self.bindings = {b.role: b for b in bindings}
        self.pins = dict(helper_pins)
        self.executor, self.root, self.clock = executor, root, clock
        self.origin = number(clock() if origin is None else origin)
        self.active: dict[str, Endpoint] = {}
        self.channels: dict[str, DecideReplyChannel] = {}
        self.assignments: dict[str, int] = {}
        self.rows: list[dict[str, Any]] = []
        self.refusal_rows: list[dict[str, Any]] = []
        self.unknown: set[str] = set()
        self.lock = threading.RLock()
        self.closed = False
        self.expected_digest: str | None = None
        self.refusal_digest: str | None = None
        root.mkdir(parents=True, exist_ok=False)
        self._publish()
        self._publish_refusals()

    def _publish_refusals(self) -> None:
        if self.refusal_digest is not None:
            try:
                old, _ = SafeTree(self.root).read("refusals.json", 16 * 1024 * 1024)
                if hashlib.sha256(old).hexdigest() != self.refusal_digest:
                    raise OSError("refusal custody changed")
            except (Unreadable, OSError) as exc:
                self.unknown.add("refusal-integrity-unavailable")
                raise OSError("refusal custody lost") from exc
        raw = json.dumps({"version": 1, "bindings": [asdict(b) for b in self.bindings.values()],
                          "rows": self.refusal_rows}, sort_keys=True).encode()
        temporary = self.root / "refusals.pending"
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.root / "refusals.json")
        self.refusal_digest = hashlib.sha256(raw).hexdigest()

    def _publish(self) -> None:
        if self.expected_digest is not None:
            try:
                previous, _ = SafeTree(self.root).read("journal.json", 16 * 1024 * 1024)
                if hashlib.sha256(previous).hexdigest() != self.expected_digest:
                    raise OSError("journal digest changed")
            except (Unreadable, OSError) as exc:
                self.unknown.add("journal-integrity-unavailable")
                raise OSError("journal custody lost") from exc
        raw = json.dumps({"version": 1, "bindings": [asdict(b) for b in self.bindings.values()],
                          "helper_pins": self.pins, "rows": self.rows,
                          "unknown": sorted(self.unknown)}, sort_keys=True).encode()
        temporary = self.root / "journal.pending"
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.root / "journal.json")
        self.expected_digest = hashlib.sha256(raw).hexdigest()

    def bind_channel(self, role: str, channel: DecideReplyChannel) -> None:
        """The controller binds the actual owned server, not a supplied log."""
        if (not isinstance(channel, DecideReplyChannel) or role in self.channels
                or channel.attempt_id != self.bindings[role].attempt_id
                or not channel.peer_authentication_configured()):
            raise ValueError("one actual matching role channel required")
        self.channels[role] = channel

    def _record(self, kind: str, binding: Binding, **fields: Any) -> None:
        if len(self.rows) >= 128:
            self.unknown.add("journal-population-over-bound")
            raise OSError("journal entry cap reached")
        now = number(self.clock()) - self.origin
        if now < 0 or (self.rows and now < self.rows[-1]["elapsed"]):
            raise ValueError("nonmonotonic observation clock")
        self.rows.append({"seq": len(self.rows) + 1, "kind": kind,
                          **asdict(binding), "elapsed": now, **copy.deepcopy(fields)})
        publication_failed = False
        if kind == "refusal":
            self.refusal_rows.append(copy.deepcopy(self.rows[-1]))
            try:
                self._publish_refusals()
            except OSError:
                self.unknown.add(binding.role + ":refusal-publication-unavailable")
                publication_failed = True
        try:
            self._publish()
        except OSError:
            self.unknown.add(binding.role + ":publication-unavailable")
            raise
        if publication_failed:
            raise OSError("refusal publication unavailable")

    def open_turn(self, role: str, captured_header: bytes) -> Endpoint:
        """Called by the controller after immutable bootstrap header binding."""
        with self.lock:
            binding = self.bindings[role]
            if self.closed or session_id_from_header(captured_header) != binding.session_id:
                raise ValueError("unobserved or incompatible bootstrap session")
            endpoint = Endpoint(binding, secrets.token_hex(16), object())
            self.active[role] = endpoint
            return endpoint

    def end_turn(self, endpoint: Endpoint) -> None:
        with self.lock:
            if self.active.get(endpoint.binding.role) is endpoint:
                del self.active[endpoint.binding.role]

    def _operation(self, binding: Binding, operation: str, commit: str | None = None) -> bool:
        try:
            admitted = self.executor.admitted(binding) is True
        except (OSError, ValueError):
            admitted = False
        if not admitted:
            self.unknown.add(binding.role + ":execution-binding-unavailable")
            self._record("unavailable", binding, operation=operation)
            return False
        nonce = secrets.token_hex(16)
        try:
            receipt = self.executor.execute(binding, operation, nonce,
                                            self.assignments.get(binding.role), commit)
        except (OSError, ValueError, TimeoutError):
            receipt = None
        valid = (isinstance(receipt, Mapping) and receipt.get("nonce") == nonce
                 and receipt.get("operation") == operation
                 and type(receipt.get("exit_code")) is int and receipt["exit_code"] == 0
                 and receipt.get("effect") is True
                 and receipt.get("pins_before") == self.pins and receipt.get("pins_after") == self.pins)
        if valid and receipt is not None:
            revision = receipt.get("revision")
            valid = type(revision) is int and revision > 0
            if operation == "ack":
                valid = valid and revision == self.assignments.get(binding.role)
        if not valid:
            self.unknown.add(binding.role + ":helper-result-unavailable")
            self._record("unavailable", binding, operation=operation, receipt=dict(receipt) if receipt else None)
            return False
        assert receipt is not None
        self._record("assignment" if operation == "assignment" else "operation", binding,
                     operation=operation, receipt=dict(receipt))
        if operation == "assignment":
            self.assignments[binding.role] = int(receipt["revision"])
        return True

    def assign(self, role: str) -> bool:
        with self.lock:
            if self.closed or role not in self.active or role in self.assignments:
                raise ValueError("one controller assignment after observed bootstrap required")
            return self._operation(self.bindings[role], "assignment")

    def request(self, endpoint: Endpoint, request: Mapping[str, Any]) -> dict[str, Any]:
        """Only the endpoint's controller callback calls this, never actor data."""
        with self.lock:
            binding = endpoint.binding
            active = self.active.get(binding.role)
            known = active is endpoint and active._capability is endpoint._capability
            if self.closed or not known:
                # A forged Python context is not even an attributable endpoint.
                self.unknown.add("unattributed-or-stale-endpoint")
                self._publish()
                return {"accepted": False, "reason": "unattributed-or-stale-endpoint"}
            required = {"op", "binding", "turn_nonce"}
            allowed = required | ({"commit"} if request.get("op") == "complete" else set())
            reason = None
            if not required <= set(request) or set(request) - allowed:
                reason = "control-or-unknown-fields"
            elif request.get("op") not in {"ack", "complete"}:
                reason = "operation-not-allowed"
            elif request.get("turn_nonce") != endpoint.turn_nonce:
                reason = "stale-turn"
            elif request.get("binding") != asdict(binding) or any(
                    type(request["binding"][key]) is not type(value) for key, value in asdict(binding).items()):
                reason = "wrong-assignment-identity"
            elif binding.role not in self.assignments:
                reason = "assignment-unobserved"
            if reason is not None:
                try:
                    self._record("refusal", binding, reason=reason, request=dict(request))
                except OSError:
                    return {"accepted": False, "reason": "coverage-unavailable"}
                return {"accepted": False, "reason": reason}
            try:
                accepted = self._operation(binding, str(request["op"]), request.get("commit"))
            except OSError:
                accepted = False
            return {"accepted": accepted, "reason": "observed" if accepted else "coverage-unavailable"}

    def finalize(self) -> dict[str, Any]:
        """Controller-only finalization; no actor can submit completion coverage."""
        # No tap lock while channels drain: admitted handlers need it to finish.
        for role, binding in self.bindings.items():
            channel = self.channels.get(role)
            try:
                stopped = self.executor.retired(binding) is True
            except (OSError, ValueError):
                stopped = False
            if not stopped:
                self.unknown.add(role + ":stop-unconfirmed")
                self.unknown.add(role + ":channel-finalization-unavailable")
                continue
            try:
                if channel is None:
                    raise ValueError("channel absent")
                observed = channel.trusted_log()
                if (observed.status != "witnessed" or observed.attempt_id != binding.attempt_id
                        or channel.dropped_connections()):
                    raise ValueError("incomplete channel observation")
                accepted = sum(1 for row in observed.decisions
                               if row.request.get("op") in {"ack", "complete"}
                               and row.result.get("accepted") is True)
                recorded = sum(1 for row in self.rows if row["kind"] == "operation" and row["role"] == role)
                if accepted != recorded:
                    raise ValueError("operation/channel population mismatch")
            except (OSError, RuntimeError, ValueError):
                self.unknown.add(role + ":channel-finalization-unavailable")
        with self.lock:
            self.closed = True
            for role, binding in self.bindings.items():
                operations = [r["operation"] for r in self.rows if r["kind"] == "operation" and r["role"] == role]
                if "ack" not in operations or "complete" not in operations:
                    self.unknown.add(role + ":protocol-coverage-incomplete")
            try:
                self._publish()
                raw, _ = SafeTree(self.root).read("journal.json", 16 * 1024 * 1024)
                if hashlib.sha256(raw).hexdigest() != self.expected_digest:
                    raise OSError("journal changed on final read")
            except (OSError, Unreadable):
                self.unknown.add("journal-integrity-unavailable")
            try:
                self._publish_refusals()
                refusal_raw, _ = SafeTree(self.root).read("refusals.json", 16 * 1024 * 1024)
                if hashlib.sha256(refusal_raw).hexdigest() != self.refusal_digest:
                    raise OSError("refusal journal changed")
                failures = json.loads(refusal_raw)["rows"]
            except (OSError, Unreadable, ValueError, KeyError):
                self.unknown.add("refusal-integrity-unavailable")
                failures = [r for r in self.rows if r["kind"] == "refusal"]
            events = [{key: row[key] for key in (*asdict(self.bindings[row["role"]]), "elapsed")} | {
                "op": row["operation"]} for row in self.rows if row["kind"] == "operation"]
            if "journal-integrity-unavailable" in self.unknown:
                events = []
                if "refusal-integrity-unavailable" in self.unknown:
                    failures = []
            return {"status": "UNKNOWN" if self.unknown else "COMPLETE", "unknown": sorted(self.unknown),
                    "refusals": failures, "events": events,
                    "journal_sha256": self.expected_digest,
                    "refusal_sha256": self.refusal_digest,
                    "task_success": "UNASSESSED"}
