<!-- flow-run n=1 id=9dc1b694e41542b280e1c9004c96e769 -->
## Run 1 - issue #410 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #410
- Read at:      2026-10-17T13:07:19Z
- updatedAt:    2026-10-17T12:53:58Z   (context only - moves on comments and labels)
- Body digest:  5c61a23935c407c20dcf6d1ed9c5986517577635dee341b3f21a6f2df834bbf9   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2498 of 2498 (cap 16384)

### Body as read
## What is wrong

`tests/test_uptake_study.py::test_a_screen_scores_selectivity_not_just_recall` takes about 60 s on a quiet host and stretches to 90-120+ s under ordinary host load, against the suite-wide 120 s `pytest-timeout`. It timed out in PR #403's pipeline 804 (78546e7), which ran alone on the agent with nothing overlapping (the previous pipeline, 803, ended at 07:10; 804 ran 07:56-08:08). The test is untouched by #403.

Measured locally, one test, serially (`--durations`, timeout lifted to 300 s for the measurement), 2026-10-17:

| Ref | Host load avg (1 min) at start | Call time |
|---|---|---|
| 410801b | 18.1 | 90.7 s |
| c64bdd6 (#407) | 12.9 | 61.4 s |
| 410801b | 7.2 | 59.5 s |
| c64bdd6 (#407) | 5.8 | 64.9 s |
| a100da5 | 17.0 | 86.6 s |
| f511779 (main) | 15.9 | >120 s (timed out) |
| branch, both files together | 3.9 → 16.5 | 110.5 s |

Interleaved, #407 and its parent run about the same, so this is **not a regression from #407**. A first a100da5 vs f511779 comparison suggested one, but the interleaved runs show it was load. The cost scales with host load, and the headroom at load ~15 is gone. The sibling `test_the_arms_differ_only_in_the_install_and_selection_is_counted_and_tested` took 50.6 s in the same run.

## Why it matters

A full suite or CI run on a busy host goes red here for a reason unrelated to the change under review. That costs a pipeline restart and a lock slot in the host's shared test queue. It also teaches the habit of rerunning reds until green, which is how a real regression gets missed. #399 fixed exactly this pattern for the calibration-run tests (measure the work, cut repeats, keep the red case, do not raise the timeout).

## Suggested approach (same as #399)

Measure what the test spends its time on: it runs a full multi-variant screen through the real install/grade path with the fake docker. Cut the work, for example fewer attempts per cell, while keeping the property, and prove that with the selectivity red case the test already names (a recall-only score must rank variant-b level with variant-a). Do not raise the 120 s limit.

A related load-sensitive failure in the same pipeline, `tests/test_live_docker_budget.py::test_a_start_slower_than_the_budget_is_still_refused[1.0-3.0]` (subprocess TimeoutExpired in CI; 1.1 s locally), and the earlier `test_matched_pilot_run.py` timeouts are in the Nit Store (https://github.com/cooneycw/skillc/issues/20#issuecomment-6225508173).

Found while landing PR #403 (#271).

