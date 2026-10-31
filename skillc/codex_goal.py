"""Native Codex goal control, protocol 0.165.0 (#637).

The caller owns the contained app-server transport, authorization, transcript
capture and process cleanup. This module never starts a client on the host.
It neither grades the task nor authorizes a live run. Native goals are uncapped:
the declaration's CPP-session total is recorded separately (#628 owner ruling).
"""

from __future__ import annotations

import copy
import json
import math
import os
import select
import time
from collections.abc import Callable
from typing import IO, Any, NoReturn, Protocol

CLIENT_VERSION = "0.165.0"
# Global server config gates ThreadGoal handlers; a per-thread override alone
# cannot enable them. The caller launches this argv only inside its trial.
APP_SERVER_ARGV = ("codex", "--enable", "goals", "--disable", "step_model_switching", "app-server")
STATUSES = frozenset({"active", "paused", "blocked", "usageLimited", "budgetLimited", "complete"})
TERMINAL = frozenset({"blocked", "usageLimited", "budgetLimited", "complete", "cleared"})


class GoalRefused(ValueError):
    """Missing, ambiguous or conflicting protocol evidence."""


class Transport(Protocol):
    """One already-contained, exclusive app-server connection.

    Implementations must bound reads/writes and raise on EOF, timeout or loss.
    receive returns exactly one complete JSON object, preserving notifications
    interleaved with responses. No notification may be silently dropped.
    """

    def send(self, message: dict[str, Any]) -> None: ...

    def receive(self) -> dict[str, Any]: ...


