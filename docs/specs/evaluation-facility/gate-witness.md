# Design: a controller-owned gate-execution witness (#269)

- Status: Draft for review — design plus the parts testable without a real
  daemon; the real tree-identity mechanism is reasoned, not run, pending a
  Docker-capable environment (same limitation #183's own live test states)
- Date: 2026-10-06
- Refs: #269, #183 (the channel this builds on), #268 (`records.md`'s
  already-merged "Trust boundary needed by #269" section, which this design
  is written to satisfy exactly), #266 (explicitly NOT a dependency of this
  issue's own acceptance — see §0)
- Touches: new `skillc/gate_witness.py`, reusing `skillc/decide_reply_channel.py`
  unmodified; no `DockerBackend` change

## 0. Why #266 is not a dependency here

#269's own acceptance says "Show real deterministic processes succeeding,
failing and being interrupted through the protected path. No live model is
required." That is a synthetic-process bar — the same one #183's own red
case and conformance tests clear with a Python one-liner, never a real CPP
trial. #266 (materializing a real, installable flow-check profile in a clean
container) only matters once something wires this witness around an ACTUAL
CPP gate invocation inside a real trial — that is #270/#271's territory (then
#287/#288 toward CPP #1371), not this issue's bounded scope. Everything below
is built and tested against synthetic gates, independent of #266's own
timeline.

## 1. What this reuses, unchanged

`skillc/decide_reply_channel.py` (#183) is the transport, exactly as #183's
own design doc §2e promised: a host-owned Unix socket, one per attempt, the
controller as the only listener, deciding and logging its own decision
before any reply. This module supplies its OWN `decide` function and its OWN
request/response vocabulary (`gate_start`/`gate_complete`, below) — no change
to `DecideReplyChannel`, `DockerBackend`, or `compose_run_argv` is needed, and
none is made.

## 2. The record: one per attempt, covering the declared gate set

**Decision (orchestrator ruling on the first draft of this design): ONE
record per attempt, not one per gate.** A per-gate record cannot express a
declared gate that was never started at all — absence of a record is not a
record. The declared gate set is supplied by whoever constructs the witness
for an attempt (the controller's own plan — a ledger entry or task
declaration — never the subject), and EVERY declared gate appears in the
finalized record with an explicit coverage state, including the ones nothing
was ever heard about.

```json
{
  "kind": "gate-witness",
  "version": 1,
  "attempt_id": "a-...",
  "declared_gates": ["lint", "typecheck"],
  "gates": {
    "lint": {
      "coverage": "complete",
      "started_at": 1759700000.12,
      "completed_at": 1759700003.40,
      "exit_code": 0,
      "tree_digest_at_start": "sha256:...",
      "invocation_id": "..."
    },
    "typecheck": {
      "coverage": "not-observed"
    }
  }
}
```

`gates[gate]` is present for every name in `declared_gates`, always — a
declared gate absent from `gates` would be exactly the "absence is not a
record" gap this design exists to close.

## 3. Request/response vocabulary (the `decide` function's own content)

Two ops, both scoped to one gate invocation by a subject-generated
`invocation_id` (opaque to the controller — it is never trusted as identity,
only used to PAIR a start with its own completion, below):

- `{"op": "gate_start", "gate": "lint", "invocation_id": "..."}`
- `{"op": "gate_complete", "invocation_id": "...", "exit_code": 0}`

Reply for both: `{"accepted": true}` — nothing about the controller's
internal state is ever revealed back to the subject.

**No `tree_digest` field in the request, ever** (§6 explains why a
subject-claimed one would be worse than useless). The controller computes
its own tree identity at `gate_start` time and records that; the subject
supplies nothing about the tree.

## 4. The `decide` function's refusals (the "forged/replayed" red cases)

`gate_start` is refused (`ChannelRefusal`) when:
- `gate` is not in this attempt's own `declared_gates` — the controller's
  own plan is the only source of truth for what may be started at all, never
  the subject's request content;
- `gate` already has a START recorded for this attempt (whether or not it
  has since completed) — ONE start per declared gate per attempt. A subject
  that could re-start a gate after an unfavourable result could paper over
  the first attempt with a second, more favourable one; refusing a second
  start removes that path structurally rather than relying on a later reader
  to notice two records for one gate.

`gate_complete` is refused when:
- `invocation_id` does not match a gate that is currently in the OPEN state
  (started, not yet completed) for this attempt. This is what makes "a
  received request alone is not completion" (#269's own acceptance wording)
  true structurally: completion credit requires a request the controller
  ITSELF already opened by a genuine, declared `gate_start` — a bare
  `gate_complete` with nothing open to pair it to (a forged local receipt
  replayed through the channel, or a `gate_complete` for a gate the
  controller never started) has no open invocation to satisfy and is
  refused, never silently recorded as a loose fact.
- the matched gate's invocation is already CLOSED (a second `gate_complete`
  for the same, already-completed invocation) — a replay of an earlier,
  genuine completion cannot be used to overwrite it.

