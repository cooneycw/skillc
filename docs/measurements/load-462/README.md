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

- `<load>` is `x2` (2x nproc CPU spinners, no churn), `x4` (4x nproc spinners
  plus 8 interpreter-start churn loops), or `x2pin` (Hold B: pinned to CPUs
  0-7, 16 spinners, 2 Docker plus 2 fsync I/O churn loops).
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

## Hold B (kyleci emulation), kyle19 pinned to CPUs 0-7, main a0edf35af648, 2026-10-18

The 8-core CI host where gate_witness failed was emulated by pinning the
harness, the load and every rep to CPUs 0-7, with 16 spinners (2x the pinned
cores), 2 Docker-daemon churn loops and 2 fsync I/O churn loops.

All 7 phases were VALID:
- the pinned cores were 1.0 busy;
- the spinners were attributed 0.79-0.99 of their cores;
- the `procs_running` mean was 22-30 against a target of 16.

| Member | Hold B | Both holds |
|---|---|---|
| gate_witness | 0 of 20 (pid read max 0.34 s; 0 `stop_confirmed=False`) | 0 of 60 |
| evidence_export (the issue's named test) | 0 of 20 (attempts max 11.9 s, all captured) | 0 of 60 |
| evidence_export (whole file, `-n 8`) | 0 of 3 (attempts max 15.3 s, all captured) | 0 of 13 |
| docker_backend (stalled `docker run`) | 0 of 20 | 0 of 60 |
| trial_image_tools_live | 0 of 20 | 0 of 60 |
| demo | 0 of 20 | 0 of 60 |
| docker_backend reap `[parent-stopped]` | 0 of 20 | 0 of 20 (added after Hold A) |

These summaries were recomputed by the fixed `summarize` from the raw phase
records, which are unchanged. Hold B ran a harness that judged `meets_2x_nproc`
against the 24 host cores, so it read False there.

Each `cleanup_errors` entry is the daemon's own `--rm` racing the sweep
("removal of container ... is already in progress"). The fixed harness treats
that response as benign. After the hold, no `skillc.load462` container
remained. The raw records keep the error text as it was produced, so
`summarize` still exits 5 on them.

**Reading:** the synthetic-load hypothesis is falsified for these six members.
The reds are real and still recur in gates, but CPU, Docker or I/O contention
as modelled here does not produce them. See
https://github.com/cooneycw/skillc/issues/462#issuecomment-6251986114.
