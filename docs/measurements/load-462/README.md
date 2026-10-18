# Load measurements for #462

**Rule for contributors.** Anything that starts spinners runs ONLY inside a
lock-1 hold, or under a hard CPU cap such as
`systemd-run --user --scope -p CPUQuota=200% <command>`, never bare on a
shared host. That covers `ci/load-repro.sh`, `ci/load_harness.py phase`,
`tests/test_load_harness.py` and any mutation run against them. Two runs during
#462 leaked spinner groups (a mutant that disabled cleanup), and the cap is
what bounds that failure.

Each file is the output of `ci/load-repro.sh` (summarised by `ci/load_harness.py
summarize`), named `<member>-<load>-<sha12>-<pre|post>.json`:

- `<load>` is `x2` (2x nproc CPU spinners, no churn) or `x4` (4x nproc spinners
  plus 8 interpreter-start churn loops).
- `<sha12>` is the commit the test ran at. `pre` is unfixed main; `post` is the fix.
- `.diag.jsonl` files beside them come from `-p ci.load_diag462`: the
  gate_witness pid-read and kill-confirmation timings, and the evidence_export
  whole-attempt wall time.

Paths in the records are scrubbed (`<root>`, `~`, `pytest-of-<user>`).

A phase counts only when its load control says VALID: the sampled
`procs_running` mean reached the target (see `ci/load_harness.py`). Read
`meets_2x_nproc`, `invalid_phases` and `pauses_ok` before the pass/fail counts.

## Hold A (pre-fix baseline), kyle19, 24 cores, main 728f17342f43, 2026-10-18

All 13 phases VALID (`procs_running` mean 55-64 at x2, 114-122 at x4).

| Member | x2 | x4 + churn | Reading |
|---|---|---|---|
| lifecycle (operator cancellation) | 1 of 20 failed (`inconclusive`) | not run (reproduced at x2) | Reproduced: the 0.15 s head-start race |
| gate_witness (stop confirmation) | 0 of 20 | 0 of 20 | Not reproduced. pid read max 0.90 s against its 2.0 s poll; 0 `stop_confirmed=False` |
| evidence_export (one test) | 0 of 20 | 0 of 20 | Not reproduced |
| evidence_export (whole file, `-n 8`) | 0 of 5 | 0 of 5 | Not reproduced, including the issue's named test 10 times |
| docker_backend (stalled `docker run`) | 0 of 20 | 0 of 20 | Not reproduced |
| trial_image_tools_live (version floor) | 0 of 20 | 0 of 20 | Not reproduced |
| demo (cancellation seed) | 0 of 20 | 0 of 20 | Not reproduced |

The evidence_export diagnosis in the issue ("a 5 s whole-attempt limit") is
falsified: `timeout=5` is the agent exec's `Limits(timeout=...)` only. Whole
attempts ran 12.8 s at the median and up to 32.4 s under load, and all 230
were `captured`.