Both refusal families are mutation-checked (§8): remove the specific check
and show the specific red case the check exists for goes undetected.

## 5. Coverage states and `execution_observed` (corrections from review)

Four coverage states per declared gate, named so they never collide with
#183's own `TrustedLog` vocabulary (review correction — an earlier draft used
"unavailable" for two different facts):

| Coverage | Meaning |
|---|---|
| `complete` | a START and its matching COMPLETE are both logged |
| `interrupted` | a START is logged; no matching COMPLETE ever arrived before the attempt ended |
| `not-observed` | the channel was up and reachable for this attempt, but no `gate_start` for this declared gate ever arrived (bypass, or the gate was simply skipped) |
| `channel-unavailable` | the channel itself could not be constructed/was unreachable for this whole attempt — distinct from `not-observed`: here nothing could have been witnessed at all, not merely nothing was heard |

**Correction (review): exit code is not execution.** `execution_observed`
asks "did the gate execute", never "did it succeed" — conflating the two is
exactly the separation `records.md`'s "Three facts that are not compliance"
section (item 2) exists to keep. So:

- `execution_observed: CONFIRMED` for coverage `complete` OR `interrupted` —
  both mean the controller witnessed the gate genuinely START, independent
  of whether it ever finished or what it returned. A gate that started and
  was killed mid-run was still, honestly, witnessed starting; "did it
  finish" and "what did it return" are the separate `coverage` and
  `exit_code` facts, never folded into `execution_observed` itself.
- `execution_observed: UNKNOWN` (reason `no-controller-witness` for
  `not-observed`, reason `channel-unavailable` for that coverage) — the
  controller has no positive fact either way.
- **`execution_observed: NOT_CONFIRMED` is never produced by this witness**
  (decision, orchestrator ruling, final — not left as an open question).
  With the channel up, zero requests for a declared gate is consistent with
  "skipped" AND with "ran outside the channel entirely" - the controller
  cannot distinguish those from silence alone, so asserting POSITIVE
  non-execution would be a guess dressed as a fact. `records.md`'s own
  three-state vocabulary keeps `NOT_CONFIRMED` available for some future
  evidence kind that can actually produce it; this one structurally cannot.

## 6. Tree identity: controller-computed, never subject-claimed

**The question this design must answer (review): what does "a request
naming a different tree cannot satisfy observed execution" (#269's
acceptance) actually mean, given a subject legitimately edits the workspace
between gates?**

A subject-CLAIMED tree digest, checked by the controller against anything,
fails on both counts at once: refusing a mismatch would refuse every HONEST
gate run after the subject's first edit (the tree is SUPPOSED to change), and
a subject-supplied digest is itself subject-writable - checking it against
anything proves only that the subject can compute a hash, never that the
hash describes the tree that actually existed.

