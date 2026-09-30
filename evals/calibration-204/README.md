# Calibration before comparison (#204)

**Status: declared, not approved, not run.** `run-manifest.json` is the
predeclaration for #204's two-arm calibration: **full CPP** versus **minimal
baseline** on [`evals/level3/slugkit-pipeline`](../level3/slugkit-pipeline/README.md),
4 attempts per arm, in an order derived from a recorded seed. It passes
`skillc.calibration.load_declaration`; `skillc.calibration.require_approved`
refuses it until `approval` records who approved it and when, and until no
identity still reads `UNKNOWN` (the image digest does today). ADR 0005: no
live run without recorded, approved arms, identities, schedule and caps.

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

## Owed before the run is approved

See `owed_before_approval` in the manifest: the image digest, a re-check of
the subject and client pins, and a runner for the two-arm schedule - now
`skillc calibration-run evals/calibration-204/run-manifest.json` (#207), which
refuses this declaration until it is approved. The run,
its calibration report (questions 1-5 in the manifest) and the go / redesign /
stop recommendation for #203 are separate, later work under #204.
