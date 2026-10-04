# Calibration for #203, step (b): B/N/P on `helper-different-question`

**Status: run 2026-10-04; see [report.md](report.md). At the floor: 0/18 PASS in
every arm.** P read `flow-auto`'s guidance on this exact failure class 6/6
times and still trusted the helper.

The same design and identities as [`evals/calibration-203`](../calibration-203/README.md):
- arms `baseline` (B), `natural` (N) and `provided` (P, told to read
  `flow-auto` and `flow-check`);
- 6 attempts per arm;
- `gpt-6-astra` at effort `high`, cpp-codex @ `85e9b03`, image `sha256:eb17e8c7…`.

The task changes to candidate 3,
[`evals/level3/helper-different-question`](../level3/helper-different-question/README.md)
(#242). The first candidate was at ceiling at both efforts (PR #236,
PR #241). The order is derived from seed `20261005`.

Run with
`SKILLC_ALLOW_REAL_AGENT=1 skillc calibration-run evals/calibration-203-c3/run-manifest.json`.
