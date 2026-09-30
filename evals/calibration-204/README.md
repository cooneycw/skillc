# Calibration before comparison (#204)

**Status: approved 2026-09-30, not run.** `run-manifest.json` is the
predeclaration for #204's two-arm calibration: **full CPP** versus **minimal
baseline** on [`evals/level3/slugkit-pipeline`](../level3/slugkit-pipeline/README.md),
4 attempts per arm, in an order derived from a recorded seed. The owner
approved it on 2026-09-30, and its image digest is resolved
(`sha256:d1b2ced9...`, the image #12's rerun and #150 used), so
`skillc.calibration.require_approved` now authorizes it (ADR 0005). It has not
run: no runner for a two-arm schedule exists yet (`owed_before_run`).

## Why calibrate first

Two of the last three live experiments ran before anyone checked they could
inform (#150's pair was non-discriminating, PR #201; #12's rerun stored
inconclusive results; #26's invocation detection was heuristic). This run
checks the measurement cheaply before #203 spends its budget. It passes when
the measurement is shown to be informative, not when CPP wins.

## The endpoint is symmetric

The primary endpoint is `skillc.calibration.primary_endpoint`: the task
grader's own criteria, task and pipeline together. It never reads
`installation-ready`. The baseline installs nothing, so its readiness is the
agent-observation stand-in, which is always UNKNOWN, and its stored
verified-result status can never be PASS. Comparing that status between arms
would hand the CPP arm a win from grading plumbing. Readiness is reported
beside the endpoint (`readiness_beside`), never inside it.
`tests/test_calibration.py` shows a baseline attempt that meets every task
criterion reaching primary-endpoint PASS while its verified status stays
INCONCLUSIVE.

## Owed before the run

See `owed_before_run` in the manifest: a runner for the two-arm schedule
([#207](https://github.com/cooneycw/skillc/issues/207)).
`collection-run` has no baseline (no-skill) mode and does not pin the model;
`pilot-run` is bound to the Level 1 pilot's own declaration. The run,
its calibration report (questions 1-5 in the manifest) and the go / redesign /
stop recommendation for #203 are separate, later work under #204.
