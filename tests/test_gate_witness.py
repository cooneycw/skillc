"""Tests for the controller-owned gate-execution witness (#269).

Exercised directly (calling `decide()`) for the bulk of the logic, plus one
integration test wiring a real `DecideReplyChannel` (#183) end to end, to
prove the two modules actually compose - not just that each one's own
tests pass in isolation.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from skillc.decide_reply_channel import ChannelRefusal, DecideReplyChannel
from skillc.gate_witness import GateWitness, GateWitnessRecord


def _fixed_tree_digest() -> str:
    return "sha256:fixed-for-test"


def test_declared_gates_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        GateWitness(declared_gates=(), tree_digest_fn=_fixed_tree_digest)


def test_a_complete_gate_is_confirmed_with_its_own_timestamps_and_tree_digest() -> None:
    witness = GateWitness(declared_gates=("lint",), tree_digest_fn=_fixed_tree_digest)
    witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "inv-1"})
    witness.decide({"op": "gate_complete", "invocation_id": "inv-1", "exit_code": 0})
    record = witness.finalize("a-1")
    gate = record.gates["lint"]
    assert gate.coverage == "complete"
    assert gate.exit_code == 0
    assert gate.tree_digest_at_start == "sha256:fixed-for-test"
    assert gate.started_at is not None and gate.completed_at is not None
    assert gate.completed_at >= gate.started_at
    assert gate.execution_observed() == ("CONFIRMED", None)


def test_a_nonzero_exit_code_is_still_confirmed_execution() -> None:
    """Exit code is not execution (design doc §5) - a FAILED gate is still
    a gate the controller watched start and finish."""
    witness = GateWitness(declared_gates=("lint",), tree_digest_fn=_fixed_tree_digest)
    witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "inv-1"})
    witness.decide({"op": "gate_complete", "invocation_id": "inv-1", "exit_code": 1})
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "complete"
    assert gate.exit_code == 1
    assert gate.execution_observed() == ("CONFIRMED", None)


def test_an_undeclared_gate_start_is_refused() -> None:
    """Red case 1 (design doc §8): the controller's own declared set is
    the only source of truth for what may be started."""
    witness = GateWitness(declared_gates=("lint",), tree_digest_fn=_fixed_tree_digest)
    with pytest.raises(ChannelRefusal, match="not a declared gate"):
        witness.decide({"op": "gate_start", "gate": "typecheck", "invocation_id": "inv-1"})
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "not-observed"  # the refusal left the declared gate untouched


def test_a_second_start_for_an_already_started_gate_is_refused() -> None:
    """Red case 2: one start per declared gate per attempt - a subject
    cannot paper over an unfavourable first attempt with a second one."""
    witness = GateWitness(declared_gates=("lint",), tree_digest_fn=_fixed_tree_digest)
    witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "inv-1"})
    with pytest.raises(ChannelRefusal, match="already has a start"):
        witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "inv-2"})


def test_a_second_start_after_completion_is_also_refused() -> None:
    witness = GateWitness(declared_gates=("lint",), tree_digest_fn=_fixed_tree_digest)
    witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "inv-1"})
    witness.decide({"op": "gate_complete", "invocation_id": "inv-1", "exit_code": 0})
    with pytest.raises(ChannelRefusal, match="already has a start"):
        witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "inv-2"})


def test_an_invocation_id_cannot_be_reused_across_different_gates() -> None:
    """Red case 6 (codex code_review of #269): `invocation_id` is
    subject-generated and opaque (design doc §3) - a subject reusing it
    across two gates (deliberately, or by OS pid reuse, since a
    subject-generated id is commonly a pid) must not let one gate's
    completion be credited to another."""
    witness = GateWitness(declared_gates=("lint", "typecheck"), tree_digest_fn=_fixed_tree_digest)
    witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "x"})
    with pytest.raises(ChannelRefusal, match="already reserved"):
        witness.decide({"op": "gate_start", "gate": "typecheck", "invocation_id": "x"})
    # lint's own state is untouched by the refused collision, and typecheck
    # never started - completing "x" must still resolve to lint alone.
    witness.decide({"op": "gate_complete", "invocation_id": "x", "exit_code": 0})
    record = witness.finalize("a-1")
    assert record.gates["lint"].coverage == "complete"
    assert record.gates["typecheck"].coverage == "not-observed"


def test_an_invocation_id_stays_reserved_after_its_gate_completes() -> None:
    """The reservation in `_decide_start` is for the life of the attempt,
    never released on completion - a closed gate's id cannot be recycled
    onto a different gate either."""
    witness = GateWitness(declared_gates=("lint", "typecheck"), tree_digest_fn=_fixed_tree_digest)
    witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "x"})
    witness.decide({"op": "gate_complete", "invocation_id": "x", "exit_code": 0})
    with pytest.raises(ChannelRefusal, match="already reserved"):
        witness.decide({"op": "gate_start", "gate": "typecheck", "invocation_id": "x"})


def test_a_completion_with_no_matching_open_start_is_refused_unknown_id() -> None:
    """Red case 3a: a bare completion naming an id nothing ever opened -
    'a received request alone is not completion' (#269's own wording)."""
    witness = GateWitness(declared_gates=("lint",), tree_digest_fn=_fixed_tree_digest)
    with pytest.raises(ChannelRefusal, match="does not match a gate currently open"):
        witness.decide({"op": "gate_complete", "invocation_id": "never-started", "exit_code": 0})


def test_a_replayed_completion_for_an_already_closed_invocation_is_refused() -> None:
    """Red case 3b: a second gate_complete for an invocation already
    closed by its own, genuine first completion - a replay."""
    witness = GateWitness(declared_gates=("lint",), tree_digest_fn=_fixed_tree_digest)
    witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "inv-1"})
    witness.decide({"op": "gate_complete", "invocation_id": "inv-1", "exit_code": 0})
    with pytest.raises(ChannelRefusal, match="does not match a gate currently open"):
        witness.decide({"op": "gate_complete", "invocation_id": "inv-1", "exit_code": 1})
    # the first, genuine completion is unaffected by the refused replay
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "complete"
    assert gate.exit_code == 0


