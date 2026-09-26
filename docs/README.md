# Documentation

## Evaluation facility

The static checker, materialization, controller and verifier pieces below are
implemented and exercised by real evidence (see the top-level
[README](../README.md#status) for the milestone table). The full behavioral
task levels beyond Level 1 remain documentation only.

- [Specification](specs/evaluation-facility/spec.md): generic subjects, goal-based
  tasks, progressive difficulty, boundaries and acceptance requirements.
- [Evaluation protocol](specs/evaluation-facility/protocol.md): experiment design,
  independent grading, result semantics, evidence and comparisons.
- [Interface contracts](specs/evaluation-facility/interfaces.md): installation,
  controller ledger, artifact capture and independent verification.
- [Controller accounting and capture](specs/evaluation-facility/capture.md): what
  `skillc/trial.py` records and exports, and the evidence storage and retention policy.
- [Independent grading and result assembly](specs/evaluation-facility/verification.md):
  how `skillc/verify.py` grades frozen output outside the subject's reach, and the
  trust assumptions and unobserved properties it states.
- [Trial image and agent bootstrap](specs/evaluation-facility/trial-bootstrap.md):
  `skillc/trial_bootstrap.py` and `docker/trial/` - the per-trial home, onboarding
  seed, MCP config, invocation and skill+tool liveness canary a live agent needs to
  actually start and work inside a Docker trial (#78).
- [Design review](specs/evaluation-facility/review.md): open decisions and questions
  to challenge before implementation.
- [Delivery plan](../PLAN.md): staged milestones and their acceptance evidence.

## Project assessment

- [Skills as code and the CPP harness](reviews/2026-09-15-skills-as-code-harness.md)
  records the project scan, recommendation, verified implementation gaps, and
  proposed first milestone. This is an assessment, not an accepted roadmap.

## Decisions

- [ADR 0001: Every check ships a redcase](decisions/0001-every-check-ships-a-redcase.md)
- [ADR 0002: Independent, goal-driven evaluation](decisions/0002-independent-goal-driven-evaluation.md)
  records the planning direction and decisions deferred to implementation issues.
- [ADR 0003: No external evaluation runtime](decisions/0003-no-external-evaluation-runtime.md)
  rules out a runtime dependency on Coder Eval or Harbor (#6).
- [ADR 0004: Evaluate the exposed knowledge surface](decisions/0004-evaluate-the-exposed-knowledge-surface.md)
  widens the subject to layered, exposed knowledge and defines the
  valid/exposed/reachable/selected/effective ladder (#55).
- [ADR 0005: Runtime scope, judge mechanism and cost stop](decisions/0005-runtime-scope-and-cost-rulings.md)
  records five owner rulings: skillc runs wherever it is installed with no
  dedicated machine assumed; a managed-container backend is an optional
  plug-in (#64); no machine identities in outputs (#63); `mcp-second-opinion`
  as the model-judge mechanism, with all enabled grading tiers producing
  separate verdicts (#69); and the cost stop on paid runs (#12).
- [ADR 0006: Grading tiers - a judge seam, never averaged with the
  deterministic floor](decisions/0006-grading-tiers.md) records what each
  tier does and does not establish, the same-model limitation made a
  measured per-criterion disagreement record, and the boundary between this
  PR's seam/fake judge and the real `mcp-second-opinion` adapter, which is a
  follow-up PR (#69).

## Research and prior reviews

- [Coder Eval contract research](research/README.md) records the pinned source
  assessment and the [lessons skillc keeps](research/coder-eval-lessons.md) now
  that no backend adapter will be built.

The reports in the following table were moved from the owner's Downloads folder on 2026-09-15.
They are historical inputs to the assessment, not current compatibility
specifications or independently reproduced benchmarks. Unicode em and en dashes
were normalized to ASCII hyphens, and CSV line endings were normalized to LF;
the reports otherwise retain their content.

| Report | Relevance |
|---|---|
| [Skills Are The New Code: CPP audit](research/skills-are-the-new-code-cpp-audit.html) | Direct motivation for skillc; skill lifecycle and document-quality review |
| [Harness strategy recommendation](research/harness-strategy-recommendation-2026-09-14.html) | Keep CPP's useful controls while bounding maintenance and ceremony |
| [Instruments and counter-model adoption](research/instruments-and-counter-model-adoption-2026-09-14.html) | Distinguishes specs, instruments, and harnesses; proposes adoption work |
| [Spec-driven development research](research/spec-driven-development-2026.html) | Broader SDD research and competing approaches |
| [Issue quality and delivery assessment](research/issue-quality-assessment-2026-09-14.html) | Evidence of integration failures and misleading completion signals |

The issue-quality report's linked [metrics](research/issue-quality-metrics-2026-09-14.csv)
and [triage register](research/issue-quality-triage-2026-09-14.csv) accompany it.
