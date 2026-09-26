# Issue #5 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #5
- Read at:      2026-09-26T12:18:55Z
- updatedAt:    2026-09-20T16:27:38Z   (context only - moves on comments and labels)
- Body digest:  61381c98a1d6f7221b4565a9856f6fc7ce5094708b0c106b6f2753d6cc074eb2   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2099 of 2099 (cap 16384)

## Body as read
Parent roadmap: #1
Priority: P0
Depends on: #4.

## Problem and outcome

Use the existing CPP pilot-b-small-fix slug function as a bounded measurement canary. It may be too easy to demonstrate skill benefit; that does not reduce its value for validating the facility.

## Acceptance

- [ ] Pin and attribute the fixture independently of the CPP subject revision; inspect license/reuse terms and copy only the required fixture into skillc.
- [ ] Write public behavior/constraint acceptance shared by both arms. Audit old open/guided/baseline prompt differences; do not inherit confounded comparisons.
- [ ] Provide a correct reference outcome and multiple plausible wrong outputs, including a reported-example-only fix. Accept valid alternative implementations.
- [ ] Prove initial fixture failure and reference success; add held-out variations of public requirements and always-pass/always-fail/crash/no-output grader controls.
- [ ] Record expected ceiling effects and explicit scope: grader/path calibration, not broad CPP superiority. No live model call is needed.

## Scope and evidence

EF-04, EF-05. Candidate source: CPP tests/fixtures/delivery_pilots/pilots/pilot-b-small-fix; pin a chosen revision during this task.

Follow [PLAN.md](https://github.com/cooneycw/skillc/blob/main/PLAN.md), [interface contracts](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/interfaces.md) and [protocol](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/protocol.md). The [prior assessment](https://github.com/cooneycw/skillc/blob/main/docs/reviews/2026-09-15-skills-as-code-harness.md) and [Coder Eval handoff](https://github.com/cooneycw/skillc/blob/main/docs/research/coder-eval-skillc-contract-handoff-2026-09-20.md) distinguish historical observations from proposals.

Every load-bearing rule needs discriminating controls under ADR 0001. Keep runtime implementation out of the planning PR. Closing this issue requires its acceptance evidence, not merely code or document presence; remaining dependencies and unavailable evidence stay explicit.

