"""A controller-owned gate-execution witness (#269).

See `docs/specs/evaluation-facility/gate-witness.md` for the full design.
Builds on `skillc/decide_reply_channel.py` (#183) UNCHANGED: this module
supplies only a `decide` function and a request/response vocabulary of its
own (`run_gate`) - no change to the channel, the `DockerBackend` mount, or
`compose_run_argv` is needed or made here.

THE CONTROLLER EXECUTES THE GATE (design correction, orchestrator review):
the subject never reports a gate's outcome - it only ASKS the controller to
run a declared gate, and the controller calls `ExecutionBackend.exec_in_attempt()`
itself and records the REAL result. A subject that runs nothing cannot
produce a well-formed "it ran" claim, because there is no claim left for the
subject to author: the only thing it can send is a request naming a
declared gate, never an outcome.

ONE RECORD PER ATTEMPT, COVERING THE DECLARED GATE SET (design doc §2) -
never one per gate, because a per-gate record cannot express a declared gate
nothing was ever heard about: absence of a record is not a record. The
declared gate set, and each gate's real argv, is supplied by the CALLER
constructing this witness (the controller's own plan), never read from
anything the subject sends.

EVERY RUN IS RECORDED, NOT JUST ONE (design correction, orchestrator
review): flow-check legitimately reruns a gate after fixing a failure, so
"one run per gate per attempt" would refuse a legitimate workflow. A
concurrent duplicate (the same gate, still executing) is refused; a
sequential rerun (the prior run already resolved) is accepted and appended -
nothing already recorded is ever overwritten, so "paper over a bad first
run" stays impossible even though reruns are allowed.

THE CONTROLLER COMPUTES THE TREE IDENTITY, NEVER THE SUBJECT (design doc
§6). `tree_digest_fn` is called by this module immediately before each
`exec_in_attempt()` call; there is no `tree_digest` field anywhere in the request
vocabulary, deliberately - a subject-claimed one would either refuse every
honest edit-then-test cycle or prove nothing at all, and this module does
neither.

EXIT CODE IS NOT EXECUTION (design doc §5): a run that reached its own
natural end (`reason == "exited"`) is `complete`; a run the controller
genuinely STARTED but that was cut off before reaching that end (a timeout,
an operator-cancellation, or a call that was still running when the channel
tore down) is `interrupted` - both still mean `execution_observed:
CONFIRMED`, because a real process genuinely began. What happened to it
afterward is the separate `coverage`/`exit_code`/`reason` facts, never
folded into `execution_observed` itself.

A run that NEVER STARTED A PROCESS AT ALL - `reason` of `"launch-failed"`
(the exec itself never launched), `"attempt-not-running"` (refused before
any attempt), or `"unsupported"` (the backend cannot do this at all) - is
NOT `interrupted` and does not contribute `CONFIRMED` (codex `code_review`
correction: an earlier draft folded these into `interrupted`, which let a
refused or never-launched exec report positive execution evidence - exactly
the subject-authored-claim problem #269 exists to stop, just moved from the
subject to a failed launch). These are recorded in `runs` for transparency,
but the gate's own coverage falls back to `not-observed` if that is all it
has - a record of "a request arrived" without a record of "a process
started" is honestly `not-observed`, never a confirmed execution.

`NOT_CONFIRMED` IS CONDITIONAL, NOT DEFAULT (design correction, orchestrator
review of the first draft, which ruled it out entirely). A declared gate
with zero `run_gate` requests is `NOT_CONFIRMED` (proven non-execution)
ONLY when the caller has asserted `gate_exclusivity=True` for this attempt -
meaning the fixture gives the subject no other way to invoke that gate's
command at all. This module cannot verify that assertion itself (whether a
cheap `command -v` check could is named as owed in the design doc, not
implemented here); it is recorded verbatim into every gate's record
(`exclusivity.asserted`, `exclusivity.basis`) so a later reader sees exactly
what a `NOT_CONFIRMED` verdict rests on, rather than trusting an invisible
constructor argument. Without that assertion, silence stays `UNKNOWN`
(`no-controller-witness`) - the original, safe default.

THE REPLY CARRIES THE REAL RESULT (design correction, orchestrator review):
hiding the gate's own exit code would break the workflow under test - a
flow-check loop that cannot see a gate's failure cannot fix it and rerun.
The subject gets back `exit_code`, `reason`, and stdout/stderr truncated to
a declared byte cap - exactly what it would see running the gate itself.
What it does NOT get: the witness's own coverage state, any other gate's
status, or any tree digest. The witness stays trustworthy regardless of
what the reply contains, because the RECORD is controller-written and never
derived from anything the subject sees or sends back.

Stdlib only (`threading`, `time`, `tempfile`), per AGENTS.md.
"""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from .backend import ExecuteResult, ExecutionBackend, Limits
from .decide_reply_channel import ChannelRefusal

