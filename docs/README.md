# Documentation

## Planned evaluation facility

Documentation only; the behavioral evaluation facility is not implemented.

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
