# Design: a controller-owned gate-execution witness (#269)

- Status: Revised after orchestrator review - the controller EXECUTES each
  declared gate itself; a subject-reported outcome was found to be a
  subject-authored claim recorded as a controller fact, the exact thing
  #269 exists to stop. Implemented and tested against a fake `ExecutionBackend`
  test double and a real `DockerBackend` running the fake `docker` CLI; the
  real `export()`-backed tree digest, and a real daemon's signal-propagation
  behavior for in-place exec timeout/cancel, remain owed (same limitation
  #183's own live test states)
- Date: 2026-10-06 (revised same day, after the first draft's review)
- Refs: #269, #183 (the channel this builds on), #268 (`records.md`'s
  already-merged "Trust boundary needed by #269" section), #266 (explicitly
  NOT a dependency of this issue's own acceptance - see §0), #304 (tracks
  `ExecutionBackend.execute()`'s own stop-after-exec behavior, separate from
  this design and not changed by it)
- Touches: new `skillc/gate_witness.py`, reusing `skillc/decide_reply_channel.py`
  unmodified; new `ExecutionBackend.exec_in_attempt()` method
  (`skillc/backend.py` Protocol, implemented in `skillc/docker_backend.py`
  and `skillc/managed_backend.py`) - a shared-seam addition, not a change to
  `execute()`'s own contract

## 0. Why #266 is not a dependency here

#269's own acceptance says "Show real deterministic processes succeeding,
failing and being interrupted through the protected path. No live model is
required." That is a synthetic-process bar - the same one #183's own red
case and conformance tests clear with a Python one-liner, never a real CPP
trial. #266 (materializing a real, installable flow-check profile in a clean
container) only matters once something wires this witness around an ACTUAL
CPP gate invocation inside a real trial - that is #270/#271's territory (then
#287/#288 toward CPP #1371), not this issue's bounded scope. Everything below
is built and tested against synthetic gates, independent of #266's own
timeline.

## 1. What this reuses, and the one thing it adds to the backend seam

