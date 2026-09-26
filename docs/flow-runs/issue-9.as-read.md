# Issue #9 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #9
- Read at:      2026-09-26T16:00:36Z
- updatedAt:    2026-09-26T14:54:13Z   (context only - moves on comments and labels)
- Body digest:  2cb8caf1a6227798311a9f21f10872f3999861d4fd8dcd1064f293544f9e9d79   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2000 of 2000 (cap 16384)

## Body as read
Parent roadmap: #1
Priority: P1
Depends on: #5, #8.

## Problem and outcome

The agent and its code must not be able to manufacture the authoritative result, including while the grader executes candidate code.

## Acceptance

- [ ] Run pinned grader/held-out checks from trusted inputs in a fresh isolated environment on a disposable copy of frozen artifacts.
- [ ] Keep candidate processes unable to overwrite the success channel, grader definitions or controller ledger; do not expose evaluator credentials to candidate code.
- [ ] Derive criterion outcomes and protocol disposition from validated checks; preserve missing evidence and observed mandatory violations.
- [ ] Prove known-good/bad outputs, forged prose/JSON, modified local tests, attempted verifier-output writes, stale receipts and missing digests discriminate correctly.
- [ ] Test always-pass/always-fail/crash/no-output graders and deterministic regrading lineage. Record remaining trust assumptions and unobserved process properties.

## Scope and evidence

EF-04, EF-05, EF-07, EF-08. Deterministic checks first; calibrated model judges are later scope.

Follow [PLAN.md](https://github.com/cooneycw/skillc/blob/main/PLAN.md), [interface contracts](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/interfaces.md) and [protocol](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/protocol.md). The [prior assessment](https://github.com/cooneycw/skillc/blob/main/docs/reviews/2026-09-15-skills-as-code-harness.md) and [Coder Eval handoff](https://github.com/cooneycw/skillc/blob/main/docs/research/coder-eval-skillc-contract-handoff-2026-09-20.md) distinguish historical observations from proposals.

Every load-bearing rule needs discriminating controls under ADR 0001. Keep runtime implementation out of the planning PR. Closing this issue requires its acceptance evidence, not merely code or document presence; remaining dependencies and unavailable evidence stay explicit.

