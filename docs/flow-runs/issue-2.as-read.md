# Issue #2 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #2
- Read at:      2026-09-25T16:14:48Z
- updatedAt:    2026-09-20T16:27:35Z   (context only - moves on comments and labels)
- Body digest:  61c7b688f7d733093196430366afe3a8cf182a0bf12cd950b3cb530158bf6d04   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1868 of 1868 (cap 16384)

## Body as read
Parent roadmap: #1
Priority: P0
Depends on: None; can start from the planning baseline.

## Problem and outcome

The September 15 assessment recorded empty good controls and parser failures certifying a different rule, plus unknown --rule values returning a clean result. Current source still contains these paths; the existing 12-test suite passes without covering them.

## Acceptance

- [ ] Require nonempty, readable, successfully parsed good/bad populations for semantic rules; parser controls have explicit expectations.
- [ ] Require the selected rule ID to produce the bad-case finding; an unrelated frontmatter error cannot certify it.
- [ ] Reject unknown CLI rule selectors with nonzero exit and a useful diagnostic before scanning.
- [ ] Commit controls for empty good/bad populations, malformed bad input with a blinded rule, and an invalid selector; confirm a healthy rule still passes.

## Scope and evidence

Static gate foundation; ADR 0001. Does not add behavioral execution.

Follow [PLAN.md](https://github.com/cooneycw/skillc/blob/main/PLAN.md), [interface contracts](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/interfaces.md) and [protocol](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/protocol.md). The [prior assessment](https://github.com/cooneycw/skillc/blob/main/docs/reviews/2026-09-15-skills-as-code-harness.md) and [Coder Eval handoff](https://github.com/cooneycw/skillc/blob/main/docs/research/coder-eval-skillc-contract-handoff-2026-09-20.md) distinguish historical observations from proposals.

Every load-bearing rule needs discriminating controls under ADR 0001. Keep runtime implementation out of the planning PR. Closing this issue requires its acceptance evidence, not merely code or document presence; remaining dependencies and unavailable evidence stay explicit.

