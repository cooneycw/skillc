<!-- flow-run n=1 id=99f9e5a6e7ea48b889cef4567c63e084 -->
## Run 1 - issue #399 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #399
- Read at:      2026-10-15T18:54:23Z
- updatedAt:    2026-10-15T16:13:40Z   (context only - moves on comments and labels)
- Body digest:  19a2b5242e82a2aaa1658c870c7999d3ff6dfd35acee050c0cc64e76e3586158   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3502 of 3502 (cap 16384)

### Body as read
Two `tests/test_calibration_run.py` tests time out on a loaded Woodpecker host. They turned PR CI red twice on 2026-10-15, each time on a PR that never touched them, and a plain restart of the same commit went green both times.

## The tests

- `tests/test_calibration_run.py::test_three_arms_differ_only_by_install_and_the_provided_arm_s_instruction` (line 611)
- `tests/test_calibration_run.py::test_expanded_instruction_lane_dry_run_schedules_and_reconciles_all_three_arms` (line 757)

Each takes **33.6 s** locally on a quiet host (measured 2026-10-15 on `a100da5`). The limit is the suite-wide `timeout = 120` in `pyproject.toml` (#148). Neither test raises it with `@pytest.mark.timeout`. So both have a 3.5x margin, and a CI host running about 2x slower than local, under other load, eats it.

## Occurrences

| Pipeline | PR | Suite time | Result |
|---|---|---|---|
| 781 | #397 (#394) | 605 s, load average 5.7/6.1 | both tests `Timeout (>120.0s) from pytest-timeout` |
| 782 | same commit, restarted | 315 s | green |
| 785 | #398 (#387), `478e2c9` | 618 s | both tests timed out: 2 failed, 3989 passed |
| 786 | same commit, restarted | - | green |

Neither PR caused it. #397's effect on these tests was measured at about +5% (one extra fake `docker inspect` per `destroy()`). #398 touched only `tests/test_gate_witness.py`, and its local full gate ran 4017 passed, 0 failed, in 323 s.

Earlier records: Nit Store https://github.com/cooneycw/skillc/issues/20#issuecomment-6192580187 and the recurrence https://github.com/cooneycw/skillc/issues/20#issuecomment-6193948059. This issue promotes them, because the pair now blocks merges.

## Why it matters

Every merge attempted while the CI host is busy now costs a full extra CI run (about 10 minutes) and a manual restart. A red that clears on restart also teaches people to restart reds without reading them, which is how a real failure in this file would get waved through.

This is the same family as #382, #385 and #387: a fixed time budget racing work whose duration depends on host load.

## Not the cause

The fake daemon budget is already generous. `_FAKE_DAEMON_TIMEOUT = 120.0` (line 51) bounds each fake `docker` call, not the test. What runs out is pytest's whole-test limit, which covers many fake-CLI calls. Each call is a fresh Python process, so the test's total time scales with host load.

## Acceptance

- [ ] **Measure first.** Count the fake `docker` invocations each test makes and where its 33 s goes (`--durations` alone does not show it). Decide from that between:
  - **(a)** cutting the work: fewer attempts per arm, or a cheaper fake path for steps the test doesn't assert on;
  - **(b)** an explicit `@pytest.mark.timeout` on these two tests with a stated, measured margin.
  
  Prefer (a): (b) raises the limit without making the tests any faster.
- [ ] **Keep the property each test asserts.** Three arms that differ only by install plus the provided arm's instruction, and a dry run that schedules and reconciles all three arms. Do not weaken either assertion to buy speed.
- [ ] **Show the margin under load.** Run both tests under the same 8-way parallel load used to reproduce #387 and report the slowest observed time against the limit.
- [ ] **The limit must still catch a hang.** If (b) is chosen, a test that genuinely hangs must still fail within the new limit, not run unbounded. Name the input that proves it (for example a fake `docker` that never returns).

Found while merging PR #398 (#387).

