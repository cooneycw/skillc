# ADR 0002: Independent, goal-driven evaluation with progressive difficulty

- Status: Accepted as planning direction; backend selection amended by
  [ADR 0003](0003-no-external-evaluation-runtime.md) (no external evaluation runtime); evaluated
  subject widened by [ADR 0004](0004-evaluate-the-exposed-knowledge-surface.md) (exposed knowledge surface)
- Date: 2026-09-20
- Decision owner: Repository owner
- Specification: [Evaluation facility](../specs/evaluation-facility/spec.md)
- Open choices: [Design review](../specs/evaluation-facility/review.md)

## Context

skillc currently checks skill structure and controls its own static rules. Those
checks cannot establish that scaffolding improves an agent's delivery behavior.
CPP motivated the evaluation work, but a CPP-specific runner would make it hard
to compare collections, transfer the measurement to another project or isolate
the effect of scaffolding from the agent and environment.

The owner wants CPP left undisturbed, selected skillc as the home for this work,
and clarified that evaluation layers should be progressively harder task levels.
A goal can organize those tasks, provided acceptance is independently observable.
The owner has asked for planning documents before implementation.

## Decision

Build the proposed facility as an optional capability in skillc, independent of
the subject repository. Separate subject adapters, client/environment execution,
goal-based tasks and graders. CPP is the first adapter, not an assumption inside
the generic runner or an installation dependency of the evaluator.

Use six proposed task-difficulty bands from basic execution to adaptive delivery,
as defined in the specification. Calibrate their placement empirically. Keep
environment readiness and test techniques separate from task difficulty.

Start with a disposable Docker execution lane. Keep authoritative grading and
retained evidence outside the agent's writable workspace. Add other environment
profiles only when the claim requires them; containers do not certify host behavior.

Compare matched configurations with/without a selected scaffold, across revisions
or across collections. Keep a known-bad control distinct from those benefit
comparisons. Report an evidence profile before considering a headline score.

Preserve the static checker as a standalone stdlib-only capability. Use the CPP
small-fix pilot as the first task-family seed and its native Codex surface as the
initial subject target. Finalize exact task/configuration details in delivery
issues. Backend adoption, model/version, paid-run budgets and qualification remain
explicitly unresolved.

Adopt four owned contracts: installation receipt, controller trial ledger,
artifact/observation capture and independently verified results. Evaluate pinned
Coder Eval first as a replaceable execution/measurement backend. Its typed outputs
and contract echo are useful checks, not evidence authentication; the
[interface specification](../specs/evaluation-facility/interfaces.md) defines the
stronger boundary and required conformance cases.

## Alternatives considered

| Alternative | Benefit | Reason not selected as the proposed starting point |
|---|---|---|
| Put the facility directly in CPP | Easy proximity to its workflows | Conflicts with the owner's isolation direction and couples the examiner to one subject |
| Fork CPP and develop the facility there | Separate experimentation | Still makes a subject repository the product foundation; skillc is already the selected home |
| Build a generic runner/platform first | Broad theoretical reuse | Infrastructure work precedes evidence that one meaningful case discriminates |
| Only evaluate whether a skill activates | Small, cheap initial signal | Activation does not establish that the delivered result is correct or better |
| Run prompts without installed workflows | Simple instruction experiments | Useful as a separately labelled ablation, insufficient for installed-product claims |
| Adopt Coder Eval, Harbor or a native runner immediately | Potentially substantial reuse | Needs a bounded compatibility check of grading, evidence and failure semantics before commitment |

The last alternative remains a candidate implementation choice. This ADR selects
boundaries, not a competing runner implementation. Existing systems should be
reused when they demonstrably meet those boundaries.

## Consequences

- A new collection needs a supported adapter and task applicability declaration,
  not a rewrite of the measurement engine.
- Genericity has a concrete proof: two collections through the same runner/grader.
- Goals require fixtures, public acceptance and controlled graders; a prose wish
  alone cannot yield a defensible benchmark score.
- Every attempt, including infrastructure failures, costs evidence and retention.
- Multiple trials increase cost; budget and repeated-trial policy must be explicit.
- A separate examiner reduces accidental coupling but still needs its own redcases
  and review. Isolation alone does not establish evaluator correctness.
- No result can claim broad reliability or benefit beyond its task population,
  environment and tested configuration.

## Decision scope and implementation evidence

On September 20 the owner authorized consolidating the plan, merging the docs and
scaffolding issues. This ADR records that planning direction; it does not assert
that a backend has qualified or authorize spending on trials. Outstanding choices
have owners in the issue sequence rather than blocking documentation delivery.

The first implementation repairs static trust gaps, proves a grader using correct
and incorrect outcomes, then qualifies one isolated execution path before repeated
matched trials. The [delivery plan](../../PLAN.md) maps steps to issues and acceptance.

## Revisit triggers

- Subject adapters repeatedly require project-specific branches in core logic:
  revisit the interface using two concrete failing examples.
- A proven existing runner supplies the required boundaries more cheaply:
  adopt it rather than preserve custom machinery for its own sake.
- A subject requires host semantics Docker cannot represent: add a scoped
  environment adapter, not an unqualified portability claim.
- Pilot evidence contradicts the difficulty ordering: version and recalibrate
  the task bands rather than reinterpret earlier scores.
- Optional evaluation dependencies impair the standalone static checker:
  restore the boundary before extending the evaluation surface.

## References

- [Pinned Coder Eval contract handoff](../research/coder-eval-skillc-contract-handoff-2026-09-20.md)
- [ADR 0001: Every check ships a redcase](0001-every-check-ships-a-redcase.md)
- [Prior project assessment](../reviews/2026-09-15-skills-as-code-harness.md)
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Harbor task structure](https://docs.harborframework.com/core-concepts/tasks/overview)
- [Harbor separate verifier](https://docs.harborframework.com/core-concepts/tasks/separate-verifier)

The external sources inform the design and reuse investigation. No runner
compatibility experiment or live behavioral trial has been performed for this ADR.
