# Flow run record - issue #410

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=9dc1b694e41542b280e1c9004c96e769 -->
## Run 1

- Run-id:            9dc1b694e41542b280e1c9004c96e769
- Run-start:         bb247399219ca2bfcc775d6fd8808081c06d734b
- Issue:             #410
- Base SHA:          bb24739
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T14:00:00Z

### Section B evidence
- Commits on origin/main since filing (2026-10-17T12:21Z): none beyond base bb24739 (#409).
- Merged PRs inspected: #405, #406, #407, #409 - none touch tests/test_uptake_study.py or the screen path.
- Related, none superseding: #399 (closed, same shape for calibration-run), #385, #382, #390, #221 (closed, fake-docker budgets), Nit Store #20.
- Measured serially, timeout lifted: 3 attempts - load 0.2 37.0s, load 8.1 57.5s, load 11.6 61.9s; 2 attempts - load 9.2 46.4s, load 9.8 26.7s.
- Scope condition: the pipeline-806 5s-bound family moves to its own issue, filed before the PR.

### Section C - the approved plan
1. `tests/test_uptake_study.py` - test_a_screen_scores_selectivity_not_just_recall runs at 2 attempts per cell (monkeypatched us.MIN_ATTEMPTS, _screen_data(attempts_per_arm=2)), all five assertions kept with 2/2 counts, docstring records the measurement; production MIN_ATTEMPTS unchanged.

Scope: small, one test function.
Risks: about 1.5x headroom at load 15, not unlimited; a refactor binding MIN_ATTEMPTS at import time would red loudly with a 3-30 refusal.
