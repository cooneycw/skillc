# Issue #4 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #4
- Read at:      2026-09-26T11:50:03Z
- updatedAt:    2026-09-20T16:27:37Z   (context only - moves on comments and labels)
- Body digest:  20ef77d1480acb8537fbdc545a2540972ee345aac81bf4c320c235afa90b93a9   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2114 of 2114 (cap 16384)

## Body as read
Parent roadmap: #1
Priority: P0
Depends on: None; can start from the planning baseline.

## Problem and outcome

The design needs executable boundaries that distinguish a subject claim from controller observations and a verified outcome, independently of runner choice.

## Acceptance

- [ ] Define versioned minimal schemas/records for installation receipts, planned trials/attempts, artifact/event manifests and per-criterion verified results; retain backend raw data.
- [ ] Assign producers and authority; bind subject, case, grader, client/image/config identities and artifact digests to controller-created attempt IDs.
- [ ] Specify protocol status derivation, missing evidence, origin/coverage, retry/regrade lineage and incompatible-version handling.
- [ ] Commit good/bad contract examples for malformed IDs, missing mandatory evidence, conflicting IDs, stale/cross-trial receipts and forged subject verdicts; preserve established mandatory failures.
- [ ] Select the initial observation requirements and local/private retention boundary. Runtime packages must stay outside the stdlib-only static checker.

## Scope and evidence

EF-02, EF-06, EF-07, EF-08, EF-11. Schemas can be local records; no service or SDK platform required.

Follow [PLAN.md](https://github.com/cooneycw/skillc/blob/main/PLAN.md), [interface contracts](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/interfaces.md) and [protocol](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/protocol.md). The [prior assessment](https://github.com/cooneycw/skillc/blob/main/docs/reviews/2026-09-15-skills-as-code-harness.md) and [Coder Eval handoff](https://github.com/cooneycw/skillc/blob/main/docs/research/coder-eval-skillc-contract-handoff-2026-09-20.md) distinguish historical observations from proposals.

Every load-bearing rule needs discriminating controls under ADR 0001. Keep runtime implementation out of the planning PR. Closing this issue requires its acceptance evidence, not merely code or document presence; remaining dependencies and unavailable evidence stay explicit.

