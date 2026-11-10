# Offline assembly of controller-held wave captures (Refs #620)

This infrastructure slice joins the existing offline verdict to held byte
inventories, complete-wave export integrity, final shared/remote custody and
verified controller poke counts. It supplies no launcher, role protocol,
runtime policy, clutter lifecycle hook, native wake or live authority. Today's
runtime does not produce every required observation. A missing producer remains
UNKNOWN; the healthy controls use **authored protocol fixture bytes** and do not
qualify an existing live semantic producer.

## Separate original plan and capture expectations

`live_wave_assembly.freeze_plan(value)` returns a frozen `Planned` byte snapshot.
The trusted caller retains it **before observation**, separately from captures
and reports. Its closed object contains version 1, `declaration_digest`, and a
nonempty ordered `waves` list. Each wave has `plan`, `budget_digest`, `clock` and
`grader_digest`.

`plan` follows `live_wave.WavePlan`: wave ID, complete role list, integrator and
common deadline. Each role binds its role/attempt/session, task, generation,
revision, nonce and required artifact paths. A planned nonstart can have no
session. The caller owns initial session binding and the task/grader contract;
this module cannot authenticate those choices. Clock kind is `monotonic` or
`injected-policy-only`; the budget digest names the original deadline domain.
No clock or deadline is restarted during replay.

After capture, `freeze(value, exported, planned)` accepts the separately held
`wave_export.FrozenExport` and original `Planned`. The complete plan, grader and
clock projection must exactly match that original snapshot. Wave IDs/order and
roles must also match the export's original population; declaration digests
agree. Canonical immutable bytes prevent later input aliases from changing the
plan or expectations. Bad frozen contracts refuse with `AssemblyRefused` rather
than inventing a denominator. The reader does not approve a plan or prove when
its caller froze it.

The capture object repeats the original fields and adds each wave's
`observation`, `roles`, `wake` and `final`. Absence is explicitly null. Every
role capture row has `role`, `startup`, `observation`, `transcript`, `protocol`
and `artifacts`. A byte reference has exactly `slot`, `path`, `sha256` and `size`.
The slot must belong to that wave and the correct role/kind in the held export
manifest; its path, size and digest must match the catalogue entry and the
actual bounded bytes. Artifact maps bind logical artifact paths to references.
These expectations must come from the controller, never an arriving listing.

## Producer inputs and unavailable coverage

| Input | Existing producer and assembler contract |
|---|---|
| Startup | Captured controller-drained stderr, joined as the role's `stderr` slot; parse the strict initial client header and compare with the held role observation and planned session. |
| Transcript | The role's captured, hashed `transcript` slot; complete newline-terminated JSONL, consistent session metadata. The caller must establish coverage and normalize multiple rollout fragments without cherry-picking. |
| Role observation | Held `role-report` bytes with exact wave/role/attempt/session, budget and clock bindings, lifecycle flags, capture completeness, stop cause/code/time and optional usage/duration. This normalized contract is a caller responsibility; current Docker runtime JSON is not automatically this record. |
| Protocol | Explicit `protocol` slot containing complete bounded controller-observed ack/complete JSONL. No such live producer is supplied here. Final mailbox bytes, a poke, an idle turn or agent prose cannot replace it. |
| Artifacts | Explicit role `artifact` slots, original required paths and exact retained bytes. Export integrity is custody, not correctness; the independent grader reads the captured bytes for every role. |
| Wave observation | Held `wave-report` bytes with original budget/clock, capture/cleanup completion, infrastructure/deadline witnesses and optional abandonment. Its captured `status` is ignored when deciding task outcome. |
| Wake counts | `wave_wake_capture.poke_counts` over the real sealed byte store, separately held Reference and Context; all role/session, declaration, original wave/budget/clock joins must agree. Missing or corrupt custody gives unavailable counts, never zeros. |
| Final shared/remote | `wave_capture.verify` against the separately held manifest SHA256; both original surfaces and confirmed-writer capture remain required. Final custody does not prove earlier revisions or semantic acknowledgements. |
| Tokens/wall | Explicit optional controller-held observations only. Null stays null. No total is inferred from text, file times or repeated cumulative resume counters; current generic runtime does not provide a complete role-duration producer. |

