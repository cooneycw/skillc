# Issue #12 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #12
- Read at:      2026-09-28T09:35:43Z
- updatedAt:    2026-09-28T09:05:07Z   (context only - moves on comments and labels)
- Body digest:  2cf4377a53a187d5dea2f28ca33134f4a68dc0d45e4df96f775a257730adfd22   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3855 of 3855 (cap 16384)

## Body as read
Parent roadmap: #1
Priority: P1
Depends on: #11.

## Problem and outcome

The facility is useful when it measures outcomes honestly, including a null result. Live execution requires an explicit experiment configuration and spending bounds.

## Acceptance

- [ ] Before any paid invocation, record exact model/client/subject/image identities, goal population, treatment versus minimal baseline, repeat schedule, arm order, per-trial/total time and monetary caps, and clarification/approval behavior.
- [ ] Use fresh state, matched ordinary project requirements/tools/budgets and all extra scaffold calls in accounting; resolve private artifact retention before capture.
- [ ] Run only within that recorded authorized budget. If no budget is approved, prepare the reviewable run manifest and leave execution incomplete.
- [ ] Report every scheduled attempt by protocol disposition, per-criterion success, uncertainty, claim accuracy, intervention counts, time and observed cost with missing values explicit.
- [ ] Separate setup/agent/grading cost and time; compare completion time on matched successful trials while displaying failures. Preserve raw artifacts and make no qualification or broad-benefit claim from a small canary.

## Scope and evidence

EF-06, EF-07, EF-09. Paid runs are not authorized by creating this issue or merging planning docs.

Follow [PLAN.md](https://github.com/cooneycw/skillc/blob/main/PLAN.md), [interface contracts](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/interfaces.md) and [protocol](https://github.com/cooneycw/skillc/blob/main/docs/specs/evaluation-facility/protocol.md). The [prior assessment](https://github.com/cooneycw/skillc/blob/main/docs/reviews/2026-09-15-skills-as-code-harness.md) and [Coder Eval handoff](https://github.com/cooneycw/skillc/blob/main/docs/research/coder-eval-skillc-contract-handoff-2026-09-20.md) distinguish historical observations from proposals.

Every load-bearing rule needs discriminating controls under ADR 0001. Keep runtime implementation out of the planning PR. Closing this issue requires its acceptance evidence, not merely code or document presence; remaining dependencies and unavailable evidence stay explicit.


## Folded in from the Nit Store (#20), 2026-09-27

This acceptance requires "exact model/client/subject/image identities" and concurrent attempts. These three gaps stand in the way:

- [ ] **The digest of the image that actually ran is never recorded.** `DockerBackend` takes a configured `image` string. Nothing resolves `docker image inspect --format {{.Id}}` for the attempt or puts it in the receipt or ledger, so a floating or republished tag leaves "what ran" unverified. This is a schema change (`records.py` vocabulary / `BackendDescription`). (https://github.com/cooneycw/skillc/issues/20#issuecomment-5849956487)
- [ ] **Judge model identity is the server, not the LLM** (`judge_mcp_second_opinion.py` `describe()` ~191). `JudgeDescription.model`/`.version` come from MCP `serverInfo`, which is the server's own name. Two tiers pointed at one server report the same "model" whatever LLM each calls, so ADR 0006's tier separation cannot be verified from the wire. Resolve this before tier verdicts are compared. (https://github.com/cooneycw/skillc/issues/20#issuecomment-5851020208)
- [ ] **Concurrent attempts falsely refuse each other's grades** (`verify.py` `grade()`). The whole experiment directory is snapshotted before the probe and compared after, so a sibling attempt's legitimate capture or `add_result` reads as tampering. It fails closed, but every overlap costs a grade. Add an experiment-level lock across snapshot, grade, re-check and `add_result`, or a scoped snapshot. Red case: two attempts, one captured while the other grades. (https://github.com/cooneycw/skillc/issues/20#issuecomment-5847991336)

