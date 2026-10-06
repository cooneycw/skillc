"""A controller-owned gate-execution witness (#269).

See `docs/specs/evaluation-facility/gate-witness.md` for the full design.
Builds on `skillc/decide_reply_channel.py` (#183) UNCHANGED: this module
supplies only a `decide` function and a request/response vocabulary of its
own (`gate_start`/`gate_complete`) - no change to the channel, the
`DockerBackend` mount, or `compose_run_argv` is needed or made here.

ONE RECORD PER ATTEMPT, COVERING THE DECLARED GATE SET (design doc §2) -
never one per gate, because a per-gate record cannot express a declared gate
nothing was ever heard about: absence of a record is not a record. The
declared gate set is supplied by the CALLER constructing this witness (the
controller's own plan), never read from anything the subject sends.

THE CONTROLLER COMPUTES THE TREE IDENTITY, NEVER THE SUBJECT (design doc
§6). `tree_digest_fn` is called by this module at `gate_start` time; there
is no `tree_digest` field anywhere in the request vocabulary, deliberately -
a subject-claimed one would either refuse every honest edit-then-test cycle
or prove nothing at all, and this module does neither.

EXIT CODE IS NOT EXECUTION (design doc §5, review correction): a paired
start and complete is `execution_observed: CONFIRMED` whatever the exit
code reports: that separation is `records.md`'s own "Three facts that are
not compliance" item 2, applied here. `NOT_CONFIRMED` is never produced by
this witness at all - a declared gate with zero requests is consistent with
"skipped" and with "ran outside the channel," and this module cannot tell
those apart from silence, so it never asserts positive non-execution.

Stdlib only (`threading`, `time`), per AGENTS.md.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import Lock

from .decide_reply_channel import ChannelRefusal

#: Computes the CURRENT tree's content identity, called by this module at
#: `gate_start` time - never supplied by the subject. In production this is
#: backed by a real `ExecutionBackend.export()` call plus a deterministic
#: whole-tree hash; this module is tested against a fake one (design doc
#: §6's "owed, not shipped here" - the real export()-backed version is a
#: live-Docker question this module does not simulate).
TreeDigestFn = Callable[[], str]


@dataclass
class _GateState:
    """Mutable per-gate bookkeeping, held under `GateWitness._lock`. Not
    part of this module's public surface - `GateWitness.finalize()` is the
    one way a caller sees anything derived from this."""

    invocation_id: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    exit_code: int | None = None
    tree_digest_at_start: str | None = None

    @property
    def started(self) -> bool:
        return self.started_at is not None

    @property
    def closed(self) -> bool:
        """A completed invocation - closed to any further gate_complete,
        whether a legitimate second completion or a replay of the first."""
        return self.completed_at is not None


@dataclass(frozen=True)
class GateRecord:
    """One declared gate's entry in the finalized witness (design doc §2,
    §5). `coverage` is one of `complete` / `interrupted` / `not-observed` /
    `channel-unavailable` - named so none of them collide with #183's own
    `TrustedLog` vocabulary (review correction: an earlier draft used
    "unavailable" for two different facts here)."""

    coverage: str
    started_at: float | None = None
    completed_at: float | None = None
    exit_code: int | None = None
    tree_digest_at_start: str | None = None

    def execution_observed(self) -> tuple[str, str | None]:
        """`(CONFIRMED|UNKNOWN, reason)` - design doc §5's derivation.
        `NOT_CONFIRMED` is never returned; see the module docstring."""
        if self.coverage in ("complete", "interrupted"):
            return "CONFIRMED", None
        if self.coverage == "not-observed":
            return "UNKNOWN", "no-controller-witness"
        return "UNKNOWN", "channel-unavailable"

    def to_json(self) -> dict[str, object]:
        return {
            "coverage": self.coverage,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "exit_code": self.exit_code,
            "tree_digest_at_start": self.tree_digest_at_start,
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
            "version": 1,
            "attempt_id": self.attempt_id,
            "declared_gates": list(self.declared_gates),
            "gates": {gate: record.to_json() for gate, record in self.gates.items()},
        }).encode("utf-8")


class GateWitness:
    """Owns the per-attempt gate state and supplies `decide` to a
    `DecideReplyChannel` (#183) constructed against this attempt's socket.
    Usage:

        witness = GateWitness(declared_gates=("lint", "typecheck"), tree_digest_fn=real_fn)
        channel = DecideReplyChannel(socket_path, witness.decide)
        channel.start()
        ... run the attempt ...
        channel.stop_and_finalize()
        record = witness.finalize("a-attempt-id")

    `finalize()` does not depend on the channel's own log at all - this
    class tracks state itself as `decide` is called, which is simpler and
    matches `DisruptionTrigger`'s own separation (the channel owns
    transport and its own request log; a caller owns deriving a
    domain-specific record from the decisions it made)."""

    def __init__(self, declared_gates: Sequence[str], tree_digest_fn: TreeDigestFn) -> None:
        if not declared_gates:
            raise ValueError(
                "declared_gates must be non-empty - a witness declaring nothing cannot "
                "distinguish a bypassed attempt from one that was never asked to run anything"
            )
        self._declared = tuple(declared_gates)
        self._tree_digest_fn = tree_digest_fn
        self._lock = Lock()
        self._gates: dict[str, _GateState] = {gate: _GateState() for gate in self._declared}
        #: invocation_id -> gate it was reserved for, for the LIFE of the
        #: attempt (never released on completion). Red case 2 above only
        #: refused a second start for the SAME gate; a subject reusing one
        #: id across two different gates (deliberately, or by OS pid reuse,
        #: since a subject-generated id is commonly a pid) would otherwise
        #: have its `gate_complete` matched to whichever gate started FIRST
        #: with that id (`_decide_complete`'s linear scan), crediting the
        #: wrong gate with the other's result (codex code_review of #269).
        self._invocation_ids: dict[str, str] = {}
        #: Set by a caller whose channel never became reachable at all for
        #: this attempt (design doc §5's `channel-unavailable`, distinct
        #: from `not-observed` - nothing could have been witnessed, not
        #: merely nothing was heard).
        self.channel_unavailable = False

    def decide(self, request: Mapping[str, object]) -> Mapping[str, object]:
        op = request.get("op")
        if op == "gate_start":
            return self._decide_start(request)
        if op == "gate_complete":
            return self._decide_complete(request)
        raise ChannelRefusal(f"gate-witness: unknown op {op!r}")

    def _decide_start(self, request: Mapping[str, object]) -> Mapping[str, object]:
        gate = request.get("gate")
        invocation_id = request.get("invocation_id")
        if not isinstance(gate, str) or gate not in self._gates:
            # Design doc §8 red case 1: the controller's own declared set is
            # the only source of truth for what may be started at all.
            raise ChannelRefusal(f"gate_start: {gate!r} is not a declared gate for this attempt")
        if not isinstance(invocation_id, str) or not invocation_id:
            raise ChannelRefusal("gate_start: invocation_id must be a non-empty string")
        # Held for the whole operation, including the tree-digest call -
        # simpler and obviously correct over optimizing for concurrent
        # gate_start calls across different gates, which a single flow-check
        # wrapper is not expected to issue anyway.
        with self._lock:
            state = self._gates[gate]
            if state.started:
                # Design doc §8 red case 2: one start per declared gate per
                # attempt - a subject that could re-start after an
                # unfavourable result could paper over the first attempt
                # with a second, more favourable one.
                raise ChannelRefusal(f"gate_start: {gate!r} already has a start recorded for this attempt")
            holder = self._invocation_ids.get(invocation_id)
            if holder is not None:
                # Red case 6 (codex code_review of #269): an id already
                # reserved by ANY gate - including one that has since
                # completed - must not be reused by another. Checked before
                # reservation so this gate's own state stays untouched on
                # refusal.
                raise ChannelRefusal(
                    f"gate_start: invocation_id {invocation_id!r} is already reserved by gate "
                    f"{holder!r} for this attempt"
                )
            self._invocation_ids[invocation_id] = gate
            state.invocation_id = invocation_id
            state.tree_digest_at_start = self._tree_digest_fn()
            state.started_at = time.time()
        return {"accepted": True}

    def _decide_complete(self, request: Mapping[str, object]) -> Mapping[str, object]:
        invocation_id = request.get("invocation_id")
        exit_code = request.get("exit_code")
        if not isinstance(invocation_id, str) or not invocation_id:
            raise ChannelRefusal("gate_complete: invocation_id must be a non-empty string")
        if not isinstance(exit_code, int):
            raise ChannelRefusal("gate_complete: exit_code must be an int")
        with self._lock:
            matched = next(
                (state for state in self._gates.values() if state.invocation_id == invocation_id), None,
            )
            # Design doc §8 red case 3: completion credit requires an OPEN
            # invocation the controller itself started - a bare completion
            # naming an unknown id, an id never started, or an id already
            # closed (a replay of its own earlier, genuine completion) all
            # fail this the same way: "a received request alone is not
            # completion" (#269's own acceptance wording).
            if matched is None or not matched.started or matched.closed:
                raise ChannelRefusal(
                    f"gate_complete: invocation_id {invocation_id!r} does not match a gate "
                    f"currently open for this attempt"
                )
            matched.exit_code = exit_code
            matched.completed_at = time.time()
        return {"accepted": True}

    def finalize(self, attempt_id: str) -> GateWitnessRecord:
        """Design doc §5's coverage derivation, over every declared gate -
        never only the ones that received a request. Safe to call only
        once the attempt's own `confirm_stopped()` has returned, matching
        `DisruptionTrigger`/`DecideReplyChannel`'s own discipline for
        reading a channel's state after the fact."""
        with self._lock:
            records: dict[str, GateRecord] = {}
            for gate, state in self._gates.items():
                if self.channel_unavailable:
                    records[gate] = GateRecord(coverage="channel-unavailable")
                elif not state.started:
                    records[gate] = GateRecord(coverage="not-observed")
                elif not state.closed:
                    # Design doc §8 red case 4: started, never completed -
                    # `interrupted`, never collapsed into `complete` or
                    # `not-observed`.
                    records[gate] = GateRecord(
                        coverage="interrupted", started_at=state.started_at,
                        tree_digest_at_start=state.tree_digest_at_start,
                    )
                else:
                    records[gate] = GateRecord(
                        coverage="complete", started_at=state.started_at,
                        completed_at=state.completed_at, exit_code=state.exit_code,
                        tree_digest_at_start=state.tree_digest_at_start,
                    )
            return GateWitnessRecord(attempt_id=attempt_id, declared_gates=self._declared, gates=records)