Role observation fields are version, wave ID, budget digest, clock, role,
attempt/session IDs, `started`, `stopped`, `cleanup_confirmed`,
`capture_complete`, `stop_reason`, `exit_code`, `stop_elapsed`, `tokens` and
`wall_seconds`. Completeness is the trusted producer's complete-stream/census
attestation, including startup drain flags, and is additionally constrained by
the assembler's actual inputs and stream validation. Export success alone
cannot set it true. An unavailable observation omits that role's usable evidence
while preserving its planned diagnostic row.

Wave observation fields are version, wave ID, budget digest, clock, captured
projection `status`, `completion_elapsed`, `cleanup_confirmed`,
`infrastructure_failed_at`, `deadline_witnessed_at` and `abandonment`. A normal
wave can have no failure/deadline witness. A per-turn timeout is not inferred to
be the common task deadline. Missing infrastructure time cannot turn an
infrastructure cancellation into task failure.

## Read-only assembly and grading

`report(arrival, expected, graders)` reads the existing `manifest.json` plus
`payload/` arrival. It verifies complete-wave export integrity before and after
assembly. Exact per-object digests and role/kind joins protect the consumed
bytes; bounded no-follow reads reject links and special files. Nested wake/final
roots must belong to that wave's captured subtree, with real directory parents.
These reads detect ordinary drift; they are not an atomic filesystem freeze.
The operator retains custody throughout.

`graders` maps original wave IDs to trusted `Grader` bindings: callable, grader
digest, original budget digest and clock kind. A matching digest is a consistency
join, not authentication of arbitrary Python code. The trusted caller pins the
actual implementation. A missing/mismatched binding or failed grader remains
unavailable and cannot erase independently observed protocol violations.

The callable receives the actual complete captured artifact population and
returns the existing `DeliveryGrade`. It must measure its grading endpoint in
the original common clock, including grading work. The kernel takes the maximum
of capture/confirmed-cleanup and grading completion. A later offline invocation
cannot backdate a live PASS. Caller assertions, independent receipts and their
provenance cannot be reconstructed from mutable report JSON.

Every original wave is counted. Missing/nonstart/incomplete waves remain UNKNOWN
unless independent positive task evidence establishes FAIL. The existing kernel
owns task precedence and integration/deadline rules. Export loss prevents PASS
but does not erase independently verified positive violations. A transferred
projection saying PASS cannot supply delivery credit.

Reports retain existing role diagnostics and separate metrics. Detailed #623
handoff timings are explicitly deferred. The #619 production before/settle
census and confirmed-stop delivered-capture join remain absent; clutter stays
null, never invented zero. Missing optional tokens/wall values remain null.
Coverage states that semantic protocol is supplied captured input and live
authority is false. Actual host roots, captured content and exception messages
are not public diagnostics. Logical names/artifact paths are caller-chosen
public data.

## Technical bounds and qualification

Metadata is at most 4 MiB; referenced files at most 8 MiB; payload work uses the
existing 64 MiB export bound. Populations are capped at 256 rows, with the wake
adapter retaining its stricter role/event limits. Protocol streams have at most
256 rows and transcript streams at most 32,768 rows. Names are bounded ASCII
logical identities; relative paths are at most 512 characters/32 components.
Numeric observations are finite nonboolean values within the bounded domain;
deadline is positive and integer counters fit 2^63-1. These are representation
bounds, not study settings, concurrency choices or approved capacities.

`controls/live-wave-assembly/` commits the authored fixture, required-source and
no-inference cases, wrong-type tables and five blind variants. Controls drive
the real export/final-custody verifiers, sealed poke producer/verified adapter,
assembler and existing verdict with a deterministic integration grader. They
include healthy/alternative PASS plus a planned nonstart, valid zero attempts,
unavailable producer UNKNOWN, independently observed violation FAIL, same-size
valid sealed swaps, forged projection, original-plan mutation, grader/clock
mismatch, source drift, nonregular files and planted output-privacy witnesses.

The compiled trust-projection, skip-poke-verifier, arrival-denominator,
complete-without-protocol and missing-to-zero variants lose their committed
witnesses. These qualify a **new instrument**; no absent API on old main counts
as a regression red. Existing verdict/export/wake tests provide preservation
evidence. A synthetic healthy path is not qualification of a live observer.

PR-B's semantic protocol producer and PR-C's healthy clutter lifecycle hooks
remain subject to the outstanding owner ruling. This slice does not complete
the original live acceptance tracked in #620, choose #639 task/run values, remove
#630 authority holds, or authorize #626 physical/model trials.