#: Computes the CURRENT tree's content identity, called by this module
#: immediately before each `exec_in_attempt()` call - never supplied by the subject.
#: In production this is backed by a real `ExecutionBackend.export()` call
#: plus a deterministic whole-tree hash; this module is tested against a
#: fake one (design doc §6's "owed, not shipped here" - the real
#: export()-backed version is a live-Docker question this module does not
#: simulate).
TreeDigestFn = Callable[[], str]

#: Default cap on the stdout/stderr text returned to the subject in a
#: `run_gate` reply - a flow-check loop needs enough to act on a failure,
#: never an unbounded echo of whatever the gate printed.
DEFAULT_REPLY_BYTE_CAP = 4096

#: `reason` values meaning NO PROCESS EVER STARTED (codex `code_review`
#: correction) - distinct from `"timeout"`/`"operator-cancelled"`, which
#: mean a process genuinely began and was cut off. A run carrying one of
#: these contributes neither `complete` nor `interrupted` to its gate's
#: coverage.
_NOT_STARTED_REASONS = frozenset({"launch-failed", "attempt-not-running", "unsupported"})


@dataclass
class _Run:
    """One execution attempt of a declared gate - mutable, held under
    `GateWitness._lock` only at its start and its resolution, never across
    the `exec_in_attempt()` call itself (that call may be slow and must not block a
    DIFFERENT gate's own `run_gate`). `reason is None` after `finalize()` has
    run means the channel tore down before this run ever resolved - the
    `interrupted`-by-teardown case; while the channel is still up, the same
    field doubles as the gate's own `in_flight` flag."""

    requested_at: float
    tree_digest_at_start: str
    completed_at: float | None = None
    exit_code: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class GateRunRecord:
    """One run's entry in the finalized record (design doc §2). Frozen,
    immutable snapshot of a `_Run` taken at `finalize()` time."""

    requested_at: float
    completed_at: float | None
    exit_code: int | None
    reason: str | None
    tree_digest_at_start: str

    def to_json(self) -> dict[str, object]:
        return {
            "requested_at": self.requested_at,
            "completed_at": self.completed_at,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "tree_digest_at_start": self.tree_digest_at_start,
        }


@dataclass(frozen=True)
class GateRecord:
    """A declared gate's entry in the finalized witness (design doc §2, §5).
    `coverage` is one of `complete` / `interrupted` / `not-observed` /
    `channel-unavailable`. `exclusivity` is recorded on EVERY gate,
    regardless of its value, so a reader of `NOT_CONFIRMED` - or of its
    absence - sees exactly what that verdict rests on, never an invisible
    constructor argument (orchestrator review)."""

    coverage: str
    runs: tuple[GateRunRecord, ...]
    exclusivity_asserted: bool
    exclusivity_basis: str

    def execution_observed(self) -> tuple[str, str | None]:
        """`(CONFIRMED|UNKNOWN|NOT_CONFIRMED, reason)` - design doc §5's
        derivation. `NOT_CONFIRMED` is produced ONLY for `not-observed`
        coverage AND an asserted `gate_exclusivity` - never by default."""
        if self.coverage in ("complete", "interrupted"):
            return "CONFIRMED", None
        if self.coverage == "not-observed":
            if self.exclusivity_asserted:
                return "NOT_CONFIRMED", "proven-non-execution"
            return "UNKNOWN", "no-controller-witness"
        return "UNKNOWN", "channel-unavailable"

    def to_json(self) -> dict[str, object]:
        return {
            "coverage": self.coverage,
            "runs": [r.to_json() for r in self.runs],
            "exclusivity": {"asserted": self.exclusivity_asserted, "basis": self.exclusivity_basis},
        }


