"""Real helper/socket boundary controls with modeled container identity only."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import socket
import tempfile
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skillc import wave_tap_operation as operation
from skillc.decide_reply_channel import DecideReplyChannel
from skillc.wave_tap import Binding, Endpoint, HelperTap, verify_journal

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts"
CASES = json.loads((ROOT / "controls/wave-tap/refusals.json").read_text())
SID = "00000000-0000-0000-0000-000000000001"
HEADER = ("OpenAI Codex v0.157.1\n--------\nsession id: " + SID + "\n--------\n").encode()


class LocalHelperExecutor:
    """Trusted unit fixture: real helpers, no container/liveness qualification."""

    def __init__(self, root: Path) -> None:
        self.scripts, self.shared = root / "scripts", root / "shared"
        self.scripts.mkdir()
        self.shared.mkdir()
        self.pins = {}
        for source in HELPERS.glob("*.sh"):
            dest = self.scripts / source.name
            shutil.copyfile(source, dest)
            self.pins[source.name] = hashlib.sha256(dest.read_bytes()).hexdigest()
        self.stopped = False
        self.available = True
        self.calls: list[str] = []
        self.receipt_mutation: dict[str, Any] = {}

    def admitted(self, binding: Binding) -> bool:
        return self.available and not self.stopped

    def execute(self, binding: Binding, op: str, nonce: str,
                assignment_rev: int | None, commit: str | None) -> Any:
        self.calls.append(op)
        result = operation.operate({"scripts": str(self.scripts), "shared": str(self.shared),
            "pins": self.pins, "binding": asdict(binding), "operation": op, "nonce": nonce,
            "assignment_rev": assignment_rev, "commit": commit}, owner_uid=os.getuid())
        return {**result, **self.receipt_mutation}

    def retired(self, binding: Binding) -> bool:
        return self.stopped


@pytest.fixture
def boundary(tmp_path: Path) -> Iterator[Any]:
    binding = Binding("tap-wave", "worker-a", "attempt-a", SID, "quote-a", 0, 1, "task-nonce")
    executor = LocalHelperExecutor(tmp_path)
    tap = HelperTap((binding,), executor.pins, executor, tmp_path / "controller")
    endpoint = tap.open_turn(binding.role, HEADER)
    with tempfile.TemporaryDirectory(prefix="wave-tap-") as short:
        path = Path(short) / "role.sock"
        channel = DecideReplyChannel(path, lambda request: tap.request(endpoint, request), binding.attempt_id)
        channel.set_peer_authorizer(lambda pid, uid, gid: pid == os.getpid())
        tap.bind_channel(binding.role, channel)
        channel.start()
        try:
            assert tap.assign(binding.role)
            yield SimpleNamespace(binding=binding, executor=executor, tap=tap, endpoint=endpoint,
                                  channel=channel, socket=path)
        finally:
            channel.close()


def request(world: Any, op: str = "ack", **patch: Any) -> dict[str, Any]:
    payload = {"op": op, "binding": asdict(world.binding), "turn_nonce": world.endpoint.turn_nonce, **patch}
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(world.socket))
        client.sendall(json.dumps(payload).encode() + b"\n")
        with client.makefile("rb") as stream:
            reply = json.loads(stream.readline(16384))
    assert reply["ok"] is True, reply
    return reply["result"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_committed_refusal_controls_do_not_execute(boundary: Any, case: dict[str, Any]) -> None:
    patch = copy.deepcopy(case.get("patch", {}))
    if "binding_patch" in case:
        patch["binding"] = {**asdict(boundary.binding), **case["binding_patch"]}
    before = len(boundary.executor.calls)
    reply = request(boundary, **patch)
    assert reply["accepted"] is case["accepted"]
    assert len(boundary.executor.calls) == before + int(case["accepted"])
    assert boundary.tap.rows[-1]["kind"] == ("operation" if case["accepted"] else "refusal")
    assert verify_journal(boundary.tap.root, boundary.tap.expected_digest)


def test_actual_helpers_channel_join_and_integrity(boundary: Any) -> None:
    assert request(boundary)["accepted"]
    assert request(boundary, "complete", commit="1" * 40)["accepted"]
    boundary.tap.end_turn(boundary.endpoint)
    boundary.executor.stopped = True
    collected = boundary.tap.finalize()
    assert collected["status"] == "COMPLETE", collected
    assert [event["op"] for event in collected["events"]] == ["ack", "complete"]
    assert collected["task_success"] == "UNASSESSED"
    assert verify_journal(boundary.tap.root, collected["journal_sha256"])
    (boundary.tap.root / "journal.json").write_bytes(b"{}")
    assert not verify_journal(boundary.tap.root, collected["journal_sha256"])


@pytest.mark.parametrize("fault", ["effect", "nonce", "pins", "publication", "custody", "liveness"])
def test_unobservable_execution_cannot_become_complete(boundary: Any, monkeypatch: Any, fault: str) -> None:
    if fault == "effect":
        boundary.executor.receipt_mutation = {"effect": False}
    elif fault == "nonce":
        boundary.executor.receipt_mutation = {"nonce": "replayed"}
    elif fault == "pins":
        boundary.executor.receipt_mutation = {"pins_after": {}}
    elif fault == "publication":
        def unavailable() -> None:
            raise OSError("injected publication loss")
        monkeypatch.setattr(boundary.tap, "_publish", unavailable)
    elif fault == "custody":
        (boundary.tap.root / "journal.json").write_bytes(b"{}")
    else:
        boundary.executor.available = False
    assert not request(boundary)["accepted"]
    boundary.executor.stopped = True
    collected = boundary.tap.finalize()
    assert collected["status"] == "UNKNOWN"
    if fault == "custody":
        assert collected["events"] == []


def test_forged_context_and_missing_bootstrap_refuse(boundary: Any) -> None:
    forged = Endpoint(boundary.binding, boundary.endpoint.turn_nonce, object())
    before = len(boundary.executor.calls)
    assert not boundary.tap.request(forged, {"op": "ack"})["accepted"]
    assert len(boundary.executor.calls) == before
    with pytest.raises(ValueError, match="bootstrap"):
        boundary.tap.open_turn(boundary.binding.role, HEADER.replace(SID.encode(), b"obsolete"))


def test_real_helper_stdout_alone_without_effect_is_unavailable(boundary: Any, monkeypatch: Any) -> None:
    assert request(boundary)["accepted"]
    fake = SimpleNamespace(returncode=0, stdout=(b"FLOW_MAILBOX_WAVE=tap-wave\n"
        b"FLOW_MAILBOX_ROLE=orchestrator\nFLOW_MAILBOX_REV=1\nFLOW_MAILBOX: sent\n"), stderr=b"")
    monkeypatch.setattr(operation.subprocess, "run", lambda *args, **kwargs: fake)
    assert not request(boundary, "complete")["accepted"]


def test_duplicate_complete_is_preserved_for_verdict_join(boundary: Any) -> None:
    assert request(boundary)["accepted"]
    assert request(boundary, "complete")["accepted"]
    assert request(boundary, "complete")["accepted"]
    boundary.executor.stopped = True
    collected = boundary.tap.finalize()
    assert [row["op"] for row in collected["events"]] == ["ack", "complete", "complete"]


def test_missing_channel_and_unconfirmed_stop_are_unknown(boundary: Any) -> None:
    assert request(boundary)["accepted"]
    assert request(boundary, "complete")["accepted"]
    boundary.tap.channels.clear()
    collected = boundary.tap.finalize()
    assert collected["status"] == "UNKNOWN"
    assert "worker-a:stop-unconfirmed" in collected["unknown"]


def wave_inputs(world: Any, *, wrong_output: bool = False) -> Any:
    from skillc import live_wave as lw
    b = world.binding
    binding = lw.RoleBinding(b.role, b.attempt_id, b.session_id, b.task, b.generation,
                             b.revision, b.nonce, ("output.json",))
    plan = lw.WavePlan(b.wave_id, (binding,), b.role, 200)
    transcript = json.dumps({"type": "session_meta", "payload": {"id": b.session_id}}).encode() + b"\n"
    output = b'{}' if wrong_output else b'{"delivered":true}'
    role = lw.RoleEvidence(b.role, b.attempt_id, b.session_id,
        lw.Blob(transcript, hashlib.sha256(transcript).hexdigest()), None,
        {"output.json": lw.Blob(output, hashlib.sha256(output).hexdigest())},
        lw.PokeCount(b.role, b.session_id, 0), True, True, True, True, "exited", 0, stop_elapsed=100)
    evidence = lw.WaveEvidence(b.wave_id, (role,), 100, True)

    def grade(plan: Any, artifacts: Any) -> Any:
        return lw.DeliveryGrade("PASS" if artifacts[b.role]["output.json"] == b'{"delivered":true}' else "FAIL", 100)
    return lw, plan, evidence, grade


@pytest.mark.parametrize("coverage_loss", [False, True])
def test_protocol_refusal_does_not_become_successful_ack(boundary: Any, coverage_loss: bool) -> None:
    from skillc.wave_tap_join import protocol_evidence
    assert not request(boundary, seq=1)["accepted"]
    if coverage_loss:
        boundary.executor.available = False
        assert not request(boundary)["accepted"]
        boundary.executor.available = True
    assert request(boundary)["accepted"]
    assert request(boundary, "complete")["accepted"]
    boundary.executor.stopped = True
    collection = boundary.tap.finalize()
    lw, plan, evidence, grade = wave_inputs(boundary)
    joined = protocol_evidence(plan, evidence, collection, boundary.tap.root)
    assert joined.roles[0].protocol is not None
    ops = [json.loads(line)["op"] for line in joined.roles[0].protocol.data.splitlines()]
    assert ops == ["refused-protocol", "ack", "complete"]
    assert lw.verdict(plan, joined, grade)["status"] == "FAIL"


@pytest.mark.parametrize("fault", ["coverage", "custody", "participant-log", "wrong-task"])
def test_task_grade_and_protocol_completeness_are_both_required(boundary: Any, fault: str) -> None:
    from skillc.wave_tap_join import protocol_evidence
    if fault == "coverage":
        boundary.executor.available = False
        assert not request(boundary)["accepted"]
        boundary.executor.available = True
    if fault != "participant-log":
        assert request(boundary)["accepted"]
        assert request(boundary, "complete")["accepted"]
    boundary.executor.stopped = True
    collection = boundary.tap.finalize()
    if fault == "custody":
        (boundary.tap.root / "journal.json").write_bytes(b"{}")
    if fault == "participant-log":
        collection["events"] = [{"op": "ack"}, {"op": "complete"}]
    lw, plan, evidence, grade = wave_inputs(boundary, wrong_output=fault == "wrong-task")
    joined = protocol_evidence(plan, evidence, collection, boundary.tap.root)
    assert lw.verdict(plan, joined, grade)["status"] == ("FAIL" if fault == "wrong-task" else "UNKNOWN")


def test_real_dropped_connection_prevents_complete_coverage(boundary: Any) -> None:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        client.connect(str(boundary.socket))
        client.sendall(b"not-json\n")
        client.recv(1024)
    assert request(boundary)["accepted"]
    assert request(boundary, "complete")["accepted"]
    boundary.executor.stopped = True
    assert boundary.tap.finalize()["status"] == "UNKNOWN"


def test_pinned_helper_replacement_is_unavailable(boundary: Any) -> None:
    helper = boundary.executor.scripts / "flow-wave-mailbox.sh"
    helper.write_text("#!/bin/sh\nexit 0\n")
    assert not request(boundary)["accepted"]
    assert boundary.tap.rows[-1]["kind"] == "unavailable"


def test_complete_protocol_and_correct_task_can_pass(boundary: Any) -> None:
    from skillc.wave_tap_join import protocol_evidence
    assert request(boundary)["accepted"]
    assert request(boundary, "complete")["accepted"]
    boundary.executor.stopped = True
    collection = boundary.tap.finalize()
    lw, plan, evidence, grade = wave_inputs(boundary)
    joined = protocol_evidence(plan, evidence, collection, boundary.tap.root)
    assert lw.verdict(plan, joined, grade)["status"] == "PASS"


@pytest.mark.parametrize("lost", ["journal.json", "refusals.json"])
def test_known_refusal_survives_loss_of_other_custody(boundary: Any, lost: str) -> None:
    from skillc.wave_tap_join import protocol_evidence
    assert not request(boundary, event={"op": "complete"})["accepted"]
    assert request(boundary)["accepted"]
    assert request(boundary, "complete")["accepted"]
    boundary.executor.stopped = True
    collection = boundary.tap.finalize()
    (boundary.tap.root / lost).write_bytes(b"{}")
    lw, plan, evidence, grade = wave_inputs(boundary)
    joined = protocol_evidence(plan, evidence, collection, boundary.tap.root)
    assert not joined.roles[0].capture_complete
    assert lw.verdict(plan, joined, grade)["status"] == "FAIL"