**The resolution: the controller computes the tree identity ITSELF, at
`gate_start` time, by reading the workspace through the same read-only,
safe-to-call-more-than-once channel `AuthorityInterceptor`/`DisruptionTrigger`
already poll (`ExecutionBackend.export()`) - never from anything the request
carries.** `tree_digest_at_start` in §2's record is this self-computed value,
recorded unconditionally, never compared or refused against anything AT
DECIDE TIME. The comparison this design's acceptance wording is actually
asking for happens LATER, outside this witness: a grader consuming this
record checks `tree_digest_at_start` against the digest of the tree it is
actually grading (the final exported tree, hashed the same way) and decides
FOR ITSELF whether a gate that ran against a now-superseded tree should count
toward whatever it is judging. This witness's own job stops at recording an
honest, controller-computed fact; the grading decision belongs to #270/#271.

**What is owed, not shipped here.** `tree_digest_fn` (the callable this
module calls at `gate_start`, injected by whoever constructs the witness,
exactly as `DockerBackend.trigger_decide` is injected into
`DecideReplyChannel`) is BACKED, in production, by a real `backend.export()`
call plus a deterministic whole-tree hash (sorted relative paths, each file's
content digest, combined). This module is tested against a FAKE
`tree_digest_fn` (a stub returning a fixed or deliberately-changing string),
proving the PAIRING/refusal/coverage logic independent of tree hashing.
Whether a REAL `export()` against a REAL daemon produces a stable, correctly
timed digest at `gate_start` time is a live-Docker question this design does
not simulate - named as owed, the same discipline #183's own §2f(c) and live
test already use for a daemon-dependent claim this environment cannot run.

## 7. Citation into `skill-evidence` — no new mechanism

`records.md`'s own "Trust boundary needed by #269" section (already merged,
in #268) fully specifies this: the finalized `gate-witness` record is
captured as an ordinary `artifact-manifest.artifacts` entry (`type:
"gate-witness"`, matching the record's own `kind`), and
`skill-evidence.lifecycle.execution_observed.evidence` cites that entry by
`{ref, digest}` - the identical check that already refuses a `verified-result`
citing an uncaptured digest. Two committed bad-case controls already enforce
the citation requirement today
(`execution-observed-confirmed-no-witness.json`,
`execution-observed-not-confirmed-no-witness.json`), mutation-checked,
independent of whether this module exists yet. This design adds no new
citation mechanism - only the record this one now names.

## 8. Red cases (mutation-checked)

1. **Undeclared gate.** `gate_start` naming a gate not in `declared_gates` -
   refused. Mutation: remove the declared-set check, confirm an undeclared
   gate is silently admitted.
2. **Duplicate start.** A second `gate_start` for an already-started
   (whether or not completed) gate - refused. Mutation: remove the
   already-started check, confirm a second, more favourable start silently
   overwrites the first.
3. **Orphan completion (forged/replayed).** `gate_complete` with no matching
   OPEN start - refused, whether the `invocation_id` names a gate never
   started, a gate already completed (replay), or is simply unknown.
   Mutation: remove the open-invocation check, confirm a bare completion
   with nothing behind it is accepted.
4. **Interrupted coverage.** A genuine `gate_start`, no `gate_complete`
   before the attempt ends - reports `coverage: "interrupted"`,
   `execution_observed: CONFIRMED`, never `complete` and never `UNKNOWN`.
   Mutation: confirm the coverage computation actually distinguishes this
   from both `complete` and `not-observed` (collapsing any two of the three
   is the class of bug this case exists to catch).
5. **Full bypass.** A declared gate the subject never contacts the channel
   about at all - `not-observed`, `execution_observed: UNKNOWN` reason
   `no-controller-witness`, never `NOT_CONFIRMED`. This is the same
   structural guarantee #183's own bypass red case established for the
   disruption trigger, applied here to gate execution instead.

## 9. What #270/#271 may build on

- The finalized record's shape (§2) and its four coverage states (§5) -
  #270/#271 are free to add their OWN criteria logic consuming
  `execution_observed`/`coverage`/`exit_code` per gate; this design commits
  only to what the witness itself may honestly report.
- The tree-identity comparison described but not performed in §6 - a grader
  that wants to refuse crediting a gate run against a stale tree does the
  comparison itself, against this record's `tree_digest_at_start`.
- The citation shape (§7) is already fixed by `records.md`; nothing here
  changes it.