`skillc/decide_reply_channel.py` (#183) is the transport, exactly as #183's
own design doc §2e promised: a host-owned Unix socket, one per attempt, the
controller as the only listener, deciding and logging its own decision
before any reply. This module supplies its OWN `decide` function and its OWN
request/response vocabulary (`run_gate`, below) - no change to
`DecideReplyChannel`, `DockerBackend`'s mount, or `compose_run_argv` is
needed or made here.

**The one addition is `ExecutionBackend.exec_in_attempt()`** (§1a below) -
required because the first draft of this design called `execute()` to run a
gate, and `execute()` is one-shot per handle BY CONTRACT: it always stops
the attempt's container before returning, whether the subject exited on its
own or was killed for timeout. Calling it even ONCE for a gate would stop
the attempt - and if the subject's own primary `execute()` were still
running in that same container, kill that too. `execute()` was never the
right seam for this; `exec_in_attempt()` is additive, and `execute()` itself
is unchanged for every existing caller.

### 1a. `ExecutionBackend.exec_in_attempt()` (new, shared-seam)

`exec_in_attempt(handle, argv, limits, cancel=None, stdin=None) ->
ExecuteResult` - runs `argv` inside the SAME running isolation `handle`
already identifies, via a bare `docker exec`, WITHOUT ever stopping or
removing it. Same `stdin` delivery convention as `execute()`; `limits.timeout`
bounds only this one call.

**Refused, never folded into a guessed `exited` result:**
- the attempt's own primary process is not reachable to exec into at all -
  not started, already stopped, or confirmed absent - checked via the SAME
  `_inspect()` `confirm_stopped()` already uses, so a caller cannot get a
  different answer from the two: `ExecuteResult(reason=
  "attempt-not-running", exit_code=None)`.
- this backend does not implement the method at all: `ExecuteResult(reason=
  "unsupported", exit_code=None)`. `ManagedBackend`'s protocol version 1
  carries no `exec_in_attempt` row on its page, so it always answers this -
  a caller (the gate-execution witness) must treat the WHOLE mechanism as
  unavailable for this attempt, never retry expecting a different answer.

**`DockerBackend`'s implementation** shares its launch/drain/timeout-loop
and its join/error/observations-write-back tail with `execute()` (two
private helpers, `_launch_and_wait`/`_finish_result`, factored out of the
pre-existing method rather than duplicated) - the ONE thing the two methods
do differently is what happens to the container afterward.

**TIMEOUT/CANCEL CONFIRMS THE IN-CONTAINER PROCESS IS DEAD (orchestrator
ruling on finding 3, codex `code_review`).** A first pass signaled only
the LOCAL `docker exec` client's own process group - against a real
daemon this does NOT reliably terminate the session it started inside the
container, so a timed-out gate could leave an orphaned process still
mutating the workspace while a rerun (or a different gate) started against
the same tree, corrupting exactly the facts this witness exists to
certify. The orchestrator rejected both obvious half-measures - leaving
the race (a gate rerun could overlap a still-running zombie) and
over-silencing (one slow gate killing observation of every later gate) -
in favor of CONFIRMED absence, the same rule `confirm_stopped()`/
`confirm_absent()` already apply to the whole attempt:

- `argv` is wrapped as `sh -c 'echo $$ > MARKER; exec "$@"' sh <argv...>`,
  so the in-container process reports its OWN pid (surviving the `exec`
  that replaces the shell with it) to a per-call marker path
  (`_read_in_container_pid`, polled via a second `docker exec ... cat
  MARKER`).
- On timeout or `cancel()`, a THIRD exec (`_confirm_and_kill_in_container`)
  sends `kill -TERM` to that pid INSIDE the container, polls `kill -0` for
  `limits.grace`, escalates to `kill -KILL` if still alive, and polls
  again - never touching the container itself, only this one pid. Every
  one of these goes through `sh -c 'kill ...'`, never a bare `kill` argv -
  `kill` is a POSIX SHELL BUILTIN (dash, bash), so this needs no
  standalone `kill` binary on the image's PATH at all, which CI's
  `python:3.12-slim` is not guaranteed to carry (the `procps` package it
  usually comes from). Verified directly: `test_confirmed_kill_needs_no_
  standalone_kill_binary_on_path` strips `PATH` down to `sh`/`cat`/
  `python3`/`tar` before `prepare()` (whose captured `handle.env` every
  later call on that handle reuses) and the confirmed-kill path still
  passes. `kill -0`'s own exit 0 (alive) or its explicit "No such process"
  text (confirmed dead) are the only two signals trusted; any other
  nonzero exit (the exec infrastructure itself failing - a bad
  `docker_bin`, a dropped daemon) is UNKNOWN, never guessed as either
  answer (mirrors `_inspect()`'s own discipline).
- `ExecuteResult.stop_confirmed` reports the outcome: `True` only once
  death is independently confirmed; `False` when the pid was never
  learned, the kill exec itself could not be reached, or the process
  survives escalation; `None` for `reason == "exited"` (no kill needed)
  and for every `execute()` result (not applicable there).
- `GateWitness` reads `stop_confirmed is False` as `_workspace_integrity_
  unknown = True` - sticky, and REFUSES every later `run_gate` for the
  rest of the attempt (`workspace-integrity-unknown`), for ANY declared
  gate, because a possibly-still-running zombie could be mutating the tree
  any later gate would measure. Unlike `channel_unavailable`, this never
  retroactively changes a gate that already completed - its own record
  stands.

The LOCAL client's own process group is still reaped afterward regardless
(`start_new_session=True` at launch), so `exec_in_attempt()` itself returns
promptly rather than waiting on a client whose remote session may outlive
it. `term_forwarding` is always `None` on this method's results - not
applicable, since it never sends a container-level signal for anything to
forward.

**Owed, named precisely rather than silently assumed solved**: this
three-exec sequence (marker write-back, in-container kill, in-container
`kill -0` confirmation) is exercised here only against the fake CLI
(`tests/fixtures/docker-backend/fake_docker.py`, which runs the simulated
subject as the local client's own direct child and has a real `kill`
binary to confirm against). A REAL daemon's behavior for this sequence is
not demonstrated - named as owed, matching every other real-daemon
question this feature already defers (the real `tree_digest_fn`, the
#158 forwarding capability check).

**Closed by this revision: the shared `observations` artifact race
(codex `code_review`).** `exec_in_attempt()` shares `execute()`'s own
write-back convention - the exec'd process's stdout lands at
`<workspace>/observations`, read back via `export()` - which means two
concurrent execs (two different gates, or a gate racing the primary
subject's own `execute()`) could read each other's output. `GateWitness`
closes this by serializing the ACTUAL exec-and-read critical section
across the WHOLE witness (a dedicated lock, separate from the one guarding
claim bookkeeping) - different gates may still be CLAIMED concurrently,
but their execs and observation reads never overlap. This trades
cross-gate exec concurrency for correctness; given `#1a`'s own real-daemon
caveats, that trade was judged worth making without a separate round of
review.

## 2. The record: one per attempt, every run of every declared gate

**Decision (orchestrator ruling): ONE record per attempt, not one per
gate.** A per-gate record cannot express a declared gate that was never
started at all - absence of a record is not a record. The declared gate
set, and each gate's real argv, is supplied by whoever constructs the
witness for an attempt (the controller's own plan - a ledger entry or task
declaration - never the subject), and EVERY declared gate appears in the
finalized record with an explicit coverage state, including the ones
nothing was ever heard about.

**Decision (orchestrator correction): EVERY run is recorded, not only the
first.** Flow-check legitimately reruns a gate after fixing a failure, so
"one run per gate per attempt" would refuse a real workflow. A concurrent
duplicate (the same gate, still executing) is refused; a sequential rerun
(the prior run already resolved) is accepted and appended - nothing already
recorded is ever overwritten, so "paper over a bad first run" stays
impossible even though reruns are allowed.

```json
{
  "kind": "gate-witness",
  "version": 2,
  "attempt_id": "a-...",
  "declared_gates": ["lint", "typecheck"],
  "gates": {
    "lint": {
      "coverage": "complete",
      "runs": [
        {"requested_at": 1759700000.1, "completed_at": 1759700000.4, "exit_code": 1, "reason": "exited", "tree_digest_at_start": "sha256:a..."},
        {"requested_at": 1759700010.2, "completed_at": 1759700010.5, "exit_code": 0, "reason": "exited", "tree_digest_at_start": "sha256:b..."}
      ],
      "exclusivity": {"asserted": false, "basis": ""}
    },
    "typecheck": {"coverage": "not-observed", "runs": [], "exclusivity": {"asserted": false, "basis": ""}}
  }
}
```

`gates[gate]` is present for every name in `declared_gates`, always - a
declared gate absent from `gates` would be exactly the "absence is not a
record" gap this design exists to close.

## 3. Request/response vocabulary

ONE op, carrying nothing but the gate's declared name:

```json
{"op": "run_gate", "gate": "lint"}
```

No `invocation_id` (there is no separate completion message to pair - the
controller performs start-and-result in one call). No `exit_code`, no
completion message, and **no `tree_digest` field, ever** (§6 explains why a
subject-claimed one would be worse than useless) - there is structurally
nothing in the request for a subject to forge an outcome or a tree claim
with.

**The reply carries the real result (orchestrator correction over the first
draft's "reply reveals nothing").** Hiding the gate's own exit code would
break the workflow under test: flow-check runs a gate, reads its failures,
fixes them, and reruns - a subject that cannot see a gate's result cannot do
that workflow, so every trial would measure a crippled skill, not the real
one. The reply is `{"accepted": true, "exit_code": ..., "reason": ...,
"stdout": "...", "stderr": "..."}` - stdout/stderr truncated to a declared
byte cap (`reply_byte_cap`, default 4096). This is exactly what the subject
would see running the gate itself. What it does NOT get: the witness's own
coverage state, any other gate's status, or any tree digest - the witness
stays trustworthy regardless of what the reply contains, because the RECORD
is controller-written and never derived from anything the subject sees or
sends back.

## 4. The `decide` function's refusals

`run_gate` is refused (`ChannelRefusal`) when:
- `gate` is not in this attempt's own `declared_gates` - the controller's
  own plan is the only source of truth for what may be run at all, never
  the subject's request content.
- `gate` already has a run EXECUTING RIGHT NOW for this attempt - a
  CONCURRENT duplicate. The gate is claimed (checked-and-set) under the
  witness's own `_lock` BEFORE anything else runs, then `_lock` is released
  for the (potentially slow) tree-digest call and the exec itself, then
  re-acquired to record the result - so a racing duplicate is refused at
  claim time even while the first is still running.

**A SEQUENTIAL rerun (the prior run already resolved) is NOT refused** -
see §2's correction. The old "orphan/replayed completion" and "cross-gate
invocation-id collision" refusal families from the first draft are GONE,
structurally, not fixed: there is no separate completion message for the
subject to forge or replay, and no subject-generated id to collide. The
controller is the only thing that ever produces a result, in the same call
that accepted the request.

**Two failure points are cleaned up identically, and both are
mutation-checked (codex `code_review` correction)**: an exception out of
`exec_in_attempt()` itself, and an exception out of `tree_digest_fn()`. The
first draft computed the digest INSIDE the SAME claim, with no cleanup on
failure - a digest that raised once wedged the gate as permanently
"already executing," refusing every later request including a legitimate
retry. Both paths now clear `_in_flight[gate]` before re-raising, and
neither records a resolved run - `finalize()` tells a resolved exception
(cleared `_in_flight`) apart from a call genuinely still running when the
channel tore down (`_in_flight` still `True`) - see §5.

**`exec_in_attempt()` is never called again once it has answered
`"unsupported"` for any gate (codex `code_review` correction).** The first
draft kept calling a backend already known incapable for every later
`run_gate`, including for OTHER declared gates. A sticky
`_backend_unsupported` flag, set the first time this happens, short-circuits
every later request straight to the same `reason="unsupported"` reply
without touching the backend again - the run is still recorded (for
transparency), but no exec and no `export()` read are attempted.

## 5. Coverage and `execution_observed`

Four coverage states, computed OVER a gate's full run list (never only its
first or its most recent run):

| Coverage | Meaning |
|---|---|
| `complete` | AT LEAST ONE run reached its own natural end (`reason == "exited"`) |
| `interrupted` | at least one run GENUINELY STARTED a process but did not reach `"exited"` - a timeout, an operator-cancellation, or a call still running when the channel tore down (`_in_flight` for that gate still `True` at `finalize()` time - see below) |
| `not-observed` | no run_gate ever arrived for this declared gate, OR every run that did arrive never started a real process at all - see the `_NOT_STARTED_REASONS` correction below |
| `channel-unavailable` | the channel itself could not be constructed/was unreachable for this whole attempt, OR the backend answered `exec_in_attempt` with `reason="unsupported"` for any run (the whole mechanism is unavailable for this attempt, not merely one call) |

**Correction (codex `code_review` of the controller-executes revision): a
run that never started a process is NOT `interrupted`.** The first pass of
this revision folded `"launch-failed"` (the exec itself never launched),
`"attempt-not-running"`, and `"unsupported"` into `interrupted`, which let a
refused or never-launched exec report `execution_observed: CONFIRMED` -
positive execution evidence for a gate that never ran at all, moved from
the subject (the first draft's bug) to a failed launch (this one). Fixed:
`_NOT_STARTED_REASONS = {"launch-failed", "attempt-not-running",
"unsupported"}` contributes to neither `complete` nor `interrupted`; a gate
whose only runs carry one of these reasons reads `not-observed`, same as a
full bypass - the raw `runs` list still shows the attempted-but-failed-to-
launch run for anyone reading it directly, so nothing is hidden, only kept
out of the execution-confirmed bucket.

**The teardown-cutoff case is disambiguated by `_in_flight`, not by `reason
is None` alone.** Both a genuinely-still-running call (cut off when the
channel tore down - a process plausibly STARTED) and a resolved exception
from `exec_in_attempt()` itself (an infrastructure fault before any
confirmed outcome) leave a run with `reason is None`. The exception path
always clears `_in_flight[gate]` before re-raising; the teardown-cutoff
case cannot, because the thread is still blocked inside the call. So
`finalize()` reads a trailing `reason is None` run as `interrupted` only
when `_in_flight[gate]` is STILL `True` - otherwise it is treated the same
as a `_NOT_STARTED_REASONS` run.

`execution_observed`:
- `CONFIRMED` for `complete` OR `interrupted` - both mean the controller
  genuinely caused the gate to execute; whether any run finished, and what
  it returned, are the separate `coverage`/`exit_code`/`reason` facts,
  never folded into `execution_observed` itself.
- `not-observed` SPLITS, per the orchestrator's correction to the first
  draft's blanket "never `NOT_CONFIRMED`" ruling:
  - If `gate_exclusivity=True` was asserted for this attempt AND the
    channel was never `channel-unavailable` for any part of it:
    **`NOT_CONFIRMED`, reason `proven-non-execution`.**
  - Otherwise (the default): `UNKNOWN`, reason `no-controller-witness`.
- `channel-unavailable`: `UNKNOWN`, reason `channel-unavailable`.

**`gate_exclusivity: bool` - a REQUIRED constructor parameter, no default**,
paired with a required `exclusivity_basis: str`. Scoped precisely: asserts
proven non-execution THROUGH THE DECLARED COMMAND PATH ONLY - never that
the subject could not achieve the gate's equivalent effect by some other
means outside this witness's view. True only when the fixture gives the
subject no direct way to invoke this gate's command at all (no binary,
script, or path reachable from inside the subject's own isolation). This
module cannot verify that assertion itself - it trusts it, exactly as
`tree_digest_fn` is trusted to compute a real digest.

**Recorded on EVERY gate, regardless of value** (orchestrator correction: "a
`NOT_CONFIRMED` that rests on an unverified constructor boolean is a verdict
built on an assertion nobody can see later") - `exclusivity: {"asserted":
bool, "basis": str}` in §2's JSON shape, so any reader of `NOT_CONFIRMED` -
or of its absence - sees exactly what that verdict rests on, never an
invisible constructor argument.

**Cheap verification is owed, not implemented.** A caller COULD cheaply
check the assertion (have the controller run `command -v <argv0>` as the
subject's own identity and expect absence) and record the result alongside
`exclusivity`. Not built in this pass: it needs a decision about when it
runs (at construction? at first `run_gate`? re-checked per run?) and how an
ambiguous `command -v` result (a shell builtin, an alias, a PATH this
witness cannot fully enumerate) is reported - rushing it risks a
verification mechanism that is itself wrong. `exclusivity.basis` is
recorded as an unverified assertion string for now.

**`gate-not-executed` stays OUT of `SKILL_EVIDENCE_CONTRADICTING_REASONS`**
(`skillc/records.py`, #268's review) until `gate_exclusivity` has its own
committed red-case fixture demonstrating `proven-non-execution` end to end -
orchestrator instruction, not yet done as of this revision.

## 6. Tree identity: controller-computed, never subject-claimed

**The question this design must answer: what does "a request naming a
different tree cannot satisfy observed execution" (#269's acceptance)
actually mean, given a subject legitimately edits the workspace between
gates?**

A subject-CLAIMED tree digest, checked by the controller against anything,
fails on both counts at once: refusing a mismatch would refuse every HONEST
gate run after the subject's first edit (the tree is SUPPOSED to change), and
a subject-supplied digest is itself subject-writable - checking it against
anything proves only that the subject can compute a hash, never that the
hash describes the tree that actually existed.

**The resolution: the controller computes the tree identity ITSELF,
immediately before each `exec_in_attempt()` call, by reading the workspace
through the same read-only, safe-to-call-more-than-once channel
`AuthorityInterceptor`/`DisruptionTrigger` already poll
(`ExecutionBackend.export()`) - never from anything the request carries.**
`tree_digest_at_start` in §2's record is this self-computed value per RUN,
recorded unconditionally, never compared or refused against anything AT
DECIDE TIME. The comparison this design's acceptance wording is actually
asking for happens LATER, outside this witness: a grader consuming this
record checks each run's `tree_digest_at_start` against the digest of the
tree it is actually grading and decides FOR ITSELF whether a run against a
now-superseded tree should count toward whatever it is judging. This
witness's own job stops at recording an honest, controller-computed fact
per run; the grading decision belongs to #270/#271.

**What is owed, not shipped here.** `tree_digest_fn` is tested against a
FAKE callable (a stub returning a fixed string). Whether a REAL `export()`
against a REAL daemon produces a stable, correctly timed digest at exec
time is a live-Docker question this design does not simulate - named as
owed, the same discipline #183's own §2f(c) and live test already use.

## 7. Citation into `skill-evidence` - no new mechanism

`records.md`'s own "Trust boundary needed by #269" section (already merged,
in #268) fully specifies this: the finalized `gate-witness` record is
captured as an ordinary `artifact-manifest.artifacts` entry (`type:
"gate-witness"`, matching the record's own `kind`), and
`skill-evidence.lifecycle.execution_observed.evidence` cites that entry by
`{ref, digest}` - the identical check that already refuses a `verified-result`
citing an uncaptured digest. This design adds no new citation mechanism -
only the record this one now names, with its revised §2 shape.

## 8. Red cases (mutation-checked)

1. **Undeclared gate.** `run_gate` naming a gate not in `declared_gates` -
   refused, and the backend is never even called. Mutation: remove the
   declared-set check, confirm an undeclared gate is silently admitted.
2. **Concurrent duplicate.** A second `run_gate` for a gate still executing
   - refused. Mutation: remove the global in-flight check, confirm the
   second call is admitted while the first is still running (demonstrated
   against a backend double whose `exec_in_attempt()` blocks).
3. **Sequential reruns are both recorded, never overwritten.** A gate run
   twice, with the prior run resolved before the second starts - both
   appear in `runs`, in order, the first's own result unchanged by the
   second's. Mutation: confirm a version that replaces rather than appends
   loses the first run.
4. **The reply carries the real result.** `exit_code`/`reason`/bounded
   `stdout`/`stderr` in the reply match the backend's own `ExecuteResult` -
   and the reply contains NOTHING else (no coverage, no other gate's name,
   no tree digest). Mutation: confirm a version that omits `exit_code` from
   the reply is not what a flow-check-style caller could act on.
5. **Interrupted coverage, genuinely-started causes only.** A genuine run
   whose `reason` is `"timeout"` or `"operator-cancelled"`, OR a run still
   running when the channel tore down (`_in_flight` still `True`) - all
   `interrupted`, `CONFIRMED`, never `complete` and never `UNKNOWN`.
   Mutation: confirm the coverage computation actually treats a non-
   `"exited"`-but-started reason as `interrupted` rather than `complete`
   (the first draft's own bug, found by review - a timeout WAS being read
   as a clean completion).
5a. **Never-started causes are `not-observed`, never `interrupted`
   (codex `code_review` correction).** `"launch-failed"`,
   `"attempt-not-running"`, and a RESOLVED exception from
   `exec_in_attempt()` (one that cleared `_in_flight` before re-raising,
   as opposed to a call still genuinely running) all mean no process ever
   started - `not-observed`, `UNKNOWN`, never `CONFIRMED`. Mutation:
   confirm a version that folds these into `interrupted` reports positive
   execution evidence for a gate that never ran at all (the exact bug this
   case exists to catch - codex found it in the controller-executes
   revision's first pass).
5b. **A resolved exception vs. a genuine teardown cutoff.** Both leave a
   run with `reason is None`; `_in_flight[gate]` is what tells them apart
   (cleared by the exception path, left `True` by a genuinely stuck call).
   Mutation: confirm the derivation ignores `_in_flight` and reads every
   `reason is None` run as `interrupted` - this reports `CONFIRMED` for a
   backend exception that never started anything.
5c. **A digest failure clears `_in_flight` and records nothing, exactly
   like an `exec_in_attempt()` failure.** Mutation: confirm a version that
   computes the digest without this cleanup leaves the gate permanently
   "already executing," refusing even a legitimate retry.
5d. **`unsupported` is sticky - the backend is never called again.**
   Mutation: confirm a version that re-checks `exec_in_attempt()` on every
   request calls a backend already known incapable for a SECOND declared
   gate, after the first already answered `unsupported`.
6. **Full bypass, `UNKNOWN` by default.** A declared gate the subject never
   contacts the channel about at all, `gate_exclusivity=False` - `UNKNOWN`,
   reason `no-controller-witness`, never `NOT_CONFIRMED`.
7. **Full bypass, `NOT_CONFIRMED` only under asserted exclusivity.** The
   same bypass, `gate_exclusivity=True` - `NOT_CONFIRMED`, reason
   `proven-non-execution`, and `exclusivity.asserted` is `true` in the
   record. Mutation: confirm the derivation does not produce
   `NOT_CONFIRMED` when the flag is `False` (red case 6 pins the other
   half of the same branch).
8. **`exclusivity` is recorded on every gate, not only ones reaching
   `NOT_CONFIRMED`.** Mutation: confirm a version that only writes
   `exclusivity` when `asserted=True` makes a `False`-asserted gate's
   record silent about the premise.
9. **`attempt-not-running` is a refusal-shaped result, never a guessed
   `exited`.** Calling `exec_in_attempt()` after the attempt's own primary
   process has already stopped (via `execute()`'s own one-shot-and-stop
   contract) returns `reason="attempt-not-running"`, `exit_code=None` -
   demonstrated against a real `DockerBackend` and the fake `docker` CLI.
10. **`unsupported` makes the whole attempt `channel-unavailable`.**
    `ManagedBackend.exec_in_attempt()` always answers `reason=
    "unsupported"`; the witness reads this as `channel_unavailable=True`
    for every declared gate, not merely the one call that triggered it.
11. **`exec_in_attempt()` never stops the container, including on its OWN
    timeout.** A gate that times out inside `exec_in_attempt()` leaves the
    attempt's container `confirm_stopped() == NOT_CONFIRMED` (still
    running) afterward - demonstrated against the real `DockerBackend`.
12. **A gate exec never disturbs the attempt's own primary process.**
    Driving two gates and a rerun through `exec_in_attempt()` WHILE a real,
    separately-running primary subject process (started via `execute()`)
    is still inside the same container - the primary completes with its
    own real, undisturbed exit code afterward. This is the integration
    proof for the whole redesign: the first draft's `execute()`-based
    approach would have stopped the container (and the primary subject
    with it) at the FIRST gate exec, let alone a rerun.
13. **Confirmed kill, demonstrated against the real `DockerBackend`.** A
    gate that times out reports `stop_confirmed=True`, and the attempt's
    own container (`confirm_stopped()`) is still `NOT_CONFIRMED`-running
    afterward - the in-container pid died, never the container. Mutation:
    confirm `_alive()`'s "any nonzero exit = dead" shortcut (the bug this
    design found in its own first pass) reports `stop_confirmed=True` for
    an unreachable kill exec that never actually ran.
14. **Unconfirmed kill makes the attempt refuse every later `run_gate`,
    without touching already-completed gates.** `_confirm_and_kill_in_
    container` returns `False` when the kill exec itself cannot be
    reached (demonstrated with a broken `docker_bin` sharing a real
    container a working backend already launched). At the witness level,
    a `stop_confirmed=False` result on gate B, after gate A already
    completed, refuses a later request for EITHER gate with
    `workspace-integrity-unknown`, while gate A's own finalized record is
    untouched. Mutation: remove the `_workspace_integrity_unknown` check
    (or the flag-setting on `stop_confirmed is False`), confirm a rerun is
    admitted while the "zombie" is still alive in the fake.

## 9. What #270/#271 may build on

- The finalized record's shape (§2) and its four coverage states (§5) -
  #270/#271 are free to add their OWN criteria logic consuming
  `execution_observed`/`coverage`/`exit_code` per gate (now per RUN, plural)
  - this design commits only to what the witness itself may honestly
    report.
- The tree-identity comparison described but not performed in §6 - a grader
  that wants to refuse crediting a gate run against a stale tree does the
  comparison itself, against that run's own `tree_digest_at_start`.
- The citation shape (§7) is already fixed by `records.md`; nothing here
  changes it.
- The cheap `gate_exclusivity` verification named as owed in §5, and the
  real-daemon signal-propagation question named as owed in §1a, are both
  explicitly available for a later issue to close - neither is assumed
  solved by anything in this design.