def test_an_interrupted_gate_is_confirmed_but_distinct_from_complete_and_not_observed() -> None:
    """Red case 4: started, never completed - 'interrupted', never
    collapsed into either neighbouring state."""
    witness = GateWitness(declared_gates=("lint", "typecheck"), tree_digest_fn=_fixed_tree_digest)
    witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "inv-1"})
    # typecheck never contacted at all
    record = witness.finalize("a-1")
    lint = record.gates["lint"]
    typecheck = record.gates["typecheck"]
    assert lint.coverage == "interrupted"
    assert lint.completed_at is None
    assert lint.exit_code is None
    assert lint.execution_observed() == ("CONFIRMED", None)
    assert typecheck.coverage == "not-observed"
    assert typecheck.execution_observed() == ("UNKNOWN", "no-controller-witness")
    assert lint.coverage != typecheck.coverage  # the two must not collapse into one


def test_a_fully_bypassed_declared_gate_is_unknown_never_not_confirmed() -> None:
    """Red case 5: the full bypass. A declared gate the subject never
    contacts the channel about at all."""
    witness = GateWitness(declared_gates=("lint",), tree_digest_fn=_fixed_tree_digest)
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "not-observed"
    status, reason = gate.execution_observed()
    assert status == "UNKNOWN"
    assert reason == "no-controller-witness"
    assert status != "NOT_CONFIRMED"


def test_channel_unavailable_covers_every_declared_gate_distinctly_from_not_observed() -> None:
    witness = GateWitness(declared_gates=("lint", "typecheck"), tree_digest_fn=_fixed_tree_digest)
    witness.channel_unavailable = True
    record = witness.finalize("a-1")
    for gate in record.gates.values():
        assert gate.coverage == "channel-unavailable"
        assert gate.execution_observed() == ("UNKNOWN", "channel-unavailable")


def test_execution_observed_never_returns_not_confirmed_for_any_coverage() -> None:
    """Decision (orchestrator ruling): NOT_CONFIRMED is never produced by
    this witness, for any of its four coverage states."""
    from skillc.gate_witness import GateRecord
    for coverage in ("complete", "interrupted", "not-observed", "channel-unavailable"):
        status, _ = GateRecord(coverage=coverage).execution_observed()
        assert status != "NOT_CONFIRMED"


def test_gate_witness_record_round_trips_as_json_with_every_declared_gate_present() -> None:
    witness = GateWitness(declared_gates=("lint", "typecheck"), tree_digest_fn=_fixed_tree_digest)
    witness.decide({"op": "gate_start", "gate": "lint", "invocation_id": "inv-1"})
    witness.decide({"op": "gate_complete", "invocation_id": "inv-1", "exit_code": 0})
    record = witness.finalize("a-1")
    parsed = json.loads(record.to_json_bytes().decode("utf-8"))
    assert parsed["kind"] == "gate-witness"
    assert parsed["attempt_id"] == "a-1"
    assert set(parsed["declared_gates"]) == {"lint", "typecheck"}
    assert set(parsed["gates"].keys()) == {"lint", "typecheck"}  # absence is not a record
    assert parsed["gates"]["lint"]["coverage"] == "complete"
    assert parsed["gates"]["typecheck"]["coverage"] == "not-observed"


def test_an_unknown_op_is_refused() -> None:
    witness = GateWitness(declared_gates=("lint",), tree_digest_fn=_fixed_tree_digest)
    with pytest.raises(ChannelRefusal, match="unknown op"):
        witness.decide({"op": "something_else"})


# ------------------------------------------------- real channel integration


