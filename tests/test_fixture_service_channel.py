"""The fixture service through the isolated path (#276): a REAL
`DecideReplyChannel` socket, the REAL `docker/trial/skillc-gh-shim.py` as a
subprocess, and adversarial deterministic clients speaking the wire protocol
directly. The observed effects - the remote's refs and what the shim printed
- must equal the controller's record.

Also holds orchestrator ruling (a)'s condition: on the one shared socket,
gh requests never reach the gate witness's ops and vice versa, including a
crafted request carrying both sides' fields.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from test_fixture_service import World, _git

from skillc import fixture_service as fs
from skillc.decide_reply_channel import DecideReplyChannel

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
needs_jq = pytest.mark.skipif(fs.measure_jq()[0] is None, reason="jq 1.7.x is not installed")

SHIM = Path(__file__).resolve().parent.parent / "docker" / "trial" / "skillc-gh-shim.py"
GATE_KEYS = frozenset({"op", "gate", "cwd"})
READY_KEYS = frozenset({"op", "nonce"})


class Harness:
    def __init__(self, world: World, service: fs.FixtureService, socket_path: Path) -> None:
        self.world, self.service, self.socket_path = world, service, socket_path
        self.gate_requests: list[Mapping[str, object]] = []
        self.ready_requests: list[Mapping[str, object]] = []

    def shim(self, *argv: str, cwd: Path | None = None, stdin: str | None = None
             ) -> subprocess.CompletedProcess[str]:
        env = {"PATH": "/usr/bin:/bin", "SKILLC_TRIGGER_SOCKET": str(self.socket_path), "HOME": str(cwd or
               self.world.work), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        return subprocess.run([sys.executable, str(SHIM), *argv], cwd=str(cwd or self.world.work), env=env,
                              input=stdin, capture_output=True, text=True, timeout=30, check=False)

    def raw(self, request: Mapping[str, Any]) -> dict[str, Any]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(10)
            sock.connect(str(self.socket_path))
            sock.sendall(json.dumps(request).encode() + b"\n")
            sock.shutdown(socket.SHUT_WR)
            data = b""
            while chunk := sock.recv(65536):
                data += chunk
        return json.loads(data)


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    world = World(tmp_path)
    service = world.service()
    short = Path(tempfile.mkdtemp(prefix="fs-"))  # AF_UNIX paths are short
    socket_path = short / "trigger.sock"
    h = Harness(world, service, socket_path)

    def gate(request: Mapping[str, object]) -> Mapping[str, object]:
        h.gate_requests.append(dict(request))
        return {"exit_code": 0, "reason": "exited", "stdout": "", "stderr": ""}

    def ready(request: Mapping[str, object]) -> Mapping[str, object]:
        h.ready_requests.append(dict(request))
        return {"nonce": request["nonce"]}

    decide = fs.dispatch({"gh": (service.decide, fs.REQUEST_KEYS), "run_gate": (gate, GATE_KEYS),
                          "witness_ready": (ready, READY_KEYS)})
    channel = DecideReplyChannel(socket_path, decide, "attempt-1")
    channel.start()
    try:
        yield h
    finally:
        channel.stop_and_finalize()
        shutil.rmtree(short, ignore_errors=True)


@needs_jq
def test_shim_lifecycle_effects_equal_the_controller_record(harness: Harness) -> None:
    (harness.world.work / "body.md").write_text("Closes #3\n")
    created = harness.shim("pr", "create", "--title", "feat: the feature", "--body-file", "body.md")
    assert created.returncode == 0, created.stderr
    merged = harness.shim("pr", "merge", "--squash")  # no number: the PR for the current branch
    assert merged.returncode == 0, merged.stderr
    state = harness.shim("pr", "view", "--json", "state", "--jq", ".state")
    assert state.stdout == "MERGED\n"
    record = harness.service.finalize("attempt-1")
    events = record.events
    assert [e["op"] for e in events] == ["pr.create", "pr.merge", "pr.view"]
    # What the subject saw is exactly what the controller recorded it was sent.
    assert [e["reply"]["stdout"] for e in events] == [created.stdout, merged.stdout, state.stdout]
    assert events[0]["context"]["branch"] == "feature"
    assert events[1]["effect"]["merge_commit"] == harness.world.main()
    assert events[1]["effect"]["closed_issues"] == [3]
    assert record.remote_integrity == "SATISFIED"


def test_concurrent_duplicate_creates_yield_exactly_one_pr(harness: Harness) -> None:
    results: list[subprocess.CompletedProcess[str]] = []
    threads = [threading.Thread(target=lambda: results.append(
        harness.shim("pr", "create", "--title", "a", "--body", "b"))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.returncode for r in results) == [0, 1, 1, 1]
    record = harness.service.finalize("attempt-1")
    assert [e["reason"] for e in record.events].count("duplicate-create") == 3
    assert sorted(record.final_state["prs"]) == ["2", "4"]


def test_shim_in_a_foreign_checkout_is_wrong_repository(harness: Harness, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    _git(other, "remote", "add", "origin", "/elsewhere/widget.git")
    reply = harness.shim("issue", "view", "1", cwd=other)
    assert reply.returncode == 1
    assert harness.service._events[-1]["reason"] == "wrong-repository"


def test_shim_without_a_channel_exits_125(harness: Harness) -> None:
    harness.socket_path = harness.socket_path.with_name("absent.sock")
    reply = harness.shim("auth", "status")
    assert reply.returncode == 125 and "channel error" in reply.stderr
    assert harness.service._events == []


# --- ruling (a): one socket, isolated sides --------------------------------------

@pytest.mark.parametrize("request_", [
    {"op": "gh", "argv": ["pr", "merge", "4", "--squash"], "gate": "flow-check-plan"},
    {"op": "gh", "argv": ["auth", "status"], "nonce": "n"},
    {"op": "run_gate", "gate": "flow-check-plan", "argv": ["pr", "merge", "4", "--squash"]},
    {"op": "run_gate", "gate": "flow-check-plan", "context": {"branch": "main"}},
    {"op": "witness_ready", "nonce": "n", "argv": ["auth", "status"]},
    {"op": "pr", "argv": ["merge", "4"]},
    {"argv": ["auth", "status"]},
])
def test_mixed_or_unenabled_requests_reach_neither_side(harness: Harness, request_: dict[str, Any]) -> None:
    reply = harness.raw(request_)
    assert reply["ok"] is False
    assert harness.gate_requests == [] and harness.ready_requests == []
    assert harness.service._events == []  # refused before the service is reached


def test_each_side_still_answers_its_own_ops(harness: Harness) -> None:
    assert harness.raw({"op": "run_gate", "gate": "flow-check-plan", "cwd": "/work"})["ok"] is True
    assert harness.raw({"op": "witness_ready", "nonce": "n"})["ok"] is True
    assert harness.raw({"op": "gh", "argv": ["auth", "status"], "context": {
        "origin_url": str(harness.world.bare), "branch": None}})["ok"] is True
    assert len(harness.gate_requests) == 1 and len(harness.ready_requests) == 1
    assert [e["op"] for e in harness.service._events] == ["auth.status"]


def test_dispatch_refuses_a_route_whose_key_set_omits_op() -> None:
    with pytest.raises(ValueError):
        fs.dispatch({"gh": (lambda r: {}, frozenset({"argv"}))})


# --- raw-socket forgery -----------------------------------------------------------

def test_a_raw_client_cannot_inject_history(harness: Harness) -> None:
    forged = harness.raw({"op": "gh", "argv": ["pr", "list"], "seq": 1,
                          "context": {"origin_url": str(harness.world.bare), "branch": "feature"}})
    assert forged["ok"] is False
    honest = harness.raw({"op": "gh", "argv": ["pr", "create", "--title", "a", "--body", "b"],
                          "context": {"origin_url": str(harness.world.bare), "branch": "feature"}})
    assert honest["ok"] is True and honest["result"]["exit_code"] == 0
    record = harness.service.finalize("attempt-1")
    assert [e["seq"] for e in record.events] == [1]  # the controller numbers, the "seq": 1 claim did nothing
    assert record.events[0]["op"] == "pr.create"
