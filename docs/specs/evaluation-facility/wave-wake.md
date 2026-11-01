# Arm-neutral controller turns (#622)

`skillc.wave_wake.drive(wave, policy)` runs #621's owned role sessions under one
immutable `WakePolicy`. It supplies controller resume turns, not native thread
wake, mail acknowledgement or task grading. No model invocation is authorized
by this API. A live caller must bind the policy object/digest into its approved
run declaration. There is no arm or CPP-mailbox argument.

## Observation and triggering

The controller sends fixed `wave_snapshot.py` source to its own fixture helper,
as an isolated root Python process. It observes only the declared shared wave
volume and bare fixture git remote. Agent processes never supply revisions.
The observer hashes relative paths, entry types/modes and raw file bytes, plus
canonical git refs. It does not decode mail or inspect message meaning. Links
are hashed as links and never followed; missing, unsupported, over-budget or
racing reads are unavailable observations rather than empty revisions.

A revision contains both file and ref digests. Any change is potential shared
work for every idle role whose own watermark predates it. The driver does not
infer which role a message addresses. This intentional broadcast rule is the
same for plain-file and CPP arms. CPP-specific state can be retained separately
as a diagnostic, but is not queried as a wake condition.

When an exec turn is first seen as finished, its watermark is the PREVIOUS
controller revision, observed before completion was seen. The new sample can
therefore never absorb a sibling write made after that turn returned but before
the controller next polled. This conservative fence can cause an extra recorded
poke for activity late in a running turn; it cannot silently discard the
post-turn activity as already consumed. Futures finishing during the current
sample are handled at the next poll against its previous revision.

Observation is polling, not a transactional filesystem journal: changes that
appear and disappear entirely between samples are outside its coverage, and a
digest can combine individually stable reads from a concurrently active tree.
The fence is explicit rather than an assertion of atomic timing at the client's
last instruction.

## Declared policy and fencing

The literal, poll interval, spacing, poke cap, failure/cap behavior and observation
bounds are included in the canonical policy digest and wake declaration. Clean
turns wait for a changed revision. Nonzero/timed-out turns stop. A completed last
allowed poke ends its role; no more than 64 pokes per role are accepted by this
version. Unconfirmed transport consumes that observed revision and waits for a
new change or the original deadline. Snapshot loss retries within that same
endpoint, coalescing unavailable observations in the journal.

Every offer binds role, header-derived session, observed revision and a fresh
controller nonce. Immediately before dispatch the controller re-observes the
shared revision, session, explicit idle state and independent container liveness.
Unknown/blank observations are not idle/live. A stale or wrong target is refused
and recorded. `DockerWave.turn(expected_session=...)` checks the session again
under the role lock, closing the queue-to-execution window. A blocking in-turn
watch remains running and receives no poke.

The controller delivers the measured argv shape through the existing backend:
`[*base_argv, "resume", session_id, policy.literal]`. Fixed per-case resumed
turns and dynamic wake policy cannot both own the same role. One driver owns a
wave; replay into an already driven/closed wave is refused.

## Evidence and count contract

`wake-declaration.json` binds the attempt, role population and literal policy.
`wake-events.json` is updated at each controller transition, including before
an attempted delivery. `wake-report.json` joins each attempt's revision, time,
session and nonce to its resulting turn exit, or an explicit refusal/unconfirmed
result. A poke is an ATTEMPT; neither a zero exit nor the count proves receipt
of any mail.

For #620 the report has exactly this per-role projection in `poke_counts`:

```json
{"role": "worker-a", "session_id": null, "pokes": null}
```

`session_id` is a string when observed, otherwise null. `pokes` is a nonnegative
integer only for an observed compatible session binding. Missing/incompatible
binding produces null, never an inferred zero. A known count, including observed
zero, stays concrete even when a separate controller journal/publication error
makes the driver outcome UNKNOWN. A suppressed transport still counts as an
attempt. Null is reserved for an already unobserved or incompatible role binding;
it is not a routine fallback for otherwise observed roles.

Counts are separate from task-achievement criteria and mailbox acknowledgements,
but their evidence is mandatory completeness for #620. A missing row or null
count/session binding makes that whole wave's evidence UNKNOWN. Describing counts
as diagnostic does not make missing count evidence optional.

### Runtime session binding phase

The caller predeclares role population, attempts, task pins/criteria and task
generation/revision/nonce before launch. Those facts do not change when session
IDs become available. The initial exec's controller-captured header is the
authority for the runtime session ID. With the current backend, that header is
parsed when the first exec result returns; until then the binding is unobserved.
Raw controller events may buffer during that turn. Finalize the header binding
before accepting/attributing them in the offline wave verdict, and keep that
initial binding immutable across resumes. Participant prose never supplies it.

The existing #621 `roles[role].session_id` capture and the wake report's
`poke_counts` projection provide this handoff; no new artifact name is required.
Retain every planned role when binding is unavailable so its null remains
explicit rather than disappearing from the population. Per-poke nonces in the
wake journal are separate from the caller's predeclared task nonce.

The driver reports `STOPPED`, `DEADLINE` or `UNKNOWN`, never task PASS. STOPPED
means its declared role policies ended, including caps or failures. Task results
belong to the independent wave verdict. The original wave completion endpoint
covers roles and capture/cleanup; unavailable cleanup cannot become a clean
driver outcome. Final decision emission is after cleanup observation.

## Model-free evidence and limits

Committed conditions live in `controls/wave-wake/`. The focused tests use trusted
scripted controller doubles, actual file-byte changes and git fixture refs; they
also execute the exact isolated observer source and test the actual DockerWave
session fence. Plain-file and CPP-diagnostic arms receive identical pokes for
identical activity. Suppressed delivery reaches the declared endpoint; stale
sessions, wrong roles, unknown liveness, caps and failed publications are
recorded/refused. These tests make no physical-daemon or native wake claim.

The conditions adopt the design identified in #622 from
`core/mailbox_wake.py:77,131,205` at source revision
`4021172f70d9cfab533f82987159d82447fc644c`: explicit idle/live evidence,
watermarks, spacing, supersession fencing, and attempt-versus-receipt accounting.
No source text was copied and no runtime imports or dependencies were added
from that repository. Its native wake route remains a later phase.