class JsonLineTransport:
    """Bounded stdio adapter for pipes to an app-server in the trial container.

    The container backend, not this adapter, starts/stops that process. wire
    receives every exact sent/received JSON line for controller-owned capture.
    timeout is a transport liveness bound, never a trial/goal wall-time budget.
    """

    def __init__(self, reader: IO[bytes], writer: IO[bytes], *,
                 wire: Callable[[str, bytes], None], timeout: float = 30.0,
                 max_frame: int = 4 * 1024 * 1024) -> None:
        if (type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300
                or type(max_frame) is not int or not 1024 <= max_frame <= 16 * 1024 * 1024):
            raise GoalRefused("invalid transport bounds")
        self.reader, self.writer, self.wire = reader, writer, wire
        self.timeout, self.max_frame = timeout, max_frame
        self.buffer = b""

    def send(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, ensure_ascii=False, allow_nan=False).encode() + b"\n"
        if len(data) > self.max_frame:
            raise GoalRefused("outgoing app-server frame too large")
        remaining_data = memoryview(data)
        deadline = time.monotonic() + self.timeout
        while remaining_data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.writer], [], remaining)[1]:
                raise TimeoutError("app-server write timeout")
            # <= PIPE_BUF after writability avoids a blocking large pipe write.
            count = os.write(self.writer.fileno(), remaining_data[:4096])
            if count <= 0:
                raise OSError("app-server write closed")
            remaining_data = remaining_data[count:]
        self.wire("sent", data)

    def receive(self) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while b"\n" not in self.buffer:
            if len(self.buffer) > self.max_frame:
                raise GoalRefused("incoming app-server frame too large")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.reader], [], [], remaining)[0]:
                raise TimeoutError("app-server read timeout")
            data = os.read(self.reader.fileno(), 65536)
            if not data:
                raise EOFError("app-server stream closed")
            self.buffer += data
        line, _, self.buffer = self.buffer.partition(b"\n")
        self.wire("received", line + b"\n")
        if len(line) > self.max_frame:
            raise GoalRefused("incoming app-server frame too large")
        value = json.loads(line, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise GoalRefused("app-server frame is not an object")
        return value


def _text(value: object, name: str, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise GoalRefused(f"invalid {name}")
    return value


def recorded_budget(sessions: object) -> int:
    """Sum every declared CPP role/session, refusing an empty population."""
    if not isinstance(sessions, list) or not sessions:
        raise GoalRefused("comparison session budget population is empty")
    seen: set[str] = set()
    total = 0
    for row in sessions:
        if not isinstance(row, dict) or set(row) != {"session", "role", "token_budget"}:
            raise GoalRefused("comparison budget rows must name session, role and token_budget")
        session = _text(row["session"], "session")
        _text(row["role"], "role")
        budget = row["token_budget"]
        if session in seen or type(budget) is not int or not 0 < budget <= 2**63 - 1:
            raise GoalRefused("duplicate session or invalid comparison token budget")
        seen.add(session)
        total += budget
    if total > 2**63 - 1:
        raise GoalRefused("comparison token budget sum overflows int64")
    return total


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GoalRefused("duplicate JSON member in session record")
        result[key] = value
    return result


def session_models(record: bytes, thread_id: str) -> tuple[str, ...]:
    """Models from complete caller-captured rollout bytes, never agent prose.

    The caller must bind these bytes to its immutable capture manifest. A
    startup model response alone cannot establish the model used on every turn.
    """
    if not record or not record.endswith(b"\n"):
        raise GoalRefused("missing or truncated session record")
    models: list[str] = []
    bound = False
    try:
        for index, line in enumerate(record.decode("utf-8").splitlines()):
            row = json.loads(line, object_pairs_hook=_unique)
            if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
                raise GoalRefused("malformed session record")
            payload = row["payload"]
            if index == 0:
                if row.get("type") != "session_meta" or payload.get("id") != thread_id:
                    raise GoalRefused("session record is not bound to the controlled thread")
                if payload.get("cli_version") != CLIENT_VERSION:
                    raise GoalRefused("session record does not establish the pinned client version")
                bound = True
            elif row.get("type") == "session_meta":
                raise GoalRefused("multiple session identities")
            if row.get("type") == "turn_context":
                model = _text(payload.get("model"), "observed model")
                models.append(model)
            if row.get("type") == "event_msg" and payload.get("type") == "model_rerouted":
                models.extend((_text(payload.get("from_model"), "source model"),
                               _text(payload.get("to_model"), "destination model")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GoalRefused("unreadable session record") from exc
    if not bound or not models:
        raise GoalRefused("session record contains no observed turn model")
    return tuple(models)


class GoalSession:
    """One thread on an exclusive connection; every goal mutation is retained.

    Lifecycle calls are explicit. poll() observes automatic native goal turns;
    a completed ordinary turn does not mean the goal completed. No client-side
    continuation prompt is invented. Results are diagnostic, never task grades.
    """

    def __init__(self, transport: Transport, *, objective: str, model: str,
                 comparison_sessions: object) -> None:
        self.transport = transport
        self.objective = _text(objective, "objective").strip()
        self.model = _text(model, "declared model")
        self.budget = recorded_budget(comparison_sessions)
        self.thread_id: str | None = None
        self.goal: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []
        self.observed_models: list[str] = []
        self._next_id = 0
        self._failed: str | None = None
        self._started = False
        self._cleared = False

    def _event(self, kind: str, **detail: Any) -> None:
        self.events.append(copy.deepcopy({"seq": len(self.events) + 1, "kind": kind, **detail}))

    def _fail(self, reason: str) -> NoReturn:
        self._failed = reason
        self._event("protocol-error", reason=reason)
        raise GoalRefused(reason)

    def _receive(self) -> dict[str, Any]:
        try:
            message = self.transport.receive()
        except (OSError, ValueError, EOFError) as exc:
            self._fail(f"transport receive failed: {type(exc).__name__}")
        if not isinstance(message, dict):
            self._fail("app-server message is not an object")
        return message

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._failed:
            raise GoalRefused(self._failed)
        self._next_id += 1
        request_id = self._next_id
        deadline = time.monotonic() + 30.0
        self._event("request", method=method, params=params)
        try:
            self.transport.send({"id": request_id, "method": method, "params": params})
        except (OSError, ValueError, TimeoutError) as exc:
            self._fail(f"transport send failed: {type(exc).__name__}")
        # Control RPCs must terminate even if a peer keeps sending unrelated
        # notifications. This is protocol-flood refusal, not a model token cap.
        for _ in range(10000):
            if time.monotonic() >= deadline:
                self._fail("app-server control request timed out")
            message = self._receive()
            if "id" not in message:
                self._notification(message)
                continue
            if type(message["id"]) is not int or message["id"] != request_id or "method" in message:
                self._fail("unexpected app-server response or server request")
            if "error" in message or not isinstance(message.get("result"), dict):
                self._fail("app-server request refused or response malformed")
            result = message["result"]
            self._event("response", method=method, result=result)
            return result
        self._fail("app-server notification flood during control request")

    def _goal(self, value: object, source: str) -> None:
        if not isinstance(value, dict) or value.get("threadId") != self.thread_id:
            self._fail("goal belongs to a different thread or is missing")
        if not isinstance(value.get("status"), str) or value["status"] not in STATUSES:
            self._fail("unknown goal status")
        if not isinstance(value.get("objective"), str) or not value["objective"].strip():
            self._fail("missing goal objective")
        for key in ("tokensUsed", "timeUsedSeconds", "createdAt", "updatedAt"):
            if type(value.get(key)) is not int or value[key] < 0:
                self._fail("invalid goal accounting")
        if value.get("tokenBudget") is not None:
            self._fail("native goal unexpectedly enforces a token budget")
        self.goal = copy.deepcopy(value)
        self._cleared = False
        self._event("goal-state", source=source, goal=value)

    def _notification(self, message: dict[str, Any]) -> None:
        method, params = message.get("method"), message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            self._fail("malformed notification")
        if "threadId" in params and params["threadId"] != self.thread_id:
            self._fail("notification belongs to a different thread")
        if method == "thread/goal/updated":
            self._goal(params.get("goal"), method)
        elif method == "thread/goal/cleared":
            if params.get("threadId") != self.thread_id:
                self._fail("cleared goal lacks thread identity")
            self.goal = None
            self._cleared = True
            self._event("goal-cleared")
        elif method == "model/rerouted":
            if params.get("threadId") != self.thread_id:
                self._fail("reroute lacks thread identity")
            try:
                self.observed_models.extend((_text(params.get("fromModel"), "source model"),
                                             _text(params.get("toModel"), "destination model")))
            except GoalRefused:
                self._fail("malformed model reroute")
            self._event("model-rerouted", params=params)
        elif method == "error":
            self._event("client-error", params=params)
            error = params.get("error")
            if isinstance(error, dict) and error.get("codexErrorInfo") == "usageLimitExceeded":
                self._event("usage-limited")
        # Full wire capture remains the transport owner's obligation, including
        # item content and automatic turns. Do not interpret arbitrary prose as
        # model identity, goal state, or a task grade.

    def start(self, *, cwd: str) -> None:
        if self._started:
            raise GoalRefused("goal session already started")
        self._started = True
        _text(cwd, "contained working directory")
        self._request("initialize", {"clientInfo": {"name": "skillc_goal", "version": "1"},
                                     "capabilities": {"experimentalApi": True}})
        self.transport.send({"method": "initialized", "params": {}})
        result = self._request("thread/start", {
            "model": self.model, "cwd": cwd, "approvalPolicy": "never",
            "allowProviderModelFallback": False, "sandbox": "danger-full-access",
            "config": {"features": {"goals": True, "step_model_switching": False}},
        })
        thread = result.get("thread")
        if not isinstance(thread, dict):
            self._fail("thread/start lacks thread")
        try:
            self.thread_id = _text(thread.get("id"), "thread identity")
            observed = _text(result.get("model"), "resolved model")
        except GoalRefused:
            self._fail("thread/start lacks identity or model")
        self.observed_models.append(observed)
        if observed != self.model:
            self._fail("thread/start resolved a different model")
        self.set_goal(objective=self.objective, status="active")
        # 0.165.0 goal/set applies its own idle-turn runtime effect. Sending an
        # extra turn/start would duplicate/steer the objective during that turn.

    def set_goal(self, *, objective: str | None = None, status: str = "active") -> None:
        if self.thread_id is None or status not in {"active", "paused"}:
            raise GoalRefused("goal mutation needs a started thread and active/paused status")
        params: dict[str, Any] = {"threadId": self.thread_id, "status": status,
                                  "origin": "user", "tokenBudget": None}
        if objective is not None:
            objective = _text(objective, "objective").strip()
            params["objective"] = objective
        result = self._request("thread/goal/set", params)
        self._goal(result.get("goal"), "thread/goal/set")
        if self.goal is None or self.goal["status"] != status:
            self._fail("goal set did not acknowledge requested status")
        if objective is not None and self.goal["objective"] != objective:
            self._fail("goal set did not acknowledge requested objective")

    def clear(self) -> None:
        if self.thread_id is None:
            raise GoalRefused("clear needs a started thread")
        result = self._request("thread/goal/clear", {"threadId": self.thread_id})
        if result.get("cleared") is not True:
            self._fail("goal clear was not acknowledged")
        self.goal = None
        self._cleared = True
        self._event("goal-cleared", source="thread/goal/clear")

    def refresh(self) -> None:
        """Read current native goal accounting without resetting its usage."""
        if self.thread_id is None:
            raise GoalRefused("get needs a started thread")
        result = self._request("thread/goal/get", {"threadId": self.thread_id})
        if result.get("goal") is None:
            self.goal = None
            self._cleared = True
            self._event("goal-cleared", source="thread/goal/get")
        else:
            self._goal(result["goal"], "thread/goal/get")

    def poll(self) -> None:
        """Consume one notification; caller controls capture and stop lifecycle."""
        if self._failed or self.thread_id is None:
            raise GoalRefused(self._failed or "poll needs a started thread")
        message = self._receive()
        if "id" in message:
            self._fail("unsolicited app-server response or request")
        self._notification(message)

    def report(self, session_record: bytes | None = None) -> dict[str, Any]:
        """Derive treatment identity separately from native goal outcome.

        A missing/unreadable session record is UNKNOWN and never poolable.
        Even a poolable completed goal still requires independent task grading.
        """
        models = list(self.observed_models)
        missing: str | None = None
        try:
            models.extend(session_models(session_record or b"", self.thread_id or ""))
        except GoalRefused as exc:
            missing = str(exc)
        identity = "CHANGED" if any(m != self.model for m in models) else (
            "UNKNOWN" if missing or self._failed else "STABLE")
        state = "cleared" if self._cleared else self.goal["status"] if self.goal else "unknown"
        usage_limited = state == "usageLimited" or any(e["kind"] == "usage-limited" for e in self.events)
        outcome = ("infrastructure-usage-limit" if usage_limited else
                   "infrastructure-protocol-error" if self._failed else
                   "goal-" + state)
        return copy.deepcopy({
            "version": 1, "declared_client_version": CLIENT_VERSION, "thread_id": self.thread_id,
            "declared_model": self.model, "observed_models": models,
            "model_identity": identity, "model_evidence_missing": missing,
            "recorded_token_budget": self.budget, "budget_enforced": False,
            "native_token_budget": None, "goal": self.goal, "goal_state": state,
            "outcome": outcome, "task_grade": "UNASSESSED",
            "pool_eligible": identity == "STABLE" and state == "complete" and not usage_limited,
            "events": self.events,
        })
