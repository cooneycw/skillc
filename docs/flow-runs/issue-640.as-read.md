<!-- flow-run n=1 id=a909e2be424f436487b041a27a0419b3 -->
## Run 1 - issue #640 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #640
- Read at:      2026-10-30T10:03:43Z
- updatedAt:    2026-10-30T10:02:31Z   (context only - moves on comments and labels)
- Body digest:  e3e37847c935d58a883f0e7b96b5b8de6eb95c364fc1b59d368b081ca86623c2   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2352 of 2352 (cap 16384)

### Body as read
Parent: #568 (its B2 slice). Also on the critical path of #628 and #631: every live wave or NHL attempt dispatches through this bridge. Wave: skillc-nhl (owner, 2026-10-30).

## Problem

From `evals/flow-auto-calibration-568/task-interface.md`: `calibration_run` calls `collection_conformance.run_level1_agent_attempt` (the closed single-attempt path) **without a fixture**. `fixture_live`'s closed registry and mandatory treatment are not a baseline route. So no calibration arm can today get the controller-owned GitHub stand-in (#276) and fixture remote, and no arm's result can be graded from the remote's actual objects.

## Bounded delivery

- [ ] **Symmetric paired fixture dispatch.** Every arm of a calibration run (treated and baseline) gets an identical fixture built by `fixture_campaign.build_case` / `AttemptFixture` on the same controller export, with `capture_snapshot` after the attempt. Same service authority, same remote, same public requirements; an arm never gets a fixture the other lacks.
- [ ] **Grade the remote's actual objects.** The oracle reads exact remote `main` objects through `GitDir` from the captured snapshot. Source digests or local workspace correctness never supply delivered files. Missing export is UNKNOWN; an observed wrong or undelivered `main` FAILS.
- [ ] **Register the oracle as an isolated grader**, running outside the agent's container against the captured snapshot only.
- [ ] **Decide #568's `_HONESTY_ROLES` row** (`skillc/calibration_run.py:1652`) and record the decision.
- [ ] **Accounting:** success, task failure, timeout, infrastructure failure and non-start are all counted for every scheduled attempt; a fixture that fails to build is a non-start, not a task failure.
- [ ] **Model-free proof** with deterministic clients through the real dispatch path: a correct delivery passes, an undelivered or wrong `main` fails, a missing export is UNKNOWN, and both arms received byte-identical fixtures (committed controls, each shown red on the pre-change path where behaviour exists).

## Out of scope

Cold profile proof, prompt retention (B3), the frozen declaration, and any live run: those stay on #568. Multi-container attempts are #621, which builds on this.

No live model trials are authorized by this issue. Any live run needs a separately approved declaration under skillc ADR 0005.


<!-- end of body -->
