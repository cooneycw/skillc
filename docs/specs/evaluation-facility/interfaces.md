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
   after partial setup, cancellation and repeated cleanup requests.

Discovery, availability, invocation and task success are four different facts.
If a client cannot expose invocation, report unknown. Do not silently substitute
pasted instructions when native installation fails. Prompt treatments are valid
separate experiments and must be labelled accordingly. Symlink staging requires
immutable accessible targets, collision checks and a recorded dependency closure.

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
