# Integration, reporting and verification contracts

- Status: Planning specification; the executable record forms for all four contracts are in [records.md](records.md)
- Date: 2026-09-20
- Governing documents: [specification](spec.md), [protocol](protocol.md)
- Research: [pinned Coder Eval handoff](../../research/coder-eval-skillc-contract-handoff-2026-09-20.md)

## Contract ownership

A skills collection need not implement an API or change its repository. A subject
adapter connects its native installation to a client in a disposable environment.
The evaluator owns the contracts below regardless of the selected execution backend.

| Contract | Producer | Required output | Independent check |
|---|---|---|---|
| Installation receipt | Subject adapter, checked by controller | Subject revision/digest, selected native surface, adapter/client versions, effective instruction/configuration layers, dependencies, installed paths/digests, allowed writes and readiness evidence | Expected nonempty surface exists and a client-specific discovery canary works; baseline proves subject absence |
| Trial ledger | Controller | Experiment/trial/attempt IDs, expected population, task/grader/image/config identities, budgets, lifecycle, termination and cleanup observations | Every planned attempt remains accounted for; reruns receive new IDs; configuration matches the declared comparison |
| Artifact and observation bundle | Controller-owned capture | Frozen output manifest with path/type/size/content digests, raw client records/events, origin and coverage metadata, redactions and capture failures | Bind to the ledger and actual attempt; reject escapes, mismatched identities, stale records and changed content |
| Verified result | Independent verifier and controller result assembler | Criterion outcomes/evidence references, grader/control identities, artifact digest, overall protocol label and explicit missing evidence | Protected grader distinguishes correct/incorrect outcomes; the assembler derives status rather than copying a subject-authored success flag |

These contracts define semantics, not a required network service, SDK, serialization
format or upstream schema. A versioned local envelope can wrap an upstream record
while preserving its raw bytes for inspection. Incompatible versions, missing
required identities, duplicate/conflicting IDs and unknown authoritative verdicts
are explicit validation failures, never verified success.

## Installation and execution lifecycle

1. Describe supported layouts, installation modes, clients and observation limits.
2. Resolve immutable inputs and the permitted configuration before preparation.
3. Prepare only in allocated workspace/home locations; record setup and failures.
4. Verify the native installation, dependency closure and clean baseline. A file
   count, checkout path or adapter boolean alone cannot prove a usable install.
