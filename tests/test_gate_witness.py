"""Tests for the controller-owned gate-execution witness (#269).

Exercised against a `_FakeBackend` test double (fast, in-process, scriptable
results and blocking) for the bulk of the logic, plus one integration test
against a REAL `DockerBackend` running the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`) through a REAL
`DecideReplyChannel` socket - proving the three modules actually compose end
to end with a real `ExecutionBackend.exec_in_attempt()` call, not a hand-crafted
dict, and that real OS processes succeed, fail and are interrupted through
the protected path (#269's own acceptance wording).
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import socket
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from skillc import docker_backend as d
from skillc.backend import BackendDescription, Confirmation, ExecuteResult, Limits
from skillc.decide_reply_channel import ChannelRefusal, DecideReplyChannel
from skillc.gate_witness import GateRecord, GateWitness, GateWitnessRecord

FAKE_DOCKER = Path(__file__).resolve().parent / "fixtures" / "docker-backend" / "fake_docker.py"


def _fixed_tree_digest() -> str:
    return "sha256:fixed-for-test"


def _limits(timeout: float = 5.0) -> Limits:
    return Limits(timeout=timeout)


# --------------------------------------------------------------- fake backend


@dataclass
class _FakeBackend:
    """Minimal `ExecutionBackend` test double: scriptable per-argv results,
    scriptable stdout for the subsequent `export()`, and a `block` set that
    makes `execute()` sleep well past any test's own timeout - the
    `interrupted`-by-teardown case needs a call that genuinely never
    returns before the channel tears down, not merely one that raises."""

    results: dict[tuple[str, ...], ExecuteResult] = field(default_factory=dict)
    stdout: dict[tuple[str, ...], str] = field(default_factory=dict)
    block: set[tuple[str, ...]] = field(default_factory=set)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    _last_stdout: str = ""

    def exec_in_attempt(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: object = None, stdin: object = None,
    ) -> ExecuteResult:
        key = tuple(argv)
        self.calls.append(key)
        if key in self.block:
            time.sleep(3600)
        self._last_stdout = self.stdout.get(key, "")
        return self.results[key]

    def export(self, handle: object, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "observations").write_text(self._last_stdout, encoding="utf-8")

    # The rest of `ExecutionBackend` is unused by `GateWitness` and
    # therefore never exercised through this double - stubbed only so
    # `_FakeBackend` structurally satisfies the full Protocol `GateWitness`
    # is typed against.
    def describe(self) -> BackendDescription:
        raise NotImplementedError

    def prepare(self, attempt_id: str) -> object:
        raise NotImplementedError

    def install(self, handle: object, surface: Mapping[str, object]) -> dict[str, object]:
        raise NotImplementedError

    def execute(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: object = None, stdin: object = None,
    ) -> ExecuteResult:
        raise NotImplementedError

    def confirm_stopped(self, handle: object) -> Confirmation:
        raise NotImplementedError

    def confirm_absent(self, handle: object) -> Confirmation:
        raise NotImplementedError

    def destroy(self, handle: object) -> None:
        raise NotImplementedError


def _exited(exit_code: int) -> ExecuteResult:
    return ExecuteResult(reason="exited", exit_code=exit_code)


# ------------------------------------------------------------------ construction


def test_declared_gates_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        GateWitness(
            declared_gates={}, tree_digest_fn=_fixed_tree_digest, backend=_FakeBackend(),
            handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
        )


def test_a_declared_gates_argv_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="non-empty argv"):
        GateWitness(
            declared_gates={"lint": []}, tree_digest_fn=_fixed_tree_digest, backend=_FakeBackend(),
            handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
        )


# --------------------------------------------------------------- happy paths


def test_a_complete_gate_is_confirmed_with_its_own_timestamps_and_tree_digest() -> None:
    backend = _FakeBackend(results={("lint",): _exited(0)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    reply = witness.decide({"op": "run_gate", "gate": "lint"})
    assert reply["accepted"] is True
    assert reply["exit_code"] == 0
    assert reply["reason"] == "exited"
    record = witness.finalize("a-1")
    gate = record.gates["lint"]
    assert gate.coverage == "complete"
    assert len(gate.runs) == 1
    run = gate.runs[0]
    assert run.exit_code == 0
    assert run.tree_digest_at_start == "sha256:fixed-for-test"
    assert run.completed_at is not None and run.completed_at >= run.requested_at
    assert gate.execution_observed() == ("CONFIRMED", None)


def test_a_nonzero_exit_code_that_still_exited_is_complete_coverage() -> None:
    """Exit code is not execution (design doc §5) - a FAILED gate that ran
    to its own natural end is still `complete`, never `interrupted`."""
    backend = _FakeBackend(results={("lint",): _exited(1)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    reply = witness.decide({"op": "run_gate", "gate": "lint"})
    assert reply["exit_code"] == 1
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "complete"
    assert gate.runs[0].exit_code == 1
    assert gate.execution_observed() == ("CONFIRMED", None)


@pytest.mark.parametrize("reason", ["timeout", "operator-cancelled"])
def test_a_gate_that_started_but_did_not_exit_cleanly_is_interrupted_not_complete(reason: str) -> None:
    """Orchestrator correction: a gate the controller started and that was
    cancelled or timed out is `interrupted` with the controller's own
    reason - NOT `complete` merely because `exec_in_attempt()` returned a
    result. Both of these `reason`s mean a real process genuinely began."""
    backend = _FakeBackend(results={("lint",): ExecuteResult(reason=reason, exit_code=None)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    reply = witness.decide({"op": "run_gate", "gate": "lint"})
    assert reply["reason"] == reason
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "interrupted"
    assert gate.execution_observed() == ("CONFIRMED", None)


@pytest.mark.parametrize("reason", ["launch-failed", "attempt-not-running", "unsupported"])
def test_a_gate_that_never_started_a_process_is_not_observed_never_confirmed(reason: str) -> None:
    """Codex `code_review` correction: these three `reason`s mean NO
    process ever started (never launched, refused before any attempt, or
    the backend cannot do this at all) - the first draft folded them into
    `interrupted`/`CONFIRMED`, which let a refused or never-launched exec
    report positive execution evidence, exactly the subject-authored-claim
    problem #269 exists to stop."""
    backend = _FakeBackend(results={("lint",): ExecuteResult(reason=reason, exit_code=None)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    reply = witness.decide({"op": "run_gate", "gate": "lint"})
    assert reply["reason"] == reason
    gate = witness.finalize("a-1").gates["lint"]
    if reason == "unsupported":
        # Sticky and attempt-wide (its own red case) - checked separately.
        assert gate.coverage == "channel-unavailable"
        assert gate.execution_observed() == ("UNKNOWN", "channel-unavailable")
    else:
        assert gate.coverage == "not-observed"
        assert gate.execution_observed() == ("UNKNOWN", "no-controller-witness")
        assert len(gate.runs) == 1  # recorded for transparency, just not counted as started


def test_an_undeclared_gate_is_refused() -> None:
    """Red case 1 (design doc §8): the controller's own declared set is
    the only source of truth for what may be run."""
    backend = _FakeBackend()
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    with pytest.raises(ChannelRefusal, match="not a declared gate"):
        witness.decide({"op": "run_gate", "gate": "typecheck"})
    assert backend.calls == []  # never even attempted
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "not-observed"


def test_an_unknown_op_is_refused() -> None:
    backend = _FakeBackend()
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    with pytest.raises(ChannelRefusal, match="unknown op"):
        witness.decide({"op": "something_else"})


# ------------------------------------------------------------ reruns and races


def test_a_concurrent_duplicate_run_gate_for_the_same_gate_is_refused() -> None:
    """Red case 2: a CONCURRENT duplicate (same gate, still executing) is
    refused. Uses a real `DecideReplyChannel` so the second request
    genuinely arrives while the first is still inside `execute()`."""
    backend = _FakeBackend(block={("lint",)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(timeout=3600), gate_exclusivity=False, exclusivity_basis="",
    )
    first_started = threading.Event()

    def run_first() -> None:
        first_started.set()
        witness.decide({"op": "run_gate", "gate": "lint"})

    t = threading.Thread(target=run_first, daemon=True)
    t.start()
    first_started.wait(timeout=5.0)
    time.sleep(0.2)  # let the first call actually enter `execute()` and block
    with pytest.raises(ChannelRefusal, match="already executing"):
        witness.decide({"op": "run_gate", "gate": "lint"})
    # the blocked first call is never joined - it would hang until process exit;
    # daemon=True keeps it from blocking the test session's own teardown.


def test_a_genuinely_stuck_call_reads_as_interrupted_confirmed_at_finalize() -> None:
    """Distinct from the exception path (`test_an_execute_exception_leaves_
    the_run_not_started_and_clears_in_flight`): a call still blocked INSIDE
    `exec_in_attempt()` when `finalize()` runs (the real teardown-cutoff
    case) means a process plausibly started and is in limbo - `_in_flight`
    stays `True` forever for this gate, which is what tells `finalize()`
    apart from the resolved-exception case where it was already cleared."""
    backend = _FakeBackend(block={("lint",)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(timeout=3600), gate_exclusivity=False, exclusivity_basis="",
    )
    first_started = threading.Event()

    def run_first() -> None:
        first_started.set()
        witness.decide({"op": "run_gate", "gate": "lint"})

    t = threading.Thread(target=run_first, daemon=True)
    t.start()
    first_started.wait(timeout=5.0)
    time.sleep(0.2)  # let the call actually enter exec_in_attempt() and block
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "interrupted"
    assert gate.execution_observed() == ("CONFIRMED", None)
    assert gate.runs[0].reason is None


def test_sequential_reruns_of_the_same_gate_are_both_recorded() -> None:
    """A rerun after the prior run resolved is not refused, and nothing
    already recorded is overwritten - the first run is still in the record
    even though the second, later run is what a reader would act on."""
    backend = _FakeBackend(results={("lint",): _exited(1)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    witness.decide({"op": "run_gate", "gate": "lint"})
    backend.results[("lint",)] = _exited(0)  # subject fixed it, rerun gate
    witness.decide({"op": "run_gate", "gate": "lint"})
    gate = witness.finalize("a-1").gates["lint"]
    assert len(gate.runs) == 2
    assert gate.runs[0].exit_code == 1  # the first, unfavourable run survives
    assert gate.runs[1].exit_code == 0
    assert gate.coverage == "complete"  # any run complete is enough


def test_an_execute_exception_leaves_the_run_not_started_and_clears_in_flight() -> None:
    """An exception out of `exec_in_attempt()` itself (an infrastructure
    fault, not a normal launch failure - those return a `reason` normally)
    must not be silently recorded as success, must not permanently wedge
    the gate as perpetually in-flight, and - codex `code_review` correction
    - must NOT report `CONFIRMED` execution: the exception path clears
    `_in_flight` before re-raising, which is exactly what distinguishes
    "never started" from a call genuinely still running when the channel
    tears down (see `test_a_rerun_is_still_possible_after_an_exception`)."""
    backend = _FakeBackend()

    def boom(handle: object, argv: Sequence[str], limits: Limits, cancel: object = None, stdin: object = None) -> ExecuteResult:
        raise RuntimeError("simulated backend crash")

    backend.exec_in_attempt = boom  # type: ignore[method-assign]
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    with pytest.raises(RuntimeError, match="simulated backend crash"):
        witness.decide({"op": "run_gate", "gate": "lint"})
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "not-observed"
    assert gate.execution_observed() == ("UNKNOWN", "no-controller-witness")
    assert gate.runs[0].reason is None


def test_a_rerun_is_still_possible_after_an_exception() -> None:
    """The exception path must clear `_in_flight`, not merely leave the
    gate permanently refusing - a flow-check retry after an infrastructure
    hiccup must be able to proceed."""
    backend = _FakeBackend(results={("lint",): _exited(0)})
    calls = {"n": 0}
    real_exec = backend.exec_in_attempt

    def flaky(handle: object, argv: Sequence[str], limits: Limits, cancel: object = None, stdin: object = None) -> ExecuteResult:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated backend crash")
        return real_exec(handle, argv, limits, cancel, stdin)

    backend.exec_in_attempt = flaky  # type: ignore[method-assign]
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    with pytest.raises(RuntimeError):
        witness.decide({"op": "run_gate", "gate": "lint"})
    reply = witness.decide({"op": "run_gate", "gate": "lint"})
    assert reply["exit_code"] == 0
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "complete"
    assert len(gate.runs) == 2


def test_a_tree_digest_failure_clears_in_flight_and_records_nothing() -> None:
    """Codex `code_review` correction: the first draft computed the tree
    digest INSIDE the same lock that claims `_in_flight`, with no cleanup
    on failure - a digest that raises once would wedge the gate as
    perpetually "already executing" forever, refusing every later request
    including a legitimate retry."""
    calls = {"n": 0}

    def flaky_digest() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated export failure")
        return "sha256:ok"

    backend = _FakeBackend(results={("lint",): _exited(0)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=flaky_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    with pytest.raises(RuntimeError, match="simulated export failure"):
        witness.decide({"op": "run_gate", "gate": "lint"})
    assert backend.calls == []  # never reached the backend at all
    reply = witness.decide({"op": "run_gate", "gate": "lint"})  # must not be refused as "already executing"
    assert reply["exit_code"] == 0
    gate = witness.finalize("a-1").gates["lint"]
    assert len(gate.runs) == 1  # the failed digest attempt recorded nothing
    assert gate.coverage == "complete"


# -------------------------------------------------------- coverage/UNKNOWN/NOT_CONFIRMED


def test_a_fully_bypassed_declared_gate_is_unknown_by_default() -> None:
    """Red case 5: the full bypass, with the SAFE default
    (`gate_exclusivity=False`) - `UNKNOWN`, never `NOT_CONFIRMED`."""
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=_FakeBackend(),
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "not-observed"
    status, reason = gate.execution_observed()
    assert (status, reason) == ("UNKNOWN", "no-controller-witness")


def test_a_fully_bypassed_declared_gate_is_not_confirmed_under_asserted_exclusivity() -> None:
    """Orchestrator correction: `NOT_CONFIRMED` is reachable ONLY when the
    caller has asserted `gate_exclusivity=True` - the fixture's own claim
    that the subject has no other way to run this gate at all."""
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=_FakeBackend(),
        handle=None, limits=_limits(), gate_exclusivity=True,
        exclusivity_basis="fixture installs no lint binary on the subject's PATH",
    )
    gate = witness.finalize("a-1").gates["lint"]
    assert gate.coverage == "not-observed"
    status, reason = gate.execution_observed()
    assert (status, reason) == ("NOT_CONFIRMED", "proven-non-execution")


def test_exclusivity_is_recorded_on_every_gate_regardless_of_value() -> None:
    """A `NOT_CONFIRMED` verdict - or its absence - must be legible without
    trusting an invisible constructor argument (orchestrator review)."""
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=_FakeBackend(),
        handle=None, limits=_limits(), gate_exclusivity=True, exclusivity_basis="stated basis",
    )
    parsed = json.loads(witness.finalize("a-1").to_json_bytes())
    assert parsed["gates"]["lint"]["exclusivity"] == {"asserted": True, "basis": "stated basis"}


def test_an_unsupported_backend_makes_the_whole_attempt_channel_unavailable() -> None:
    """Red case 10: `ManagedBackend.exec_in_attempt()` (or any backend not
    implementing it) always answers `reason="unsupported"` - the witness
    must read this as the WHOLE mechanism being unavailable for this
    attempt, not merely the one call that triggered it."""
    backend = _FakeBackend(results={
        ("lint",): ExecuteResult(reason="unsupported", exit_code=None),
    })
    witness = GateWitness(
        declared_gates={"lint": ["lint"], "typecheck": ["typecheck"]},
        tree_digest_fn=_fixed_tree_digest, backend=backend, handle=None,
        limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    witness.decide({"op": "run_gate", "gate": "lint"})
    record = witness.finalize("a-1")
    # Both gates read channel-unavailable, not only "lint" - including
    # "typecheck", which never even made a request.
    assert record.gates["lint"].coverage == "channel-unavailable"
    assert record.gates["typecheck"].coverage == "channel-unavailable"
    for gate in record.gates.values():
        assert gate.execution_observed() == ("UNKNOWN", "channel-unavailable")


def test_an_unsupported_backend_is_never_called_again(tmp_path: Path) -> None:
    """Codex `code_review` correction: once `exec_in_attempt()` has
    answered `unsupported`, a LATER `run_gate` for a different gate must
    not call the backend again at all - it already told us, once, that it
    cannot do this."""
    backend = _FakeBackend(results={
        ("lint",): ExecuteResult(reason="unsupported", exit_code=None),
        ("typecheck",): _exited(0),  # would succeed if ever actually called
    })
    witness = GateWitness(
        declared_gates={"lint": ["lint"], "typecheck": ["typecheck"]},
        tree_digest_fn=_fixed_tree_digest, backend=backend, handle=None,
        limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    witness.decide({"op": "run_gate", "gate": "lint"})
    assert backend.calls == [("lint",)]
    reply = witness.decide({"op": "run_gate", "gate": "typecheck"})
    assert reply["reason"] == "unsupported"
    assert backend.calls == [("lint",)]  # typecheck's own argv never called


def test_channel_unavailable_covers_every_declared_gate_distinctly_from_not_observed() -> None:
    witness = GateWitness(
        declared_gates={"lint": ["lint"], "typecheck": ["typecheck"]},
        tree_digest_fn=_fixed_tree_digest, backend=_FakeBackend(), handle=None,
        limits=_limits(), gate_exclusivity=True, exclusivity_basis="irrelevant here",
    )
    witness.channel_unavailable = True
    record = witness.finalize("a-1")
    for gate in record.gates.values():
        assert gate.coverage == "channel-unavailable"
        assert gate.execution_observed() == ("UNKNOWN", "channel-unavailable")


def test_execution_observed_never_returns_not_confirmed_for_complete_or_interrupted() -> None:
    for coverage in ("complete", "interrupted"):
        record = GateRecord(coverage=coverage, runs=(), exclusivity_asserted=True, exclusivity_basis="x")
        status, _ = record.execution_observed()
        assert status == "CONFIRMED"


# ---------------------------------------------------------------- the reply


def test_the_reply_carries_the_real_result_and_nothing_else() -> None:
    """The gate's own exit code and bounded output ARE what the subject
    would see running the gate itself (orchestrator correction) - but
    nothing about the witness's internal state (coverage, tree digest,
    other gates) leaks through the same reply."""
    backend = _FakeBackend(results={("lint",): _exited(3)}, stdout={("lint",): "some lint output"})
    witness = GateWitness(
        declared_gates={"lint": ["lint"], "typecheck": ["typecheck"]},
        tree_digest_fn=_fixed_tree_digest, backend=backend, handle=None,
        limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    reply = witness.decide({"op": "run_gate", "gate": "lint"})
    assert reply == {
        "accepted": True, "exit_code": 3, "reason": "exited",
        "stdout": "some lint output", "stderr": "",
    }


def test_the_reply_stdout_is_truncated_to_the_declared_byte_cap() -> None:
    backend = _FakeBackend(results={("lint",): _exited(0)}, stdout={("lint",): "x" * 100})
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
        reply_byte_cap=10,
    )
    reply = witness.decide({"op": "run_gate", "gate": "lint"})
    assert reply["stdout"] == "x" * 10


def test_the_reply_stderr_comes_from_the_backends_error_field() -> None:
    backend = _FakeBackend(results={("lint",): ExecuteResult(reason="exited", exit_code=1, error="boom")})
    witness = GateWitness(
        declared_gates={"lint": ["lint"]}, tree_digest_fn=_fixed_tree_digest, backend=backend,
        handle=None, limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    reply = witness.decide({"op": "run_gate", "gate": "lint"})
    assert reply["stderr"] == "boom"


# --------------------------------------------------------------- JSON shape


def test_gate_witness_record_round_trips_as_json_with_every_declared_gate_present() -> None:
    backend = _FakeBackend(results={("lint",): _exited(0)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"], "typecheck": ["typecheck"]},
        tree_digest_fn=_fixed_tree_digest, backend=backend, handle=None,
        limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    witness.decide({"op": "run_gate", "gate": "lint"})
    parsed = json.loads(witness.finalize("a-1").to_json_bytes())
    assert parsed["kind"] == "gate-witness"
    assert parsed["attempt_id"] == "a-1"
    assert set(parsed["declared_gates"]) == {"lint", "typecheck"}
    assert set(parsed["gates"].keys()) == {"lint", "typecheck"}  # absence is not a record
    assert parsed["gates"]["lint"]["coverage"] == "complete"
    assert len(parsed["gates"]["lint"]["runs"]) == 1
    assert parsed["gates"]["typecheck"]["coverage"] == "not-observed"
    assert parsed["gates"]["typecheck"]["runs"] == []


def test_gate_witness_record_is_a_frozen_value() -> None:
    record = GateWitnessRecord(attempt_id="a-1", declared_gates=("lint",), gates={})
    with pytest.raises(AttributeError):
        record.attempt_id = "a-2"  # type: ignore[misc]


# ------------------------------------------------------- real channel + fake backend


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


def _ok_result(reply: dict[str, object]) -> dict[str, object]:
    result = reply["result"]
    assert isinstance(result, dict)
    return result


def test_gate_witness_composes_with_a_real_decide_reply_channel(tmp_path: Path) -> None:
    """Proves the modules actually wire together, not just that each passes
    its own tests in isolation - a real socket, real connections, real
    `DecideReplyChannel.decide` dispatch into `GateWitness.decide`."""
    backend = _FakeBackend(results={("lint",): _exited(0)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"], "typecheck": ["typecheck"]},
        tree_digest_fn=_fixed_tree_digest, backend=backend, handle=None,
        limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, witness.decide)
    channel.start()
    try:
        reply = _send(sock_path, {"op": "run_gate", "gate": "lint"})
        assert reply["ok"] is True
        assert _ok_result(reply)["exit_code"] == 0
        bad_reply = _send(sock_path, {"op": "run_gate", "gate": "undeclared"})
        assert bad_reply["ok"] is False
    finally:
        channel.stop_and_finalize()
    record = witness.finalize("a-1")
    assert record.gates["lint"].coverage == "complete"
    assert record.gates["typecheck"].coverage == "not-observed"


def test_concurrent_run_gate_for_different_gates_do_not_corrupt_each_others_state(tmp_path: Path) -> None:
    backend = _FakeBackend(results={("lint",): _exited(0), ("typecheck",): _exited(1)})
    witness = GateWitness(
        declared_gates={"lint": ["lint"], "typecheck": ["typecheck"]},
        tree_digest_fn=_fixed_tree_digest, backend=backend, handle=None,
        limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, witness.decide)
    channel.start()
    try:
        threads = [
            threading.Thread(target=_send, args=(sock_path, {"op": "run_gate", "gate": "lint"})),
            threading.Thread(target=_send, args=(sock_path, {"op": "run_gate", "gate": "typecheck"})),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
    finally:
        channel.stop_and_finalize()
    record = witness.finalize("a-1")
    assert record.gates["lint"].coverage == "complete"
    assert record.gates["lint"].runs[0].exit_code == 0
    assert record.gates["typecheck"].coverage == "complete"
    assert record.gates["typecheck"].runs[0].exit_code == 1


# ---------------------------------------------- real DockerBackend (fake CLI)


def _docker_bin(state_dir: Path) -> list[str]:
    return [sys.executable, str(FAKE_DOCKER), "--state", str(state_dir)]


def test_real_gates_run_with_real_exit_codes_while_the_primary_subject_keeps_running(
    tmp_path: Path,
) -> None:
    """#269's own acceptance bar ("Show real deterministic processes
    succeeding, failing and being interrupted through the protected path.
    No live model is required.") PLUS the orchestrator's correction: a gate
    exec must never touch the attempt's own primary process. Drives TWO
    gates and a RERUN through a REAL `DockerBackend` (fake CLI) while a
    REAL, separately-running primary subject process is still inside the
    SAME container via `execute()` - proving `exec_in_attempt()` never
    stops it, which was exactly the bug this design found. `python3` (bare,
    not `sys.executable`) avoids the pre-existing `/work/` substring
    collision in `fake_docker.py`'s simulated-container path remapping
    (nit-stored during #183's own work)."""
    base = tmp_path / "work"
    base.mkdir()
    backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(tmp_path / "docker-state"))
    handle = backend.prepare("a-gw-0000000000001")
    backend.install(handle, {})
    try:
        lint_argv = [
            "python3", "-c",
            "import pathlib, sys; sys.exit(0 if pathlib.Path('/work/fixed').exists() else 1)",
        ]
        witness = GateWitness(
            declared_gates={
                "lint": lint_argv,
                "typecheck": ["python3", "-c", "raise SystemExit(0)"],
            },
            tree_digest_fn=_fixed_tree_digest, backend=backend, handle=handle,
            limits=Limits(timeout=5.0, grace=0.5), gate_exclusivity=False, exclusivity_basis="",
        )
        sock_path = tmp_path / "trigger.sock"
        channel = DecideReplyChannel(sock_path, witness.decide)
        channel.start()

        primary_result: list[ExecuteResult] = []

        def run_primary() -> None:
            primary_result.append(
                backend.execute(handle, ["python3", "-c", "import time; time.sleep(1.5)"], Limits(timeout=10.0))
            )

        primary_thread = threading.Thread(target=run_primary)
        primary_thread.start()
        time.sleep(0.3)  # let the primary genuinely start before gates run against it
        try:
            lint_reply = _send(sock_path, {"op": "run_gate", "gate": "lint"})
            assert _ok_result(lint_reply)["exit_code"] == 1

            typecheck_reply = _send(sock_path, {"op": "run_gate", "gate": "typecheck"})
            assert _ok_result(typecheck_reply)["exit_code"] == 0

            # Subject "fixes" lint (creates the marker file lint_argv checks
            # for) via its OWN exec_in_attempt call - the SAME mechanism, a
            # separate in-place exec against the still-running container -
            # then reruns the gate: a sequential rerun, not refused.
            fix = backend.exec_in_attempt(
                handle, ["python3", "-c", "open('/work/fixed', 'w').close()"], Limits(timeout=5.0),
            )
            assert fix.reason == "exited" and fix.exit_code == 0
            relint_reply = _send(sock_path, {"op": "run_gate", "gate": "lint"})
            assert _ok_result(relint_reply)["exit_code"] == 0
        finally:
            channel.stop_and_finalize()
        primary_thread.join(timeout=10.0)

        # The primary ran its own full 1.5s and exited cleanly - proof that
        # no gate exec stopped or killed the container out from under it.
        assert len(primary_result) == 1
        assert primary_result[0].reason == "exited"
        assert primary_result[0].exit_code == 0

        record = witness.finalize("a-1")
        assert record.gates["typecheck"].coverage == "complete"
        assert record.gates["typecheck"].runs[0].exit_code == 0
        assert len(record.gates["lint"].runs) == 2
        assert record.gates["lint"].runs[0].exit_code == 1
        assert record.gates["lint"].runs[1].exit_code == 0
        assert record.gates["lint"].coverage == "complete"
        for gate in ("lint", "typecheck"):
            assert record.gates[gate].execution_observed() == ("CONFIRMED", None)
    finally:
        backend.destroy(handle)


def test_exec_in_attempt_is_refused_once_the_primary_has_already_stopped(tmp_path: Path) -> None:
    """Red case: `attempt-not-running`, never a guessed `exited` result.
    `execute()`'s own one-shot contract stops the container when the
    PRIMARY subject run finishes - a `run_gate` after that must see this
    refusal, not the misleading "container not running" error path folded
    into an ordinary exit code that `execute()` itself exhibits (skillc
    #304, not fixed here)."""
    base = tmp_path / "work"
    base.mkdir()
    backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(tmp_path / "docker-state"))
    handle = backend.prepare("a-gw-0000000000002")
    backend.install(handle, {})
    try:
        backend.execute(handle, ["python3", "-c", "raise SystemExit(0)"], Limits(timeout=5.0))
        # The container is now stopped (execute()'s own contract).
        result = backend.exec_in_attempt(handle, ["python3", "-c", "raise SystemExit(0)"], Limits(timeout=5.0))
        assert result.reason == "attempt-not-running"
        assert result.exit_code is None
    finally:
        backend.destroy(handle)


def test_confirmed_kill_needs_no_standalone_kill_binary_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CI's gate step runs `python:3.12-slim`, a minimal image not
    guaranteed to carry the `procps` package `kill` usually comes from.
    `_confirm_and_kill_in_container` goes through `sh -c 'kill ...'`
    specifically because `kill` is a POSIX shell builtin (dash, bash) -
    demonstrated here by stripping PATH down to `sh`/`cat`/`python3` (no
    standalone `kill` at all) BEFORE `prepare()`, since `handle.env`'s PATH
    is captured once, at prepare time, and reused by every later call on
    that handle."""
    minimal_bin = tmp_path / "minimal-bin"
    minimal_bin.mkdir()
    for name in ("sh", "cat", "python3", "tar"):
        real = shutil.which(name)
        assert real is not None, f"this test's own host is missing {name!r}"
        (minimal_bin / name).symlink_to(real)
    assert shutil.which("kill", path=str(minimal_bin)) is None

    base = tmp_path / "work"
    base.mkdir()
    monkeypatch.setenv("PATH", str(minimal_bin))
    backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(tmp_path / "docker-state"))
    handle = backend.prepare("a-gw-0000000000005")
    backend.install(handle, {})
    try:
        result = backend.exec_in_attempt(
            handle, ["python3", "-c", "import time; time.sleep(30)"], Limits(timeout=0.5, grace=0.3),
        )
        assert result.reason == "timeout"
        assert result.stop_confirmed is True
    finally:
        backend.destroy(handle)


def test_exec_in_attempt_never_stops_the_container_on_its_own_timeout(tmp_path: Path) -> None:
    """A gate that times out is `exec_in_attempt()`'s own `reason=
    "timeout"` - and the container must still be running afterward, since
    this method must never stop it even on its own internal timeout."""
    base = tmp_path / "work"
    base.mkdir()
    backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(tmp_path / "docker-state"))
    handle = backend.prepare("a-gw-0000000000003")
    backend.install(handle, {})
    try:
        result = backend.exec_in_attempt(
            handle, ["python3", "-c", "import time; time.sleep(30)"], Limits(timeout=0.5, grace=0.3),
        )
        assert result.reason == "timeout"
        assert result.stop_confirmed is True  # orchestrator ruling on finding 3
        assert backend.confirm_stopped(handle) == Confirmation.NOT_CONFIRMED  # the ATTEMPT's own container, still running
    finally:
        backend.destroy(handle)


def test_confirm_and_kill_in_container_returns_false_when_the_kill_exec_cannot_be_reached(
    tmp_path: Path,
) -> None:
    """Orchestrator ruling on finding 3, the unconfirmed path: 'make the
    kill exec fail'. A broken `docker_bin` for JUST the kill/confirm calls
    (sharing the real container a working backend already launched) proves
    `_confirm_and_kill_in_container` returns `False` rather than guessing
    `True` when it cannot reach the daemon at all."""
    base = tmp_path / "work"
    base.mkdir()
    backend = d.DockerBackend(image="fake-image:1", base_dir=base, docker_bin=_docker_bin(tmp_path / "docker-state"))
    handle = backend.prepare("a-gw-0000000000004")
    backend.install(handle, {})
    try:
        broken = dataclasses.replace(backend, docker_bin=[sys.executable, "/nonexistent/fake_docker.py"])
        assert isinstance(handle, d._Handle)
        confirmed = broken._confirm_and_kill_in_container(handle, pid=999999, grace=0.1)
        assert confirmed is False
    finally:
        backend.destroy(handle)


def test_a_rerun_after_an_unconfirmed_stop_is_refused_workspace_integrity_unknown() -> None:
    """Orchestrator ruling on finding 3: once a run cannot be confirmed
    stopped, EVERY later `run_gate` is refused - even for a DIFFERENT
    gate - because a possibly-still-running zombie could be mutating the
    tree any later gate would measure. A gate that already completed
    keeps its own record unchanged (not erased, not downgraded)."""
    backend = _FakeBackend(results={
        ("lint",): _exited(0),
        ("typecheck",): ExecuteResult(reason="timeout", exit_code=None, stop_confirmed=False),
    })
    witness = GateWitness(
        declared_gates={"lint": ["lint"], "typecheck": ["typecheck"]},
        tree_digest_fn=_fixed_tree_digest, backend=backend, handle=None,
        limits=_limits(), gate_exclusivity=False, exclusivity_basis="",
    )
    witness.decide({"op": "run_gate", "gate": "lint"})
    reply = witness.decide({"op": "run_gate", "gate": "typecheck"})
    assert reply["reason"] == "timeout"
    with pytest.raises(ChannelRefusal, match="workspace-integrity-unknown"):
        witness.decide({"op": "run_gate", "gate": "lint"})  # a RERUN, not even typecheck again
    record = witness.finalize("a-1")
    # lint's own completed run from BEFORE the unconfirmed stop is untouched.
    assert record.gates["lint"].coverage == "complete"
    assert len(record.gates["lint"].runs) == 1
    assert record.gates["lint"].runs[0].exit_code == 0
    assert record.gates["typecheck"].coverage == "interrupted"
    assert record.gates["typecheck"].runs[0].stop_confirmed is False
