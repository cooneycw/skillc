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
The subject gets back `exit_code`, `reason`, and the gate's whole stdout and
stderr - exactly what it would see running the gate itself. By default each
stream is forwarded up to the capture bound the gate ran under
(`Limits.max_captured_stdout_bytes`/`max_captured_stderr_bytes`, #404), and a
capture that hit that bound is refused rather than forwarded, so a default
reply is never a silent prefix. It used to be cut at 4,096 bytes: the real
gate prints its `FLOW_FINISH_GATE:` verdict last, so any failing run past that
size reached the subject without its verdict line.
Stderr is the backend's raw `ExecuteResult.stderr` on every exit (#334): it
used to be `error`, which is filled only for a nonzero exit and is stripped,
so a passing gate's stderr never reached the subject and a failing gate's
lost its trailing newline. A backend that reports no raw stderr still
forwards `error`; that summary is not a byte-identity claim.
What it does NOT get: the witness's own coverage state, any other gate's
status, or any tree digest. The witness stays trustworthy regardless of
what the reply contains, because the RECORD is controller-written and never
derived from anything the subject sees or sends back.

PER-STAGE OUTCOMES ARE READ AT RUN TIME, BY THE CONTROLLER (#376). A gate
the caller names in `stage_capture` is an aggregate whose stages matter on
their own: the controller applies that gate's reader to the stdout IT
captured, the moment the run resolves, and stores the result on that run
(`GateRunRecord.stages`). It is bound to that run's exit code and tree
digest, and nothing later - a replay, a rerun, anything the subject sends -
can rewrite it. A run that did not exit normally, or whose output was
incomplete, records an `unavailable` capture, never an empty success. See
`skillc/stage_capture.py` for the reader and its states.

Stdlib only (`threading`, `time`, `json`), per AGENTS.md.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Any, Protocol

from . import gate_state
from .backend import ExecuteResult, ExecutionBackend, Limits
from .decide_reply_channel import ChannelRefusal
from .ordering import Order
from .stage_capture import unavailable as _stages_unavailable

#: Computes the CURRENT tree's content identity, called by this module
#: immediately before each `exec_in_attempt()` call - never supplied by the subject.
#: In production this is backed by a real `ExecutionBackend.export()` call
#: plus a deterministic whole-tree hash; this module is tested against a
#: fake one (design doc §6's "owed, not shipped here" - the real
#: export()-backed version is a live-Docker question this module does not
#: simulate).
TreeDigestFn = Callable[[], str]

#: Reads one resolved run's per-stage outcomes from the controller-captured
#: stdout and exit code (#376); `skillc.stage_capture.capture_stages` is the
#: production reader for the flow-check plan gate.
StageReader = Callable[[bytes | None, int | None], Mapping[str, object]]

#: `reason` values meaning NO PROCESS EVER STARTED (codex `code_review`
#: correction) - distinct from `"timeout"`/`"operator-cancelled"`, which
#: mean a process genuinely began and was cut off. A run carrying one of
#: these contributes neither `complete` nor `interrupted` to its gate's
#: coverage.
_NOT_STARTED_REASONS = frozenset({"launch-failed", "attempt-not-running", "unsupported"})


class StagedGate(Protocol):
    """#508: a gate the controller runs ONE DECLARED STAGE AT A TIME
    (`skillc.project_gate.StagedRunner`). `plan()` answers which stages a
    request asks for, or None when it is not a gate invocation; `run()`
    executes them and returns the combined result with its stage capture."""

    def plan(self, request: Mapping[str, object]) -> tuple[str, ...] | None: ...

    def run(self, backend: Any, handle: object, limits: Limits, stages: Sequence[str], *,
            cwd: str | None, env: Mapping[str, str] | None, confine_root: str | None,
            make_args: Sequence[str]) -> tuple[ExecuteResult, Mapping[str, object]]: ...


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
    #: Orchestrator ruling on finding 3 (codex `code_review`): `None` unless
    #: `reason` is `"timeout"`/`"operator-cancelled"`; then `True` only once
    #: the in-container process was independently confirmed dead, `False`
    #: otherwise - never a guess either way.
    stop_confirmed: bool | None = None
    #: #376: the per-stage capture for a gate named in `stage_capture`,
    #: read from this run's own controller-held stdout when it resolved;
    #: `None` for every other gate.
    stages: Mapping[str, object] | None = None
    #: #279 PR-2a: the attempt's ordering counter at this run's request and at
    #: its resolution, and the SOURCE digest of the gated repository at its
    #: start (`source_digest`). All None unless the witness was given an order.
    order_requested: int | None = None
    order_completed: int | None = None
    source_digest_at_start: str | None = None
    #: #525: the declared variant this run executed (which copy of the gate the
    #: subject invoked); None for the gate's own default argv.
    via: str | None = None
    output: Mapping[str, object] | None = None
    state_evidence: Mapping[str, object] | None = None


@dataclass(frozen=True)
class GateRunRecord:
    """One run's entry in the finalized record (design doc §2). Frozen,
    immutable snapshot of a `_Run` taken at `finalize()` time."""

    requested_at: float
    completed_at: float | None
    exit_code: int | None
    reason: str | None
    tree_digest_at_start: str
    stop_confirmed: bool | None
    #: #376: present only for a stage-bearing gate's runs - see `_Run.stages`.
    stages: Mapping[str, object] | None = None
    #: #279 PR-2a: present only for an ordered (multi-turn) attempt.
    order_requested: int | None = None
    order_completed: int | None = None
    source_digest_at_start: str | None = None
    #: #525: see `_Run.via`.
    via: str | None = None
    output: Mapping[str, object] | None = None
    state_evidence: Mapping[str, object] | None = None

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {
            "requested_at": self.requested_at,
            "completed_at": self.completed_at,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "tree_digest_at_start": self.tree_digest_at_start,
            "stop_confirmed": self.stop_confirmed,
            "output": dict(self.output) if self.output is not None else {
                stream: {"coverage": "missing", "reason": "no controller output was retained"}
                for stream in ("stdout", "stderr")},
        }
        if self.state_evidence is not None:
            data["state_evidence"] = dict(self.state_evidence)
        if self.stages is not None:
            data["stages"] = dict(self.stages)
        if self.order_requested is not None:
            # Only an ordered attempt's runs carry these, so every other
            # record is byte-identical (#279 PR-2a).
            data["order_requested"] = self.order_requested
            data["order_completed"] = self.order_completed
            data["source_digest_at_start"] = self.source_digest_at_start
        elif self.source_digest_at_start is not None:
            # #530: an unordered run whose fixture opted into the source digest;
            # every other unordered record is byte-identical.
            data["source_digest_at_start"] = self.source_digest_at_start
        if self.via is not None:
            # Only a run through a declared variant carries it (#525), so
            # every other record is byte-identical.
            data["via"] = self.via
        return data


@dataclass(frozen=True)
class GateRecord:
    """A declared gate's entry in the finalized witness (design doc §2, §5).
    `coverage` is one of `complete` / `interrupted` / `launch-failed` /
    `not-observed` / `channel-unavailable`. `launch-failed` (orchestrator
    correction) is distinct from `not-observed`: the subject DID request
    this gate at least once, but every one of its runs failed to start a
    real process - never conflated with a true bypass, because only a
    true bypass may ever become `NOT_CONFIRMED` under asserted
    `gate_exclusivity`. `exclusivity` is recorded on EVERY gate, regardless
    of its value, so a reader of `NOT_CONFIRMED` - or of its absence -
    sees exactly what that verdict rests on, never an invisible
    constructor argument (orchestrator review)."""

    coverage: str
    runs: tuple[GateRunRecord, ...]
    exclusivity_asserted: bool
    exclusivity_basis: str

    def execution_observed(self) -> tuple[str, str | None]:
        """`(CONFIRMED|UNKNOWN|NOT_CONFIRMED, reason)` - design doc §5's
        derivation. `NOT_CONFIRMED` is produced ONLY for `not-observed`
        coverage (a TRUE bypass - zero `run_gate` requests ever arrived)
        AND an asserted `gate_exclusivity` - never by default, and NEVER
        for `launch-failed` regardless of exclusivity (orchestrator
        correction: a subject that DID request the gate, where the
        CONTROLLER failed to launch it, must never read as "proven
        non-execution" - that would attribute the controller's own
        infrastructure failure to the subject as positive evidence it
        never ran its checks, the mirror image of the bug this witness
        exists to stop)."""
        if self.coverage in ("complete", "interrupted"):
            return "CONFIRMED", None
        if self.coverage == "launch-failed":
            return "UNKNOWN", "controller-launch-failed"
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
            "version": 3,
            "attempt_id": self.attempt_id,
            "declared_gates": list(self.declared_gates),
            "gates": {gate: record.to_json() for gate, record in self.gates.items()},
        }).encode("utf-8")