5. Execute the public goal under declared tool, interaction and resource limits.
6. Stop the subject and confirm owned processes are no longer modifying output.
7. Capture artifacts and observations into controller-owned storage.
8. Verify in a fresh environment using a disposable copy and trusted grader inputs.
9. Retain evidence and cleanup diagnostics; clean only owned resources, including
   after partial setup, cancellation and repeated cleanup requests. **Every way
   an attempt can end, which disposition each earns, and the test proving it,
   is [the failure-path matrix](failure-matrix.md) (#79)** - state it there
   rather than leaving "the matrix" implicit.

Discovery, availability, invocation and task success are four different facts.
If a client cannot expose invocation, report unknown. Do not silently substitute
pasted instructions when native installation fails. Prompt treatments are valid
separate experiments and must be labelled accordingly. Symlink staging requires
immutable accessible targets, collision checks and a recorded dependency closure.

## Execution backend

This document has always required a "selected execution backend" without
defining one. `skillc/backend.py` (#10) does: an `ExecutionBackend` is the
stdlib `Protocol` that owns steps 3 through 7's process side and step 9's
teardown - it prepares a workspace/home inside its own isolation, starts a
skill's installation and the agent under test inside that isolation, and can
be asked, independently of what it reported while running, whether its work
actually stopped and whether nothing of it remains.

| Step above | Backend method | Note |
|---|---|---|
| 1 | `describe()` | Identity, isolation claims, and - required, not optional - what it does NOT establish |
| 2 | *(controller: `trial.plan`)* | Not a backend concern |
| 3 | `prepare(attempt_id)` | Returns an opaque handle; raises `BackendUnavailable` rather than a handle it cannot back |
| 4 | `install(handle, surface)` | The skill starts inside the isolation, never staged on the host and copied in |
| 5 | `execute(handle, argv, limits, cancel)` | The agent under test starts inside the isolation |
| 6 | `confirm_stopped(handle)` | Queried FROM the backend - never inferred from `execute()`'s own exit or timeout. Returns a `Confirmation` (`CONFIRMED` / `NOT_CONFIRMED` / `UNKNOWN`), never a bare bool - a backend that cannot observe returns `UNKNOWN`, never a guess, and `UNKNOWN` is never treated as a confirmed stop |
| 7 | `export(handle, dest)` | Copies out; the CONTROLLER re-hashes and freezes on its own side (`trial.capture`), so a backend cannot forge what was frozen. Must be safe to call more than once, without mutating its own state: the lifecycle driver exports once before `execute()` and once after, and refuses a capture identical to the pre-execution state - see "Liveness" below |
| 8 | *(a separate backend instance, same seam)* | See below |
| 9 | `destroy(handle)` + `confirm_absent(handle)` | Both idempotent; `confirm_absent` returns the same three-way `Confirmation` and never trusts `destroy()`'s own return, for the same reason `confirm_stopped` never trusts `execute()`'s |

**Step 8 is not a special case.** `skillc/verify.py`'s probe (#9) is planned to
run through its own instance of this same seam (#10's PR2), so the isolation a
backend provides for an agent under test and the isolation it provides for
untrusted candidate code during grading are the same property, established
once. That join is PR2's delivery, not this section's.

**An unavailable backend is a refusal, never a reason to run on the host.** A
caller that cannot `prepare()` declares the attempt through
`trial.finalize(experiment, attempt_id, disposition="unavailable", reason=...)`
- already-existing controller machinery, unchanged by this seam - and never
constructs a host `subprocess` argv as a fallback. No method on the Protocol
has a documented failure mode of "try the host instead."

**A raising `prepare()` owns its own cleanup.** It returns no handle on that
path, and `destroy()`/`confirm_absent()` both require one - a caller has no
other way to reach whatever a failed `prepare()` already allocated. A backend
that creates a container or workspace before it can confirm the isolation is
usable must tear that down itself before raising `BackendUnavailable` or any
other exception, never leave it for a handle nobody received.

**skillc will ship its own Docker-backed implementation** (a later #10 PR - it
does not exist at this commit), and that backend will be a complete,
standalone answer to #10: skillc depends on no other system to demonstrate
the full lifecycle. The seam exists so ANOTHER backend - a different
isolation technology, or one supplied by a larger system this skillc instance
happens to run inside - can implement the same contract later. Nothing in
`skillc/backend.py`, or anywhere else in this package, imports, calls, names
or assumes such a system; a backend is exactly the Protocol's methods and
`describe()`'s claims, never more.

**Neutral identity is a backend obligation** (operator rule: skillc is
public, so no hostnames, usernames, uids, home paths, IPs or internal URLs in
anything committed, reported or graded). Every backend must present a fixed,
non-host identity inside its isolation - a fixed unprivileged user/uid (e.g.
`candidate`), a fixed hostname-style value, fixed logical paths (e.g.
`/work`, `/home/candidate`) - and report only those logical values from
`describe()`, from `install()`/`execute()`'s return values, and from
`str(handle)`. A per-attempt name (a container name or equivalent) derives
from the attempt ID alone. The controller does the same on its own side: a
host-side location (the evidence store, an export destination) is recorded
relative or logical in anything that could be committed or pasted into a
public issue, never as an absolute host path.

**Liveness is a lifecycle requirement, not a Docker one.** A subject that
starts, does nothing, and exits 0 looks identical to one that never ran, and
identical to one that ran and succeeded, using exit code alone. Measured
concretely on a sibling platform: a Claude Code container wedged on a first-run
prompt, and a Codex container missing its tool-call sidecar, both reported
`exit 0` while doing zero work, invisible to a healthy-looking container.
"Exit 0 plus plausible output" must never reach grading as `captured`.

`skillc/lifecycle.py`'s driver (#10, PR1b) establishes liveness generically,
without depending on any client's transcript format: it calls `export()`
once right after `install()` (before `execute()` runs anything) and once
after, and compares the two snapshots by content digest. Identical snapshots
mean nothing observable happened, whatever the exit code says, and the
attempt is finalized `inconclusive` with a `liveness` reason - never
`captured`. A fake client that exits 0 having done nothing is the committed
negative control for this check (`tests/fixtures/backend-lifecycle/fake_client.py`, driven through `tests/test_lifecycle.py`'s `FakeBackend`).

## Reporting semantics

Candidate code, final prose and optional structured claims are submissions. They
are not authoritative trial records. Do not require every skill to emit special
JSON. Adapters can collect normal client output; missing prose only fails a case
when reporting is a declared requirement.

Each mandatory criterion reports SATISFIED, VIOLATED or UNKNOWN, with the public
requirement, check/grader revision, evidence and explanation. The assembler uses
the protocol's PASS/FAIL/UNAVAILABLE/INCONCLUSIVE/NOT_RUN semantics. An established
mandatory violation remains FAIL when another criterion is unknown. Otherwise,
missing mandatory evidence prevents PASS. Optional quality scores cannot average
away mandatory failures.

Preserve evidence origin: externally observed process events, client reports and
model-authored assertions differ. Capturing a statement faithfully does not prove
that statement true. Record unsupported or incomplete event coverage explicitly,
including nested workers and costs incurred outside the observed client.

Claims can be SUPPORTED, CONTRADICTED or UNVERIFIABLE. A reproduced missing record
contradicts "all records preserved"; an unobserved review is unverifiable. These
labels describe evidence, not intent to deceive. A malformed evaluator record is
a measurement failure; a malformed candidate submission is a task failure only
when it violates the case contract.

## What validates truthfulness

- Structure checks establish that fields are well formed and consistent.
- Protected provenance binds observations and artifacts to their producer and
  attempt. A digest verifies bytes against a trusted reference, not their truth.
- Independent outcome checks test behavior against public acceptance, using held-out
  inputs that do not introduce secret requirements.
- Process checks require sufficient event coverage to establish ordering and
  authority. Missing events cannot prove a forbidden action never happened.
- Known-good/bad controls and deliberate grader faults test the evaluator itself.

Authoritative grader definitions and result assembly stay outside the subject's
writable environment. Candidate code executed during grading remains untrusted:
its process cannot overwrite the verifier's success channel or access evaluator
credentials. A separate container alone does not demonstrate this property.
Model judges require calibration and adversarial controls; submitted artifacts
must not become grader instructions. Start with deterministic outcome checks.

The controller host, collectors and grader remain part of the trusted system.
Hashes in a subject-writable folder do not authenticate that system. Signatures
may later help across administrative boundaries; they cannot make a signed false
claim true. Retained evidence supports inspection within these stated limits.

## Conformance cases required before trusting a backend

| Case | Expected evidence | Requirement |
|---|---|---|
| CPP and a second collection | Same engine, result contract and grader; only preparation differs | EF-01 |
| Missing required skill/helper or baseline contamination | Readiness refused; no empty-population pass | EF-03 |
| Out-of-root write, symlink escape or repeated cleanup | Original source/host preserved; only trial-owned resources affected | EF-02, EF-10 |
| Incorrect output with forged success prose/JSON | Independent task failure; contradicted completion claim where asserted | EF-04, EF-08 |
| Agent replaces local tests, checker or pass file | Authoritative grading remains unaffected | EF-05, EF-08 |
| Candidate code writes verifier outputs | Cannot produce forged authoritative success | EF-05, EF-08 |
| Stale/cross-trial receipt, altered artifact or missing required digest | Evidence rejected; no verified pass | EF-07, EF-08 |
| Missing events, truncated output or unavailable provider | Explicit coverage/failure cause; no inference from silence | EF-07 |
| Always-pass, always-fail, crashed or silent grader | Control gate refuses certification | EF-05 |
| Frozen output regraded by the same deterministic grader | Same criterion outcomes in a new linked result; original retained | EF-05, EF-08 |

Regrading fixed output and rerunning an agent are different operations. Stochastic
judges may disagree on replay; preserve configuration and disagreements rather
than promise deterministic results.

**Each case above is restated, per backend, with a demonstrated/owed status
and a concrete citation, in [the support matrix](support-matrix.md) (#80)** -
never left as an unaddressed claim in this table alone.

## External runtimes

skillc depends on no external evaluation runtime
([ADR 0003](../../decisions/0003-no-external-evaluation-runtime.md)). The contracts
above are implemented by skillc's own controller, capture and verifier (#8, #9,
#10). Coder Eval and Harbor remain design references; the
[lessons and contract map](../../research/coder-eval-lessons.md) records what the
pinned static reading of Coder Eval showed, including the traps these contracts
exist to refuse: container-authored results, contract echo and stdout framing as
authentication, and missing digests that warn and proceed. No Coder Eval trial or
forgery attempt has been performed.