def _send(sock_path: Path, payload: dict[str, object]) -> dict[str, object]:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(5.0)
        s.connect(str(sock_path))
        s.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        s.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        s.close()
    result: dict[str, object] = json.loads(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"))
    return result


def test_gate_witness_composes_with_a_real_decide_reply_channel(tmp_path: Path) -> None:
    """Proves the two modules actually wire together, not just that each
    passes its own tests in isolation - a real socket, real connections,
    real DecideReplyChannel.decide dispatch into GateWitness.decide."""
    witness = GateWitness(declared_gates=("lint", "typecheck"), tree_digest_fn=_fixed_tree_digest)
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, witness.decide)
    channel.start()
    try:
        start_reply = _send(sock_path, {"op": "gate_start", "gate": "lint", "invocation_id": "inv-1"})
        assert start_reply == {"ok": True, "result": {"accepted": True}}
        complete_reply = _send(sock_path, {"op": "gate_complete", "invocation_id": "inv-1", "exit_code": 0})
        assert complete_reply == {"ok": True, "result": {"accepted": True}}
        bad_reply = _send(sock_path, {"op": "gate_start", "gate": "undeclared", "invocation_id": "inv-2"})
        assert bad_reply["ok"] is False
    finally:
        channel.stop_and_finalize()
    record = witness.finalize("a-1")
    assert record.gates["lint"].coverage == "complete"
    assert record.gates["typecheck"].coverage == "not-observed"


def test_concurrent_starts_for_different_gates_do_not_corrupt_each_others_state(tmp_path: Path) -> None:
    witness = GateWitness(declared_gates=("lint", "typecheck"), tree_digest_fn=_fixed_tree_digest)
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, witness.decide)
    channel.start()
    try:
        threads = [
            threading.Thread(target=_send, args=(sock_path, {"op": "gate_start", "gate": "lint", "invocation_id": "a"})),
            threading.Thread(target=_send, args=(sock_path, {"op": "gate_start", "gate": "typecheck", "invocation_id": "b"})),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        _send(sock_path, {"op": "gate_complete", "invocation_id": "a", "exit_code": 0})
        _send(sock_path, {"op": "gate_complete", "invocation_id": "b", "exit_code": 1})
    finally:
        channel.stop_and_finalize()
    record = witness.finalize("a-1")
    assert record.gates["lint"].coverage == "complete"
    assert record.gates["lint"].exit_code == 0
    assert record.gates["typecheck"].coverage == "complete"
    assert record.gates["typecheck"].exit_code == 1


def test_real_deterministic_processes_succeed_fail_and_interrupt_through_the_protected_path(
    tmp_path: Path,
) -> None:
    """#269's own acceptance bar (gate-witness.md §0): "Show real deterministic
    processes succeeding, failing and being interrupted through the protected
    path. No live model is required." A hand-crafted dict passed straight to
    `decide()` cannot show this - it proves the pairing logic, never that an
    actual OS process ran. This drives three REAL subprocesses (success, a
    non-zero exit, and one genuinely killed mid-run) through the real socket
    and real `DecideReplyChannel`, binding each `gate_complete.exit_code` to
    the process's own real return code - a synthetic process is still a real
    one, which is what "no live model required" means (raised by cross-model
    review, codex code_review of #269)."""
    witness = GateWitness(
        declared_gates=("succeeds", "fails", "interrupted"), tree_digest_fn=_fixed_tree_digest
    )
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, witness.decide)
    channel.start()
    try:
        _send(sock_path, {"op": "gate_start", "gate": "succeeds", "invocation_id": "s-1"})
        proc = subprocess.run([sys.executable, "-c", "raise SystemExit(0)"], check=False)
        _send(sock_path, {"op": "gate_complete", "invocation_id": "s-1", "exit_code": proc.returncode})

        _send(sock_path, {"op": "gate_start", "gate": "fails", "invocation_id": "f-1"})
        proc = subprocess.run([sys.executable, "-c", "raise SystemExit(7)"], check=False)
        _send(sock_path, {"op": "gate_complete", "invocation_id": "f-1", "exit_code": proc.returncode})

        _send(sock_path, {"op": "gate_start", "gate": "interrupted", "invocation_id": "i-1"})
        killed = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        killed.terminate()
        killed.wait(timeout=5.0)
        # Deliberately no gate_complete - the process was cut off, not finished.
    finally:
        channel.stop_and_finalize()
    record = witness.finalize("a-1")
    assert record.gates["succeeds"].coverage == "complete"
    assert record.gates["succeeds"].exit_code == 0
    assert record.gates["fails"].coverage == "complete"
    assert record.gates["fails"].exit_code == 7
    assert record.gates["interrupted"].coverage == "interrupted"
    for gate in ("succeeds", "fails", "interrupted"):
        status, reason = record.gates[gate].execution_observed()
        assert (status, reason) == ("CONFIRMED", None), gate


def test_gate_witness_record_is_a_frozen_value() -> None:
    record = GateWitnessRecord(attempt_id="a-1", declared_gates=("lint",), gates={})
    with pytest.raises(AttributeError):
        record.attempt_id = "a-2"  # type: ignore[misc]