def _output_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_run_output(run: Mapping[str, object], stream: str, read_object: Callable[[str], bytes]) -> bytes | None:
    """Verify one retained stream. Historical/missing/refused is not empty.

    Partial bytes may be read for diagnosis; coverage is never promoted. A
    reference with absent/altered bytes, wrong size or invalid flags refuses.
    """
    if stream not in ("stdout", "stderr"):
        raise ValueError("unknown output stream")
    output = run.get("output")
    if output is None:
        return None
    if not isinstance(output, dict) or set(output) != {"stdout", "stderr"}:
        raise ValueError("invalid output schema")
    entry = output[stream]
    if not isinstance(entry, dict):
        raise TypeError("invalid output entry")
    coverage = entry.get("coverage")
    if coverage in ("missing", "refused"):
        if set(entry) != {"coverage", "reason"} or not isinstance(entry["reason"], str) or not entry["reason"]:
            raise ValueError("unretained output must give a reason and no bytes")
        return None
    if (coverage not in ("complete", "partial")
            or set(entry) != {"coverage", "digest", "size", "truncated", "incomplete"}
            or type(entry["size"]) is not int or entry["size"] < 0
            or type(entry["truncated"]) is not bool or type(entry["incomplete"]) is not bool
            or (coverage == "partial") != (entry["truncated"] or entry["incomplete"])
            or not isinstance(entry["digest"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", entry["digest"])):
        raise ValueError("invalid retained output reference")
    data = read_object(entry["digest"])
    if len(data) != entry["size"] or _output_digest(data) != entry["digest"]:
        raise ValueError("retained output bytes do not match the reference")
    return data


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
        channel = DecideReplyChannel(socket_path, witness.decide, "a-attempt-id")
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
        output_store: Callable[[bytes], str] | None = None,
        exclusivity_basis: str,
        #: None (the default, #404): each stream up to its capture bound in
        #: `limits`, which is never a truncation - a capped capture is refused.
        #: An explicit value below that bound DOES cut the reply silently; it
        #: exists for tests, not for a live attempt.
        reply_byte_cap: int | None = None,
        declared_env: Mapping[str, Mapping[str, str]] | None = None,
        workspace_root: str | None = None,
        stage_capture: Mapping[str, StageReader] | None = None,
        order: Order | None = None,
        source_digest_fn: Callable[[str | None], str] | None = None,
        staged: Mapping[str, StagedGate] | None = None,
        declared_variants: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
        resume_state: gate_state.Ledger | None = None,
        state_snapshot_fn: Callable[[str | None], gate_state.Snapshot] | None = None,
    ) -> None:
        #: #279 PR-2a: the attempt's ordering counter and the source-digest
        #: function (given the gate's working directory). Both None for every
        #: attempt without controller turns, whose record is then unchanged.
        if (resume_state is None) != (state_snapshot_fn is None):
            raise ValueError("resume state and state snapshot must be declared together")
        if resume_state is not None and set(dict(resume_state.protocol.operations)) != set(declared_gates):
            raise ValueError("resume protocol must name exactly the declared fixture gates")
        self._resume_state = resume_state
        self._state_snapshot_fn = state_snapshot_fn
        self._order = order
        self._source_digest_fn = source_digest_fn
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
        #: #525: per-gate VARIANTS - other copies of the same gate the subject
        #: may invoke (a skill-bundled gate beside the installed one). A request
        #: naming `via` runs that variant's argv, declared by the CALLER like the
        #: default; an undeclared `via` is refused. The run is recorded under the
        #: SAME gate name, with `via`, so a grader reading the gate is unchanged.
        self._declared_variants: dict[str, dict[str, tuple[str, ...]]] = {}
        for gate, variants in (declared_variants or {}).items():
            if gate not in self._declared_argv:
                raise ValueError(f"declared_variants names an undeclared gate: {gate!r}")
            for via, argv in variants.items():
                if not via or not argv:
                    raise ValueError(f"declared_variants[{gate!r}] needs a non-empty name and argv")
            self._declared_variants[gate] = {via: tuple(argv) for via, argv in variants.items()}
        #: #332: per-gate exec environment, declared by the CALLER exactly
        #: like `_declared_argv` - never read from the subject. A gate with
        #: no entry here runs under `exec_in_attempt()`'s own default
        #: (whatever the isolation already carries), unchanged from before
        #: this existed. Keys outside `declared_gates` are refused eagerly
        #: (a typo'd gate name here would otherwise sit dead forever).
        if declared_env:
            unknown_env_gates = set(declared_env) - set(self._declared_argv)
            if unknown_env_gates:
                raise ValueError(f"declared_env names undeclared gate(s): {sorted(unknown_env_gates)}")
        self._declared_env: dict[str, Mapping[str, str]] = dict(declared_env) if declared_env else {}
        #: #376: per-gate stage readers, declared by the CALLER like the argv.
        #: A typo'd gate name is refused eagerly, as for `declared_env`.
        if stage_capture:
            unknown_stage_gates = set(stage_capture) - set(self._declared_argv)
            if unknown_stage_gates:
                raise ValueError(f"stage_capture names undeclared gate(s): {sorted(unknown_stage_gates)}")
        self._stage_capture: dict[str, StageReader] = dict(stage_capture) if stage_capture else {}
        #: #508: gates the controller runs stage by stage (the project gate).
        #: A staged gate has no stdout reader: its stages are the exit codes
        #: the controller itself received, one exec per stage.
        if staged:
            unknown_staged = set(staged) - set(self._declared_argv)
            if unknown_staged:
                raise ValueError(f"staged names undeclared gate(s): {sorted(unknown_staged)}")
            if set(staged) & set(self._stage_capture):
                raise ValueError("a staged gate cannot also declare a stdout stage reader")
        self._staged: dict[str, StagedGate] = dict(staged) if staged else {}
        #: #332: the one root a subject-forwarded `cwd` must resolve inside
        #: (after a REAL in-container `realpath`, never a string-prefix
        #: check on the unresolved input - a symlink could point outside
        #: it). `None` means this attempt accepts no `cwd` at all: every
        #: `run_gate` naming one is refused, never silently ignored or
        #: passed through unconfined.
        self._workspace_root = workspace_root
        self._tree_digest_fn = tree_digest_fn
        self._backend = backend
        self._handle = handle
        self._limits = limits
        self._gate_exclusivity = gate_exclusivity
        self._exclusivity_basis = exclusivity_basis
        self._output_store = output_store
        self._output_limits = (limits.max_captured_stdout_bytes, limits.max_captured_stderr_bytes)
        self._stdout_reply_cap = limits.max_captured_stdout_bytes if reply_byte_cap is None else reply_byte_cap
        self._stderr_reply_cap = limits.max_captured_stderr_bytes if reply_byte_cap is None else reply_byte_cap
        self._lock = Lock()
        #: Snapshot and execution share one order across different gates.
        self._exec_lock = Lock()
        self._runs: dict[str, list[_Run]] = {gate: [] for gate in self._declared_argv}
        self._in_flight: dict[str, bool] = {gate: False for gate in self._declared_argv}
        #: Set once `exec_in_attempt()` has answered `reason="unsupported"`
        #: for ANY gate - sticky for the rest of the attempt, so a later
        #: `run_gate` short-circuits instead of calling a backend already
        #: known incapable again (codex `code_review` correction).
        self._backend_unsupported = False
        #: Set once a timeout/operator-cancellation could NOT be confirmed
        #: dead in-container (orchestrator ruling on finding 3) - sticky
        #: for the rest of the attempt. Unlike `channel_unavailable`, this
        #: does NOT retroactively change any gate's already-finalized
        #: coverage (a gate that already completed keeps its own record);
        #: it only REFUSES every later `run_gate`, because a possibly-still-
        #: running zombie could be mutating the tree any later gate would
        #: measure.
        self._workspace_integrity_unknown = False
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

    def _confine_requested_cwd(self, cwd: object) -> str | None:
        """#332, demoted by #338: no longer the security boundary for a
        subject-forwarded `cwd` - only a cheap, non-load-bearing EARLY
        rejection, so an obviously-wrong cwd fails fast with a clear
        message before any exec is even built. `None` (no cwd requested)
        passes through unchanged - `exec_in_attempt()` then runs at its own
        default. Anything else must resolve, via a REAL in-container
        `realpath` (never a string-prefix check on the unresolved input -
        a symlink could point outside the root), to this attempt's
        declared workspace root or somewhere below it. Any failure to
        resolve, any resolution outside that root, or a cwd requested when
        no root is configured at all, is refused here - never run, never
        silently confined by guessing. Orchestrator's own named red cases
        (`cwd=/`, `cwd=../..`) are exactly what the suffix/prefix check
        below rejects: either resolves to something that is not this
        root or a path strictly below it.

        THE REAL GUARANTEE IS NOT HERE. This check and `exec_in_attempt()`'s
        own call are two separate `docker exec`s with real wall-clock time
        between them (lock acquisition, `tree_digest_fn()`) - long enough
        for the subject, who owns the whole workspace tree, to swap an
        ancestor of the resolved path for a symlink pointing outside the
        root before the later exec ever runs. `_decide_run_gate()` below
        passes `confine_root=self._workspace_root` to `exec_in_attempt()`
        so THAT call opens the cwd once, checks the directory it opened,
        and starts the gate in that same directory - see its own docstring
        (#338), including what it does not guarantee (a subject that can
        rename the opened directory can still move it after the check). This method staying unchanged in shape is deliberate: the
        fix is bounded to `exec_in_attempt()`'s own cwd handling, not a
        redesign of this witness."""
        if cwd is None:
            return None
        if self._workspace_root is None:
            raise ChannelRefusal("run_gate: a cwd was requested but this attempt accepts none")
        if not isinstance(cwd, str) or not cwd:
            raise ChannelRefusal(f"run_gate: cwd must be a non-empty string, not {cwd!r}")
        resolved = self._backend.resolve_realpath_in_attempt(self._handle, cwd)
        if resolved is None:
            raise ChannelRefusal("run_gate: cwd could not be resolved inside the attempt")
        if resolved != self._workspace_root and not resolved.startswith(self._workspace_root + "/"):
            raise ChannelRefusal(
                f"run_gate: cwd resolves outside the attempt's workspace root ({self._workspace_root!r})"
            )
        return resolved

    def _state_snapshot(self, cwd: str | None) -> gate_state.Snapshot:
        assert self._state_snapshot_fn is not None
        try:
            return self._state_snapshot_fn(cwd)
        except Exception:  # noqa: BLE001 - failed controller export is unavailable
            return gate_state.Snapshot(None, None, {}, "state-export-unreadable")

    def _decide_run_gate(self, request: Mapping[str, object]) -> Mapping[str, object]:
        gate = request.get("gate")
        if not isinstance(gate, str) or gate not in self._declared_argv:
            # Red case 1: the controller's own declared set is the only
            # source of truth for what may be run at all.
            raise ChannelRefusal(f"run_gate: {gate!r} is not a declared gate for this attempt")
        via = request.get("via")
        if "via" in request and (not isinstance(via, str) or via not in self._declared_variants.get(gate, {})):
                raise ChannelRefusal(f"run_gate: {via!r} is not a declared variant of {gate!r}")
        runner = self._staged.get(gate)
        if via is not None and runner is not None:
            raise ChannelRefusal(f"run_gate: a variant of the staged gate {gate!r} is not supported (#525)")
        argv = self._declared_variants[gate][via] if isinstance(via, str) else self._declared_argv[gate]
        requested_stages: tuple[str, ...] | None = None
        make_args = request.get("make_args", [])
        if runner is None and ("make_args" in request or "make_env" in request):
            raise ChannelRefusal(f"run_gate: {gate!r} takes no make_args or make_env")
        if runner is not None:
            requested_stages = runner.plan(request)
            if requested_stages is None:
                # #508 ruling 1: not a gate invocation. No run exists, and the
                # shim runs the real make itself - never refused, so the
                # agent's workflow is unchanged.
                return {"accepted": False, "passthrough": True, "reason": "not a gate invocation"}
        gate_cwd = self._confine_requested_cwd(request.get("cwd"))
        with self._lock:
            if self._workspace_integrity_unknown:
                # Orchestrator ruling on finding 3: an earlier timeout or
                # cancellation could not be confirmed dead in-container - a
                # possibly-still-running zombie could be mutating the tree
                # ANY further gate would measure. Refuse every later
                # run_gate for the rest of the attempt; gates that already
                # completed keep their own records unchanged.
                raise ChannelRefusal(
                    f"run_gate: {gate!r} refused - workspace-integrity-unknown "
                    "(an earlier timeout/cancellation was not confirmed stopped)"
                )
            if self._in_flight[gate]:
                # Red case 2: a CONCURRENT duplicate (the same gate, still
                # executing) is refused. A SEQUENTIAL rerun (the prior run
                # already resolved) is not refused here - flow-check
                # legitimately reruns a gate after fixing it.
                raise ChannelRefusal(f"run_gate: {gate!r} is already executing for this attempt")
            self._in_flight[gate] = True
        try:
            with self._exec_lock:
                with self._lock:
                    if self._workspace_integrity_unknown:
                        raise ChannelRefusal(
                            f"run_gate: {gate!r} refused - workspace-integrity-unknown "
                            "(an earlier queued execution was not confirmed stopped)"
                        )
                execution = (self._resume_state.begin(gate_cwd, self._state_snapshot(gate_cwd))
                             if self._resume_state is not None else None)
                try:
                    # A gate waiting behind another gate must snapshot AFTER it,
                    # not measure the tree that existed when its request arrived.
                    tree_digest = self._tree_digest_fn()
                    source: str | None = None
                    # #530: a source digest without the ordering counter, for a
                    # fixture that opts in (every earlier caller passes the
                    # function only together with an order, so nothing changes).
                    if self._order is not None or self._source_digest_fn is not None:
                        try:
                            source = (self._source_digest_fn(gate_cwd) if self._source_digest_fn is not None
                                      else "unreadable: no source-digest function")
                        except Exception as exc:  # noqa: BLE001 - an unreadable tree never matches a commit
                            source = f"unreadable: {type(exc).__name__}"
                    if execution is not None:
                        source = execution.before.source
                    with self._lock:
                        run = _Run(requested_at=time.time(), tree_digest_at_start=tree_digest,
                                   order_requested=self._order.next() if self._order is not None else None,
                                   source_digest_at_start=source, via=via if isinstance(via, str) else None)
                        self._runs[gate].append(run)
                        unsupported = self._backend_unsupported
                    staged_capture: Mapping[str, object] | None = None
                    if unsupported:
                        result = ExecuteResult(reason="unsupported", exit_code=None)
                    elif runner is not None:
                        assert requested_stages is not None and isinstance(make_args, list)
                        result, staged_capture = runner.run(
                            self._backend, self._handle, self._limits, requested_stages, cwd=gate_cwd,
                            env=self._declared_env.get(gate), confine_root=self._workspace_root,
                            make_args=[str(a) for a in make_args])
                    else:
                        result = self._backend.exec_in_attempt(
                            self._handle, list(argv), self._limits,
                            cwd=gate_cwd, env=self._declared_env.get(gate),
                            # #338's opened-directory boundary, never replaced by
                            # the earlier realpath check or a subject status claim.
                            confine_root=self._workspace_root,
                        )
                    output_bad = result.reason == "exited" and (
                        result.stdout is None or result.stdout_truncated
                        or result.stdout_incomplete or result.stderr_incomplete
                        # #334: a capped raw stderr cannot be forwarded as whole.
                        or result.stderr_truncated
                    )
                    stages: Mapping[str, object] | None
                    if runner is not None:
                        stages = (dict(staged_capture, cwd=gate_cwd, workspace_root=self._workspace_root)
                                  if staged_capture is not None and not output_bad
                                  else _stages_unavailable("controller output is missing or incomplete" if output_bad
                                                           else f"run did not start (reason {result.reason!r})"))
                    else:
                        stages = self._read_stages(gate, result, output_bad, gate_cwd)
                    retained = self._retain_output(result)
                    state_evidence = None
                    if execution is not None:
                        assert self._resume_state is not None
                        stages, state_evidence = self._resume_state.finish(
                            execution, gate, result, retained, self._state_snapshot(gate_cwd), stages)
                    with self._lock:
                        if result.reason == "unsupported":
                            self.channel_unavailable = True
                            self._backend_unsupported = True
                        if output_bad:
                            self.channel_unavailable = True
                        if result.stop_confirmed is False:
                            self._workspace_integrity_unknown = True
                        run.completed_at = time.time()
                        if self._order is not None:
                            run.order_completed = self._order.next()
                        run.exit_code = result.exit_code
                        run.reason = result.reason
                        run.stop_confirmed = result.stop_confirmed
                        run.stages = stages
                        run.output = retained
                        run.state_evidence = state_evidence
                except BaseException:
                    if execution is not None:
                        assert self._resume_state is not None
                        self._resume_state.invalidate(execution.key, execution.sequence)
                    raise
                if output_bad:
                    raise ChannelRefusal("gate-witness: controller output is missing or incomplete")
                lossless: dict[str, object] = {}
                if runner is not None:
                    # #508: a staged gate's reply stands in for make's own
                    # output, so its bytes travel exactly (base64), not decoded.
                    lossless = {"stdout_b64": base64.b64encode(result.stdout or b"").decode("ascii"),
                                "stderr_b64": base64.b64encode(result.stderr or b"").decode("ascii")}
                return {
                    **lossless,
                    "accepted": True,
                    "exit_code": result.exit_code,
                    "reason": result.reason,
                    "stdout": (result.stdout or b"")[:self._stdout_reply_cap].decode("utf-8", errors="replace"),
                    "stderr": (
                        result.stderr[:self._stderr_reply_cap].decode("utf-8", errors="replace")
                        if result.stderr is not None else (result.error or "")[:self._stderr_reply_cap]
                    ),
                }
        finally:
            # Includes a failed snapshot and backend exceptions; neither may
            # wedge this gate's in-flight claim forever.
            with self._lock:
                self._in_flight[gate] = False

    def _retain_output(self, result: ExecuteResult) -> dict[str, object]:
        retained: dict[str, object] = {}
        streams = (("stdout", result.stdout, result.stdout_truncated, result.stdout_incomplete),
                   ("stderr", result.stderr, result.stderr_truncated, result.stderr_incomplete))
        for (stream, raw, truncated, incomplete), cap in zip(streams, self._output_limits, strict=True):
            if raw is None or self._output_store is None:
                retained[stream] = {"coverage": "missing", "reason": "no raw output" if raw is None else
                                    "no controller output store"}
                continue
            data = raw[:cap]
            try:
                digest = self._output_store(data)
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or digest != _output_digest(data):
                    raise ValueError("output sink returned the wrong digest")
            except Exception as exc:  # noqa: BLE001 - retention must not alter the observed gate result
                retained[stream] = {"coverage": "refused", "reason": f"output retention refused ({type(exc).__name__})"}
                continue
            retained[stream] = {"coverage": "partial" if truncated or incomplete or len(raw) > cap else "complete",
                                "digest": digest, "size": len(data), "truncated": truncated or len(raw) > cap,
                                "incomplete": incomplete}
        return retained

    def _read_stages(self, gate: str, result: ExecuteResult, output_bad: bool,
                     gate_cwd: str | None) -> Mapping[str, object] | None:
        """#376: the run's stage capture, or `None` for a gate with no reader.
        Only a normally exited run with complete output is read; anything
        else, including a reader that raises, is an `unavailable` capture.

        A captured result is BOUND to where it ran: `cwd` is the controller-
        resolved directory (`None` when the subject requested none) and
        `workspace_root` this attempt's root. Stage outcomes from a
        neighbouring project under the workspace describe that project, not
        the one a report is about, so a consumer compares the two (Codex
        review of #376)."""
        reader = self._stage_capture.get(gate)
        if reader is None:
            return None
        if result.reason != "exited":
            return _stages_unavailable(f"run did not exit normally (reason {result.reason!r})")
        if output_bad:
            return _stages_unavailable("controller output is missing or incomplete")
        try:
            capture = dict(reader(result.stdout, result.exit_code))
        except Exception as exc:  # noqa: BLE001 - a reader defect is evidence of nothing
            return _stages_unavailable(f"stage reader failed ({type(exc).__name__})")
        capture["cwd"] = gate_cwd
        capture["workspace_root"] = self._workspace_root
        return capture

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
        if self._resume_state is not None and attempt_id != self._resume_state.attempt_id:
            raise ValueError("resume ledger belongs to another attempt")
        with self._lock:
            records: dict[str, GateRecord] = {}
            for gate, runs in self._runs.items():
                run_records = tuple(
                    GateRunRecord(
                        requested_at=r.requested_at, completed_at=r.completed_at,
                        exit_code=r.exit_code, reason=r.reason,
                        tree_digest_at_start=r.tree_digest_at_start,
                        stop_confirmed=r.stop_confirmed,
                        stages=(r.stages if r.stages is not None
                                else _stages_unavailable("run never resolved") if gate in self._stage_capture
                                else None),
                        order_requested=r.order_requested, order_completed=r.order_completed,
                        source_digest_at_start=r.source_digest_at_start, via=r.via, output=r.output,
                        state_evidence=r.state_evidence,
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
                elif run_records:
                    # At least one run_gate arrived for this gate, but NONE
                    # of them started a real process - the subject DID ask;
                    # the CONTROLLER failed to launch it. Orchestrator
                    # correction: this must NEVER share `not-observed`'s
                    # coverage, because `not-observed` is what
                    # `execution_observed()` allows to become
                    # `NOT_CONFIRMED` under asserted exclusivity, and doing
                    # that here would attribute the controller's own
                    # infrastructure failure to the subject as positive
                    # proof it never ran its checks - the mirror image of
                    # the bug this witness exists to stop.
                    coverage = "launch-failed"
                else:
                    # Zero run_gate requests ever arrived - a TRUE bypass or
                    # a genuinely skipped gate. This is the ONLY population
                    # `execution_observed()` may ever read as `NOT_CONFIRMED`.
                    coverage = "not-observed"
                records[gate] = GateRecord(
                    coverage=coverage, runs=run_records,
                    exclusivity_asserted=self._gate_exclusivity,
                    exclusivity_basis=self._exclusivity_basis,
                )
            return GateWitnessRecord(attempt_id=attempt_id, declared_gates=tuple(self._declared_argv), gates=records)
