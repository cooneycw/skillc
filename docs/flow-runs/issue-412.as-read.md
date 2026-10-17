<!-- flow-run n=1 id=2a2ccd0ca018475ea4ebecd125df73e4 -->
## Run 1 - issue #412 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #412
- Read at:      2026-10-17T14:38:23Z
- updatedAt:    2026-10-17T14:37:25Z   (context only - moves on comments and labels)
- Body digest:  2513c7d2b5df13207e59f769e9f29fa159e69de49b0d6f04d9b2cabf2b0a70e0   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 4072 of 4072 (cap 16384)

### Body as read
## Problem

Several fake-Docker tests fail on fixed deadlines when nothing about the change under review touched them. They fail at low host load too, and on **main**. Their bounds sit inside the code under test: the fake-docker daemon budget, per-call subprocess deadlines, and `Limits(timeout=5)`. The suite-wide 120 s pytest-timeout is not what trips. This issue carries the widened scope recorded on #410 (comment 2026-10-17T12:46Z). #410 is narrowed to the one screen test, which is a different mechanism: cumulative work against the 120 s wall clock.

## Evidence so far

| Pipeline | Ref | Host state | Failures |
|---|---|---|---|
| 792 | PR #403 | overlapping other pipelines | `test_demo.py` (cancellation seeds, run control, others), `test_qualify_scripts_run.py` (3 subprocess timeouts) |
| 804 | PR #403 | alone on the agent | `test_live_docker_budget.py::test_a_start_slower_than_the_budget_is_still_refused[1.0-3.0]` (and the #410 screen test) |
| 806 | main push `bb24739` (#409, test-only) | 15-min load ~3.3, nothing else under lock 1; PR pipeline 805 on the same tree and restart 807 were green | the five below |

806 members, with the bound each one depends on (read from the test source at `bb24739`; to be confirmed by measurement):

| Test | Bound | Is the bound the property under test? |
|---|---|---|
| `test_live_docker_budget.py::test_a_start_slower_than_the_budget_is_still_refused[5.0-6.0]` | production `DAEMON_TIMEOUT = 5.0` (`skillc/docker_backend.py:151`) against a 6 s fake start; 806 failed with fake-docker `run` timed out after 5.0 s | **Yes.** The 5 s vs 6 s spacing is the claim, so it cannot simply be widened |
| `test_demo.py::test_cancellation_seed_is_caught_and_leaves_the_foreign_container_untouched` | `timeout=5, sleep=4` in the demo control; 806: child exited 0.4 s after SIGINT, `foreign_removed=not-confirmed` | Partly. The stop is the property; the 1 s gap between sleep and timeout is margin |
| `test_demo.py::test_run_control_reports_all_six_seeds_in_a_leak_clean_block` | aggregate of the six control seeds, including the timeout/cancellation seeds above | No, it inherits the seeds' bounds |
| `test_docker_backend.py::test_a_directory_symlink_at_observations_makes_the_writeback_fail_visibly` | `Limits(timeout=5)` on a subject that should exit at once; 806: `'timeout' != 'exited'` | No. 5 s is margin for a quick exit |
| `test_docker_backend.py::test_read_home_tree_joins_stdout_and_stderr_against_one_shared_deadline[slow-cp]` | fake `cp` delayed 1.2 s; 806: fake-docker `cp` timed out after 5.0 s | No. The join shape is the property (#382) |

Also in this family, not yet red:
- `tests/test_uptake_study.py::test_the_arms_differ_only_in_the_install_and_selection_is_counted_and_tested`: 12 attempts, measured 50.6 s in one run and 25.2 s on 2026-10-17 at load ~2.7, against the 120 s pytest-timeout. Same mechanism as #410.
- `test_matched_pilot_run.py` timeouts and the `test_live_docker_budget[1.0-3.0]` subprocess `TimeoutExpired`: Nit Store #20 (https://github.com/cooneycw/skillc/issues/20#issuecomment-6225508173, https://github.com/cooneycw/skillc/issues/20#issuecomment-6233822186).

Prior work in this area: #382, #385, #390, #221, #399 (closed).

## Outcome and acceptance

- [ ] **First deliverable, before any bound changes:** a per-test measurement posted here. For each member: wall time, and headroom against that test's own deadline, at CI's real parallelism (`-n auto --maxprocesses=8 --dist=loadgroup`). Each measurement run holds lock 1 for its own duration and records `uptime` at its start and end.
- [ ] Each member gets a disposition: shrink the work, make it deterministic (assert the shape, not the wall clock), raise a bound with a measured reason, or leave it because the bound is the property. A bound that IS the property is never widened to make the test pass.
- [ ] Every changed test keeps a red case that fails on the defect it pins.
- [ ] No assertion is dropped.

Priority: P1. 806 was a red on main.

Split from #410 while driving it (flow:auto, cpp-final-fix session).


<!-- flow-run n=2 id=2cd7cc5ab3a545188760a5565058c3f3 -->
## Run 2 - issue #412 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #412
- Read at:      2026-10-17T15:14:48Z
- updatedAt:    2026-10-17T14:38:41Z   (context only - moves on comments and labels)
- Body digest:  2513c7d2b5df13207e59f769e9f29fa159e69de49b0d6f04d9b2cabf2b0a70e0   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 4072 of 4072 (cap 16384)

### Body as read
## Problem

Several fake-Docker tests fail on fixed deadlines when nothing about the change under review touched them. They fail at low host load too, and on **main**. Their bounds sit inside the code under test: the fake-docker daemon budget, per-call subprocess deadlines, and `Limits(timeout=5)`. The suite-wide 120 s pytest-timeout is not what trips. This issue carries the widened scope recorded on #410 (comment 2026-10-17T12:46Z). #410 is narrowed to the one screen test, which is a different mechanism: cumulative work against the 120 s wall clock.

## Evidence so far

| Pipeline | Ref | Host state | Failures |
|---|---|---|---|
| 792 | PR #403 | overlapping other pipelines | `test_demo.py` (cancellation seeds, run control, others), `test_qualify_scripts_run.py` (3 subprocess timeouts) |
| 804 | PR #403 | alone on the agent | `test_live_docker_budget.py::test_a_start_slower_than_the_budget_is_still_refused[1.0-3.0]` (and the #410 screen test) |
| 806 | main push `bb24739` (#409, test-only) | 15-min load ~3.3, nothing else under lock 1; PR pipeline 805 on the same tree and restart 807 were green | the five below |

806 members, with the bound each one depends on (read from the test source at `bb24739`; to be confirmed by measurement):

| Test | Bound | Is the bound the property under test? |
|---|---|---|
| `test_live_docker_budget.py::test_a_start_slower_than_the_budget_is_still_refused[5.0-6.0]` | production `DAEMON_TIMEOUT = 5.0` (`skillc/docker_backend.py:151`) against a 6 s fake start; 806 failed with fake-docker `run` timed out after 5.0 s | **Yes.** The 5 s vs 6 s spacing is the claim, so it cannot simply be widened |
| `test_demo.py::test_cancellation_seed_is_caught_and_leaves_the_foreign_container_untouched` | `timeout=5, sleep=4` in the demo control; 806: child exited 0.4 s after SIGINT, `foreign_removed=not-confirmed` | Partly. The stop is the property; the 1 s gap between sleep and timeout is margin |
| `test_demo.py::test_run_control_reports_all_six_seeds_in_a_leak_clean_block` | aggregate of the six control seeds, including the timeout/cancellation seeds above | No, it inherits the seeds' bounds |
| `test_docker_backend.py::test_a_directory_symlink_at_observations_makes_the_writeback_fail_visibly` | `Limits(timeout=5)` on a subject that should exit at once; 806: `'timeout' != 'exited'` | No. 5 s is margin for a quick exit |
| `test_docker_backend.py::test_read_home_tree_joins_stdout_and_stderr_against_one_shared_deadline[slow-cp]` | fake `cp` delayed 1.2 s; 806: fake-docker `cp` timed out after 5.0 s | No. The join shape is the property (#382) |

Also in this family, not yet red:
- `tests/test_uptake_study.py::test_the_arms_differ_only_in_the_install_and_selection_is_counted_and_tested`: 12 attempts, measured 50.6 s in one run and 25.2 s on 2026-10-17 at load ~2.7, against the 120 s pytest-timeout. Same mechanism as #410.
- `test_matched_pilot_run.py` timeouts and the `test_live_docker_budget[1.0-3.0]` subprocess `TimeoutExpired`: Nit Store #20 (https://github.com/cooneycw/skillc/issues/20#issuecomment-6225508173, https://github.com/cooneycw/skillc/issues/20#issuecomment-6233822186).

Prior work in this area: #382, #385, #390, #221, #399 (closed).

## Outcome and acceptance

- [ ] **First deliverable, before any bound changes:** a per-test measurement posted here. For each member: wall time, and headroom against that test's own deadline, at CI's real parallelism (`-n auto --maxprocesses=8 --dist=loadgroup`). Each measurement run holds lock 1 for its own duration and records `uptime` at its start and end.
- [ ] Each member gets a disposition: shrink the work, make it deterministic (assert the shape, not the wall clock), raise a bound with a measured reason, or leave it because the bound is the property. A bound that IS the property is never widened to make the test pass.
- [ ] Every changed test keeps a red case that fails on the defect it pins.
- [ ] No assertion is dropped.

Priority: P1. 806 was a red on main.

Split from #410 while driving it (flow:auto, cpp-final-fix session).

