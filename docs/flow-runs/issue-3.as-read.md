# Issue #3 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #3
- Read at:      2026-09-25T16:52:34Z
- updatedAt:    2026-09-20T16:27:36Z   (context only - moves on comments and labels)
- Body digest:  440e1299425705d0f8d40fa49e3e058a943cc7ee2a3f6819a595a3b3b8da9d2a   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1982 of 1982 (cap 16384)

## Body as read
Parent roadmap: #1
Priority: P0
Depends on: None; can start from the planning baseline.

## Problem and outcome

Required mapping-valued fields currently evade validation, folded descriptions are rejected, and universal harness-field warnings overstate compatibility. Resolve these before using static output as installation evidence.

## Acceptance

- [ ] Reject non-string or empty required values with the owning rule and discriminating controls.
- [ ] Document the supported YAML subset honestly; either support valid folded/literal descriptions or diagnose unsupported syntax without claiming full format compatibility.
- [ ] Replace universal field-loading claims with explicit portable/target scope. Verify the selected initial client profile against primary documentation before enforcing it.
- [ ] Test valid and invalid types/syntax plus an extension field for the selected target; preserve stdlib-only runtime and standalone commands.

## Scope and evidence

Static compatibility prerequisite for native installation; EF-03 and EF-11. Not a general YAML implementation or universal client matrix.

Follow [PLAN.md](https://github.com/cooneycw/skillc/blob/main/PLAN.md), [interface contracts](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/interfaces.md) and [protocol](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/protocol.md). The [prior assessment](https://github.com/cooneycw/skillc/blob/main/docs/reviews/2026-09-15-skills-as-code-harness.md) and [Coder Eval handoff](https://github.com/cooneycw/skillc/blob/main/docs/research/coder-eval-skillc-contract-handoff-2026-09-20.md) distinguish historical observations from proposals.

Every load-bearing rule needs discriminating controls under ADR 0001. Keep runtime implementation out of the planning PR. Closing this issue requires its acceptance evidence, not merely code or document presence; remaining dependencies and unavailable evidence stay explicit.

