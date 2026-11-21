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


#: The helper owner the unit fixture models when the suite runs as root (CI).
MODEL_OWNER_UNDER_ROOT = 65534


def model_owner() -> int:
    """`operate(owner_uid=0)` is the PRODUCTION contract: every ancestor of
    the installed helpers root-owned and not group/world-writable, and a
    privilege drop to the candidate uid/gid. A pytest tmp path under /tmp
    (1777) can never meet it. So under root the fixture models a non-root
    owner, the same model the non-root lane gets from its own uid, and chowns
    the helper copies to it; operate() itself is unchanged."""
    return os.getuid() if os.getuid() != 0 else MODEL_OWNER_UNDER_ROOT


class LocalHelperExecutor:
    """Trusted unit fixture: real helpers, no container/liveness qualification."""

    def __init__(self, root: Path) -> None:
        self.scripts, self.shared = root / "scripts", root / "shared"
        self.scripts.mkdir()
        self.shared.mkdir()
        self.owner = model_owner()
        self.pins = {}
        for source in HELPERS.glob("*.sh"):
            dest = self.scripts / source.name
            shutil.copyfile(source, dest)
            # A real install is root-owned 0755; the operation refuses a group- or
            # world-writable helper, so the copy must not inherit a 0002 umask.
            os.chmod(dest, 0o755)
            if self.owner != os.getuid():
                os.chown(dest, self.owner, -1)
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
            "assignment_rev": assignment_rev, "commit": commit}, owner_uid=self.owner)
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
            assert tap.assign(binding.role), tap.rows[-1]
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


def _reenabled_old_join(plan: Any, evidence: Any, diagnostic: dict[str, Any]) -> Any:
    """BLIND TWIN: the pre-ruling join, re-enabled, feeding the tap's retained
    operations back into the verdict input as protocol rows. The real code has
    no such path; each control below asserts the twin's verdict DIFFERS."""
    from dataclasses import asdict, replace

    from skillc import live_wave as lw
    roles = []
    for binding, role in zip(plan.roles, evidence.roles, strict=True):
        base = {"wave_id": plan.wave_id, **{k: v for k, v in asdict(binding).items()
                                            if k != "required_artifacts"}}
        rows = [{**base, "op": op, "elapsed": float(i + 1)}
                for i, op in enumerate(diagnostic["roles"][binding.role]["ops"])]
        payload = b"".join(json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows)
        protocol = lw.Blob(payload, hashlib.sha256(payload).hexdigest()) if payload else None
        roles.append(replace(role, protocol=protocol, capture_complete=role.capture_complete
                             and diagnostic["status"] == "COMPLETE"))
    return replace(evidence, roles=tuple(roles))


@pytest.mark.parametrize("coverage_loss", [False, True])
def test_protocol_refusal_does_not_become_successful_ack(boundary: Any, coverage_loss: bool) -> None:
    from skillc.wave_tap_join import VERDICT_EFFECT, corroboration
    assert not request(boundary, seq=1)["accepted"]
    if coverage_loss:
        boundary.executor.available = False
        assert not request(boundary)["accepted"]
        boundary.executor.available = True
    assert request(boundary)["accepted"]
    assert request(boundary, "complete")["accepted"]
    boundary.executor.stopped = True
    collection = boundary.tap.finalize()
    plan = wave_inputs(boundary)[1]
    diagnostic = corroboration(plan, collection, boundary.tap.root)
    assert diagnostic["roles"][plan.roles[0].role]["ops"] == ["refused-protocol", "ack", "complete"]
    assert diagnostic["verdict_effect"] == VERDICT_EFFECT
    if coverage_loss:
        assert diagnostic["status"] == "UNKNOWN"


@pytest.mark.parametrize("fault", ["coverage", "custody", "participant-log", "wrong-task"])
def test_task_grade_and_protocol_completeness_are_both_required(boundary: Any, fault: str) -> None:
    """The tap never supplies protocol evidence, so without the client journal
    the verdict is UNKNOWN; a wrong delivered task still FAILs."""
    from skillc.wave_tap_join import corroboration
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
    diagnostic = corroboration(plan, collection, boundary.tap.root)
    if fault in ("coverage", "custody"):
        assert diagnostic["status"] == "UNKNOWN"
    if fault == "participant-log":
        assert diagnostic["roles"][plan.roles[0].role]["ops"] == []
    assert lw.verdict(plan, evidence, grade)["status"] == ("FAIL" if fault == "wrong-task" else "UNKNOWN")


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


def test_a_complete_tap_alone_cannot_pass_and_its_old_join_would(boundary: Any) -> None:
    """Ruling 7039734091: complete tap coverage and a correct task do NOT make a
    PASS, because the tap is not the verdict source. The re-enabled old join
    (the blind twin) would PASS the same inputs, so it DIFFERS."""
    from skillc.wave_tap_join import corroboration
    assert request(boundary)["accepted"]
    assert request(boundary, "complete")["accepted"]
    boundary.executor.stopped = True
    collection = boundary.tap.finalize()
    lw, plan, evidence, grade = wave_inputs(boundary)
    diagnostic = corroboration(plan, collection, boundary.tap.root)
    assert diagnostic["status"] == "COMPLETE"
    assert diagnostic["roles"][plan.roles[0].role]["ops"] == ["ack", "complete"]
    real = lw.verdict(plan, evidence, grade)
    blind = lw.verdict(plan, _reenabled_old_join(plan, evidence, diagnostic), grade)
    assert real["status"] == "UNKNOWN" and f"{plan.roles[0].role}:protocol-unavailable" in real["unknown"]
    assert blind["status"] == "PASS"
    assert real["status"] != blind["status"]


@pytest.mark.parametrize("lost", ["journal.json", "refusals.json"])
def test_known_refusal_survives_loss_of_other_custody(boundary: Any, lost: str) -> None:
    from skillc.wave_tap_join import corroboration
    assert not request(boundary, event={"op": "complete"})["accepted"]
    assert request(boundary)["accepted"]
    assert request(boundary, "complete")["accepted"]
    boundary.executor.stopped = True
    collection = boundary.tap.finalize()
    (boundary.tap.root / lost).write_bytes(b"{}")
    lw, plan, evidence, grade = wave_inputs(boundary)
    diagnostic = corroboration(plan, collection, boundary.tap.root)
    assert diagnostic["status"] == "UNKNOWN"
    assert "refused-protocol" in diagnostic["roles"][plan.roles[0].role]["ops"]
    assert lw.verdict(plan, evidence, grade)["status"] == "UNKNOWN"


def test_the_fixture_helpers_pass_operate_under_this_uid(tmp_path: Path) -> None:
    """Names the cause directly when the fixture cannot meet operate()'s
    contract under the running uid (root in CI, a service account on the
    runner), instead of surfacing as a refused assignment."""
    executor = LocalHelperExecutor(tmp_path)
    assert executor.owner != 0, "the unit fixture must never model the root contract"
    for name in executor.pins:
        info = os.lstat(executor.scripts / name)
        assert info.st_uid == executor.owner and not info.st_mode & 0o022, name
    binding = Binding("tap-wave", "worker-a", "attempt-a", SID, "quote-a", 0, 1, "task-nonce")
    receipt = executor.execute(binding, "assignment", "n" * 32, None, None)
    assert receipt["exit_code"] == 0 and receipt["effect"] is True, receipt
