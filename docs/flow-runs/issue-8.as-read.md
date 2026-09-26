# Issue #8 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #8
- Read at:      2026-09-26T14:57:19Z
- updatedAt:    2026-09-26T14:54:02Z   (context only - moves on comments and labels)
- Body digest:  22caeeb8a90019127e1025f1af32ffe3afffc852dff2c170879cbf4cab641faa   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2003 of 2003 (cap 16384)

## Body as read
Parent roadmap: #1
Priority: P1
Depends on: #4.

## Problem and outcome

Expected trial inventory and evidence must survive crashes, retries and backend omissions without trusting a subject-produced task.json.

## Acceptance

- [ ] Create the expected trial inventory before dispatch and persist controller-generated experiment/trial/attempt identities with immutable resolved configuration.
- [ ] Record lifecycle, stop reasons, cleanup, capture coverage and explicit unavailable/inconclusive/not-run states; never silently drop attempts.
- [ ] After confirmed stop, export a bounded immutable artifact manifest with path/type/size/digests; reject traversal/symlink escape and unintended private/secret exports.
- [ ] Bind raw transport observations to origin and attempt; stale/mismatched records and modified artifacts cannot become verified results.
- [ ] Implement linked retries/regrades without overwriting originals; choose local/private storage and retention policy before real private or model evidence.

## Scope and evidence

EF-02, EF-07, EF-08, EF-10. Use deterministic fixtures; no backend-specific core branches.

Follow [PLAN.md](https://github.com/cooneycw/skillc/blob/main/PLAN.md), [interface contracts](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/interfaces.md) and [protocol](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/protocol.md). The [prior assessment](https://github.com/cooneycw/skillc/blob/main/docs/reviews/2026-09-15-skills-as-code-harness.md) and [Coder Eval handoff](https://github.com/cooneycw/skillc/blob/main/docs/research/coder-eval-skillc-contract-handoff-2026-09-20.md) distinguish historical observations from proposals.

Every load-bearing rule needs discriminating controls under ADR 0001. Keep runtime implementation out of the planning PR. Closing this issue requires its acceptance evidence, not merely code or document presence; remaining dependencies and unavailable evidence stay explicit.