@dataclass(frozen=True)
class GateWitnessRecord:
    """The one-per-attempt record (design doc §2) - what gets captured as
    an `artifact-manifest.artifacts` entry (`type: "gate-witness"`) and
    cited by `skill-evidence.lifecycle.execution_observed.evidence` as
    `{ref, digest}` (`records.md`'s own, already-merged mechanism - see
    design doc §7; nothing here invents a second one)."""

    attempt_id: str
    declared_gates: tuple[str, ...]
    gates: Mapping[str, GateRecord]

    def to_json_bytes(self) -> bytes:
        return json.dumps({
            "kind": "gate-witness",
            "version": 2,
            "attempt_id": self.attempt_id,
            "declared_gates": list(self.declared_gates),
            "gates": {gate: record.to_json() for gate, record in self.gates.items()},
        }).encode("utf-8")


def _read_observations(backend: ExecutionBackend, handle: object, cap: int) -> str:
    """Best-effort read of the gate's own captured stdout (`verify.py`'s
    documented `observations` write-back convention, #76) - never raises:
    an export or read failure here must not take down the gate's own
    `run_gate` reply over a secondary capture concern."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            backend.export(handle, dest)
            observations = dest / "observations"
            if not observations.is_file():
                return ""
            return observations.read_text(encoding="utf-8", errors="replace")[:cap]
    except OSError:
        return ""


class GateWitness:
    """Owns the per-attempt gate state and supplies `decide` to a
    `DecideReplyChannel` (#183) constructed against this attempt's socket.
    The subject never executes a gate itself - it asks this witness to, and
    this witness calls `backend.exec_in_attempt()` (the SAME `ExecutionBackend` the
    attempt itself runs under, with the SAME `limits`) and records the real
    result.

    Usage:

        witness = GateWitness(
            declared_gates={"lint": ["lint-script"], "typecheck": ["typecheck-script"]},
            tree_digest_fn=real_fn, backend=backend, handle=handle, limits=limits,
            gate_exclusivity=True, exclusivity_basis="fixture installs no lint-script/typecheck-script on PATH",
        )
        channel = DecideReplyChannel(socket_path, witness.decide)
        channel.start()
        ... run the attempt ...
        channel.stop_and_finalize()
        record = witness.finalize("a-attempt-id")
    """

    def __init__(
        self,
        declared_gates: Mapping[str, Sequence[str]],
        tree_digest_fn: TreeDigestFn,
        backend: ExecutionBackend,
        handle: object,
        limits: Limits,
        *,
        gate_exclusivity: bool,
        exclusivity_basis: str,
        reply_byte_cap: int = DEFAULT_REPLY_BYTE_CAP,
    ) -> None:
        if not declared_gates:
            raise ValueError(
                "declared_gates must be non-empty - a witness declaring nothing cannot "
                "distinguish a bypassed attempt from one that was never asked to run anything"
            )
        for gate, argv in declared_gates.items():
            if not argv:
                raise ValueError(f"declared_gates[{gate!r}] must be a non-empty argv")
        self._declared_argv: dict[str, tuple[str, ...]] = {
            gate: tuple(argv) for gate, argv in declared_gates.items()
        }
        self._tree_digest_fn = tree_digest_fn
        self._backend = backend
        self._handle = handle
        self._limits = limits
        self._gate_exclusivity = gate_exclusivity
        self._exclusivity_basis = exclusivity_basis
        self._reply_byte_cap = reply_byte_cap
        self._lock = Lock()
        #: Serializes the ACTUAL exec + observations-read critical section
        #: across every gate (codex `code_review` correction) - `_lock`
        #: alone let two different gates' `exec_in_attempt()` calls run
        #: concurrently, both writing and reading the SAME shared
        #: `observations` artifact the backend's write-back convention
        #: uses, so one gate's reply could carry a neighbour's (or the
        #: primary subject's) stdout. Claim-checking (`_in_flight`) stays
        #: fast under `_lock`; only the slow exec itself is serialized here.
        self._exec_lock = Lock()
        self._runs: dict[str, list[_Run]] = {gate: [] for gate in self._declared_argv}
        self._in_flight: dict[str, bool] = {gate: False for gate in self._declared_argv}
        #: Set once `exec_in_attempt()` has answered `reason="unsupported"`
        #: for ANY gate - sticky for the rest of the attempt, so a later
        #: `run_gate` short-circuits instead of calling a backend already
        #: known incapable again (codex `code_review` correction).
        self._backend_unsupported = False
        #: Set by a caller whose channel never became reachable at all for
        #: this attempt (design doc §5's `channel-unavailable`, distinct
        #: from `not-observed` - nothing could have been witnessed, not
        #: merely nothing was heard).
        self.channel_unavailable = False

    def decide(self, request: Mapping[str, object]) -> Mapping[str, object]:
        op = request.get("op")
        if op == "run_gate":
            return self._decide_run_gate(request)
        raise ChannelRefusal(f"gate-witness: unknown op {op!r}")

    def _decide_run_gate(self, request: Mapping[str, object]) -> Mapping[str, object]:
        gate = request.get("gate")
        if not isinstance(gate, str) or gate not in self._declared_argv:
            # Red case 1: the controller's own declared set is the only
            # source of truth for what may be run at all.
            raise ChannelRefusal(f"run_gate: {gate!r} is not a declared gate for this attempt")
        with self._lock:
            if self._in_flight[gate]:
                # Red case 2: a CONCURRENT duplicate (the same gate, still
                # executing) is refused. A SEQUENTIAL rerun (the prior run
                # already resolved) is not refused here - flow-check
                # legitimately reruns a gate after fixing it.
                raise ChannelRefusal(f"run_gate: {gate!r} is already executing for this attempt")
            self._in_flight[gate] = True
        try:
            # The digest call is OUTSIDE the lock but still able to leave
            # `_in_flight` wedged true forever if it raises (codex
            # `code_review` correction: the first draft computed this
            # INSIDE the lock, with no cleanup on failure) - caught
            # explicitly so a digest failure clears the claim exactly like
            # an `exec_in_attempt()` failure does, rather than permanently
            # refusing every later request for this gate.
            tree_digest = self._tree_digest_fn()
        except Exception:
            with self._lock:
                self._in_flight[gate] = False
            raise
        with self._lock:
            run = _Run(requested_at=time.time(), tree_digest_at_start=tree_digest)
            self._runs[gate].append(run)
            backend_known_unsupported = self._backend_unsupported
        if backend_known_unsupported:
            # The backend already told us, for a PRIOR gate, that it cannot
            # do this at all (codex `code_review` correction: the first
            # draft kept calling a backend already known incapable). Still
            # record a run - for transparency - without calling the
            # backend or reading observations again.
            result = ExecuteResult(reason="unsupported", exit_code=None)
            stdout = ""
        else:
            # Serializes the ACTUAL exec + observations-read globally
            # (`_exec_lock`, not `_lock`) - claim-checking above stays
            # concurrent across different gates; only the slow exec and
            # its shared-artifact read are serialized, closing the
            # cross-gate/cross-primary `observations` race (codex
            # `code_review` correction).
            with self._exec_lock:
                try:
                    result = self._backend.exec_in_attempt(
                        self._handle, list(self._declared_argv[gate]), self._limits,
                    )
                except Exception:
                    # An exception out of `exec_in_attempt()` itself is an
                    # infrastructure fault the Protocol does not document as
                    # a normal outcome (`attempt-not-running` and
                    # `unsupported` already have their own `reason`,
                    # returned normally) - never silently recorded as a
                    # clean result. The run stays unresolved (`reason`
                    # stays `None`); `finalize()` tells this apart from a
                    # genuinely still-running call cut off by teardown via
                    # `_in_flight` (cleared here, left `True` by teardown).
                    with self._lock:
                        self._in_flight[gate] = False
                    raise
                if result.reason == "unsupported":
                    with self._lock:
                        self.channel_unavailable = True
                        self._backend_unsupported = True
                    stdout = ""
                else:
                    stdout = _read_observations(self._backend, self._handle, self._reply_byte_cap)
        with self._lock:
            run.completed_at = time.time()
            run.exit_code = result.exit_code
            run.reason = result.reason
            self._in_flight[gate] = False
        return {
            "accepted": True,
            "exit_code": result.exit_code,
            "reason": result.reason,
            "stdout": stdout,
            "stderr": (result.error or "")[: self._reply_byte_cap],
        }

    def finalize(self, attempt_id: str) -> GateWitnessRecord:
        """Design doc §5's coverage derivation, over every declared gate -
        never only the ones that received a request. Safe to call only
        once the attempt's own `confirm_stopped()` has returned, matching
        `DisruptionTrigger`/`DecideReplyChannel`'s own discipline for
        reading a channel's state after the fact.

        A run whose `reason is None` here is ambiguous on its own - it
        could be genuinely still running (cut off by teardown, a real
        process that STARTED) or it could be the aftermath of an exception
        that cleared `_in_flight` before ever reaching a real backend
        result (never started at all). `_in_flight[gate]` disambiguates:
        the exception path always clears it before re-raising, so if it is
        STILL `True` here, this run is the one genuinely abandoned mid-call
        - interrupted, not dropped. If it is `False`, every run for this
        gate already has a definite `reason` (codex `code_review`
        correction)."""
        with self._lock:
            records: dict[str, GateRecord] = {}
            for gate, runs in self._runs.items():
                run_records = tuple(
                    GateRunRecord(
                        requested_at=r.requested_at, completed_at=r.completed_at,
                        exit_code=r.exit_code, reason=r.reason,
                        tree_digest_at_start=r.tree_digest_at_start,
                    )
                    for r in runs
                )
                any_complete = False
                any_interrupted = False
                for index, record in enumerate(run_records):
                    is_last = index == len(run_records) - 1
                    genuinely_stuck = record.reason is None and is_last and self._in_flight[gate]
                    if record.reason == "exited":
                        any_complete = True
                    elif record.reason in ("timeout", "operator-cancelled") or genuinely_stuck:
                        any_interrupted = True
                    # else: reason in _NOT_STARTED_REASONS, or a resolved
                    # exception (reason is None, _in_flight already False) -
                    # no process ever started; contributes nothing.
                if self.channel_unavailable:
                    coverage = "channel-unavailable"
                elif any_complete:
                    coverage = "complete"
                elif any_interrupted:
                    coverage = "interrupted"
                else:
                    # Either no run arrived at all, or every run that did
                    # arrive never started a real process (codex
                    # `code_review` correction) - both read as
                    # `not-observed`: the witness has no positive execution
                    # evidence either way. The raw `runs` list still
                    # distinguishes the two for anyone reading it directly.
                    coverage = "not-observed"
                records[gate] = GateRecord(
                    coverage=coverage, runs=run_records,
                    exclusivity_asserted=self._gate_exclusivity,
                    exclusivity_basis=self._exclusivity_basis,
                )
            return GateWitnessRecord(attempt_id=attempt_id, declared_gates=tuple(self._declared_argv), gates=records)
