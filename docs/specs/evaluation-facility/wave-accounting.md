# Bounded wave accounting and sizing (Refs #624, PR-N1)

This slice supplies pure readers/projections over authored or retained numeric
captures. It reads no client home, raw transcript, credential or host resource,
launches no work and enforces no model-token limit. The native usage collector,
actual subscription concurrency and final study sizing remain separate work.

## Capture contract

`wave_usage.Context` binds the wave, whole declaration digest, original deadline
digest/duration, common clock domain, pinned client version and exact ordered
role/session/turn population. A planned nonstart has a null expected session;
it stays in that population, and no raw counter claim can make its usage complete.
Distinctness applies to observed session IDs; several nonstarts may be null.
Each role has one planned `initial` turn followed by its
expected controller poke nonces. The caller obtains those identities from its
independently retained launch/wake evidence, not the usage document. A poke
attempt is not proof of a model turn or any token consumption. Missing or
unconfirmed coverage cannot become a measured zero.

`Reference` independently binds the context digest, SHA256 and exact byte size.
`reference(raw, context)` only computes a consistency receipt: the trusted caller
must retain its provenance separately through its own evidence contract. Neither
this factory nor a parsed context issues approval. `evaluate(raw, ref, context)`
checks byte integrity before interpreting the capture; a public report or a
mutable checkpoint cannot select its own expected digest. This API accepts bytes,
not a path, and supplies no filesystem collector or durable writer.

The closed capture object has exactly version 1, wave/declaration/deadline/clock/
client bindings, `counter_format: cumulative-session-total-v1`, a role list and
nullable `completion_elapsed`. Each role has role/session identity and exactly
its expected ordered turns. Each turn has `turn_id`, `started_at`, `ended_at`
and a nonempty list of cumulative session-total token samples. This is a numeric
capture format, not a claim that an arbitrary client transcript matches it.
Client-specific collection/counter semantics must be qualified separately.

Counters are bounded nonboolean integers. Repeated cumulative values are allowed;
only the final validated counter per continuous session contributes. Samples
are never summed. A decrease/reset or ambiguous/missing turn makes that role
UNKNOWN. The caller must not invent reset epochs or treat overlapping transcript
copies as distinct sessions. Tokens from different roles are summed once only
with complete coverage. Otherwise `tokens` is null, and a known subtotal plus
known/planned role counts retains partial information. No observed roles means
subtotal null, not an invented zero. Population order, duplicate roles/turns,
changed sessions, unknown fields, malformed/duplicate/deep JSON and custody loss
cannot yield complete coverage.

Even when bytes, receipt or their hash are unavailable, a valid independently
held context supplies the full planned denominator, role/session rows and each
role's planned turn count. Their measured counters, times and observed turn
counts stay null. An invalid context cannot supply trusted metadata. No placeholder
session UUID or measured zero is invented for a nonstart.

Role active seconds sum all its turn intervals, including resumes. Session
elapsed spans its first start through last end. Whole-wave wall seconds comes
from the original common-clock completion observation, including cleanup, not
the sum of parallel role durations. Missing completion remains null even when
all token counters are known. Late completion is reported against the original
deadline, never used to extend it. Times are finite nonboolean nonnegative values;
role intervals cannot overlap or run backwards, and completion cannot precede a
known turn end. Missing role evidence is conservatively unavailable for both its
time and token metrics.

Representation bounds are 8 MiB per capture, 1..64 roles, 1..65 turns per role,
32768 samples per role and 2^63-1 per counter/aggregate. These are technical bounds,
not selected study budgets. The three-role fixtures are synthetic. Reports always
carry `admission_authority: false` and `enforcement_authority: false` and label
usage `client-reported-not-provider-attested`. Integrity authenticates custody,
not the truth of participant-writable client counters or provider billing.

## Additive planning APIs

`wave_planning.bind_plan(declaration, approved_digest)` binds canonical WHOLE
caller declaration bytes to an independently held approved digest. It verifies
the explicit existing `nhl_limits` mode and the new closed `wave_accounting`
sizing object; other declaration validation/approval remains the caller's job.
There is no automatic calibration/live launch integration. New APIs do not
rewrite historical declarations, scalar estimates, overhead exemptions or
existing reports. Callers must validate the rest of their declaration normally.

`wave_accounting` has version 1, sizing_report_digest, nonempty exact role plans,
critical_path_seconds, setup_seconds, capture_seconds and cleanup_seconds. A role
plan supplies role, initial/resume input/output token assumptions, resumed_turns,
initial_seconds and resume_seconds. Every field is explicit; missing sizing
refuses. The resumed count is 0..64, tokens are bounded integers, and time values
are finite. Initial estimates are positive; resume estimates may be zero only
when no resumed turn is planned. Expected turn counts are assumptions, not actual
usage, authorization to poke or token caps. If capped metadata is retained, its
sizing digest must match the wave sizing source.

The owner-sized critical path must cover every individual role's active allowance;
setup/capture/cleanup add to its wall allowance. That is a consistency floor, not
proof that the declared dependencies or physical machine fit it. A three-role
wall allowance is neither guessed from one role nor automatically obtained by
adding parallel execution durations. `schedule_budget.wave_refusal_reason` is an
additive seam using these wave allowances; the old scalar 16-second observation
is not a measured overhead for this new wave model. Ordinary finite operational
deadlines remain required.

`cost_estimate.estimate_wave` projects every role's initial and expected resumed
turns. It delegates the resulting per-wave input/output totals to the existing
cost estimator once per planned wave. Judge tiers remain per wave, not per role.
The existing subscription usage/quota-versus-paid-judge distinction and dollar
authorization remain unchanged. Estimates are not measurements or enforcement.

Uncapped measurements may exceed projections and remain observations; no token
stopper is installed. Capped metadata may be projected, but the unchanged
`nhl_limits.require_for_execution` still refuses capped dispatch until separately
approved sizing and actual aggregate enforcement exist. No missing owner mode,
sizing, enforcement or credential authority is supplied by this slice.

## Qualification and limits

Committed field-level sweeps cover context/role/turn/ref, capture and sizing
boundaries, with healthy twins. Missing third-role/resume evidence, resets,
wrong bindings, malformed numbers/JSON and actual byte changes remain UNKNOWN.
Actual compiled cumulative-sum, always-complete, hash-blind, summed-parallel-wall
and flat-single-role-cost variants must lose their committed witnesses. These
qualify NEW instruments; absent APIs on old main are not regression reds.

No physical usage, VM headroom or credential-window observation is claimed.
The owner clarification about accepting client-reported usage for uncapped
sizing remains separate; this code never upgrades that source to provider truth.
CPU/memory declaration inputs follow in PR-N2. Credential/steward/container-auth
wiring is deferred to a separate SECRET-PATH PR after the unapproved #630 contracts
exist. Its text-only design is retained on #624. The native three-session probe
remains folded into #639's separately approved sizing run.
