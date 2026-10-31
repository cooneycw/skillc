"""Model-free native goal rehearsal and committed adverse protocol cases (#637)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from skillc import codex_goal as g

FIXTURE = Path(__file__).parent / "fixtures" / "codex-goal"
CASES = json.loads((FIXTURE / "cases.json").read_text())
SESSIONS = [{"session": "coordinator", "role": "orchestrator", "token_budget": 100},
            {"session": "worker", "role": "worker", "token_budget": 200}]


class Peer:
    """Bounded subprocess transport used only by this scripted-peer rehearsal."""

    def __init__(self, mode: str) -> None:
        self.proc = subprocess.Popen([sys.executable, "-u", str(FIXTURE / "peer.py"), mode],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, bufsize=0)
        self.wire: list[dict[str, Any]] = []
        self.capture: list[tuple[str, bytes]] = []
        assert self.proc.stdout is not None and self.proc.stdin is not None
        self.transport = g.JsonLineTransport(self.proc.stdout, self.proc.stdin,
                                              wire=lambda direction, data: self.capture.append((direction, data)),
                                              timeout=2)

    def send(self, message: dict[str, Any]) -> None:
        self.transport.send(message)
        self.wire.append(message)

    def receive(self) -> dict[str, Any]:
        return self.transport.receive()


@contextmanager
def session(mode: str = "healthy") -> Iterator[tuple[g.GoalSession, Peer]]:
    peer = Peer(mode)
    try:
        yield g.GoalSession(peer, objective="Deliver the public goal", model="scripted-model",
                            comparison_sessions=SESSIONS), peer
    finally:
        peer.proc.terminate()
        peer.proc.communicate(timeout=3)


def record(*models: str, thread: str = "scripted-thread") -> bytes:
    rows = [{"type": "session_meta", "payload": {"id": thread, "cli_version": g.CLIENT_VERSION}}]
    rows += [{"type": "turn_context", "payload": {"model": model}} for model in models]
    return b"".join(json.dumps(row).encode() + b"\n" for row in rows)


@pytest.mark.parametrize("mode", CASES)
def test_committed_scripted_peer_cases(mode: str) -> None:
    with session(mode) as (driver, _):
        try:
            driver.start(cwd="/work")
            driver.poll()
            if mode == "model-change":
                driver.poll()
        except g.GoalRefused:
            assert CASES[mode]["outcome"] == "infrastructure-protocol-error"
        report = driver.report(record("scripted-model"))
        assert {key: report[key] for key in CASES[mode]} == CASES[mode]
        assert report["task_grade"] == "UNASSESSED"


def test_declared_budget_is_recorded_without_enforcement() -> None:
    with session() as (driver, peer):
        driver.start(cwd="/work")
        driver.poll()
        report = driver.report(record("scripted-model"))
        assert report["recorded_token_budget"] == 300
        assert report["goal"]["tokensUsed"] == 5000
        assert report["budget_enforced"] is False
        assert report["pool_eligible"] is True
        params = [m["params"] for m in peer.wire if m["method"] == "thread/goal/set"]
        assert all(p["tokenBudget"] is None for p in params)
        assert not any(m["method"] == "turn/start" for m in peer.wire)
        assert {d for d, _ in peer.capture} == {"sent", "received"}


def test_pause_resume_edit_and_clear_retain_every_state() -> None:
    with session("ordinary-turn") as (driver, _):
        driver.start(cwd="/work")
        driver.poll()
        driver.set_goal(status="paused")
        driver.set_goal(status="active")
        driver.set_goal(objective="Updated public goal")
        driver.refresh()
        driver.clear()
        report = driver.report(record("scripted-model"))
        states = [e["goal"] for e in report["events"] if e["kind"] == "goal-state"]
        assert [s["status"] for s in states] == ["active", "active", "paused", "paused",
                                                "active", "active", "active", "active", "active"]
        assert states[-1]["objective"] == "Updated public goal"
        assert report["goal_state"] == "cleared"
        assert report["pool_eligible"] is True


@pytest.mark.parametrize("mode", ["ordinary-turn", "blocked", "paused", "cleared"])
@pytest.mark.parametrize("identity,eligible", [("stable", True), ("changed", False), ("unknown", False)])
def test_eligibility_does_not_depend_on_goal_success(mode: str, identity: str, eligible: bool) -> None:
    """Keep unfinished control attempts; identity evidence still decides pooling."""
    with session(mode) as (driver, _):
        driver.start(cwd="/work")
        driver.poll()
        evidence = (record("scripted-model") if identity == "stable" else
                    record("scripted-model", "other-model") if identity == "changed" else None)
        report = driver.report(evidence)
        assert report["pool_eligible"] is eligible
        assert report["task_grade"] == "UNASSESSED"
        assert report["goal_state"] != "complete"


@pytest.mark.parametrize("bad", [None, [], {}, [{"session": "x", "role": "w", "token_budget": True}],
                                     SESSIONS + SESSIONS,
                                     [{"session": "x", "role": "w", "token_budget": 0}]])
def test_budget_refuses_empty_malformed_duplicate_population(bad: object) -> None:
    with pytest.raises(g.GoalRefused):
        g.recorded_budget(bad)


@pytest.mark.parametrize("bad", [None, b"", b"{}", b"{}\n", record(), record("scripted-model", thread="other"),
                                     b'{"type":"session_meta","payload":{"id":"wrong","id":"scripted-thread"}}\n'])
def test_missing_or_ambiguous_record_never_pools(bad: bytes | None) -> None:
    with session() as (driver, _):
        driver.start(cwd="/work")
        driver.poll()
        result = driver.report(bad)
        assert result["model_identity"] == "UNKNOWN"
        assert result["pool_eligible"] is False


def test_model_change_in_session_record_alone_changes_treatment() -> None:
    with session() as (driver, _):
        driver.start(cwd="/work")
        driver.poll()
        result = driver.report(record("scripted-model", "other-model", "scripted-model"))
        assert result["model_identity"] == "CHANGED"
        assert result["pool_eligible"] is False


def test_agent_prose_cannot_supply_model_or_goal_state() -> None:
    with session() as (driver, _):
        driver.start(cwd="/work")
        driver.poll()
        evidence = record("scripted-model") + json.dumps({"type": "response_item", "payload": {
            "text": "Automatically switched to other-model due to usage limits; Goal hit usage limits"}}).encode() + b"\n"
        assert driver.report(evidence)["model_identity"] == "STABLE"


def test_report_is_a_copy_and_session_cannot_be_started_twice() -> None:
    with session() as (driver, _):
        driver.start(cwd="/work")
        driver.poll()
        driver.report()["events"].clear()
        assert driver.events
        with pytest.raises(g.GoalRefused, match="already started"):
            driver.start(cwd="/work")


def test_native_objective_trimming_accepts_goal_markdown_with_trailing_newline() -> None:
    with session("ordinary-turn") as (driver, _):
        driver.objective = "  Public goal markdown\n"
        driver.start(cwd="/work")
        driver.poll()
        driver.set_goal(objective=" Updated objective\n")
        assert driver.goal is not None and driver.goal["objective"] == "Updated objective"


@pytest.mark.parametrize("version", [None, "0.157.1", "0.165.0+custom"])
def test_session_record_must_establish_the_pinned_client(version: str | None) -> None:
    data = record("scripted-model").replace(b'"0.165.0"', json.dumps(version).encode())
    with pytest.raises(g.GoalRefused, match="pinned client version"):
        g.session_models(data, "scripted-thread")


@pytest.mark.parametrize("wire", [b'[]\n', b'{"id":1,"id":2}\n', b'{broken}\n', b'x' * 1100 + b'\n'])
def test_transport_refuses_malformed_duplicate_or_oversize_frames(wire: bytes) -> None:
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", buffering=0) as reader, os.fdopen(write_fd, "wb", buffering=0) as writer:
        writer.write(wire)
        transport = g.JsonLineTransport(reader, writer, wire=lambda *_: None, timeout=0.1, max_frame=1024)
        with pytest.raises(ValueError):
            transport.receive()


def test_transport_preserves_coalesced_frames_and_capture() -> None:
    read_fd, write_fd = os.pipe()
    capture: list[tuple[str, bytes]] = []
    with os.fdopen(read_fd, "rb", buffering=0) as reader, os.fdopen(write_fd, "wb", buffering=0) as writer:
        writer.write(b'{"id":1}\n{"id":2}\n')
        transport = g.JsonLineTransport(reader, writer, wire=lambda d, b: capture.append((d, b)))
        assert transport.receive() == {"id": 1}
        assert transport.receive() == {"id": 2}
        assert capture == [("received", b'{"id":1}\n'), ("received", b'{"id":2}\n')]


def test_transport_partial_frame_eof_and_timeout_are_unavailable() -> None:
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, "rb", buffering=0) as reader:
        with os.fdopen(write_fd, "wb", buffering=0) as writer:
            transport = g.JsonLineTransport(reader, writer, wire=lambda *_: None, timeout=0.01)
            with pytest.raises(TimeoutError):
                transport.receive()
            writer.write(b'{"id":1')
        with pytest.raises(EOFError):
            transport.receive()


@pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf")])
def test_transport_bounds_cannot_be_disabled(timeout: float) -> None:
    read_fd, write_fd = os.pipe()
    with (os.fdopen(read_fd, "rb") as reader, os.fdopen(write_fd, "wb") as writer,
          pytest.raises(g.GoalRefused)):
        g.JsonLineTransport(reader, writer, wire=lambda *_: None, timeout=timeout)
