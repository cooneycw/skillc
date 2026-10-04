# Low-effort check for #203: is `gate-ran-nothing` ever not at ceiling?

**Status: run 2026-10-04, 12:26-12:36Z; still at ceiling. Next: #203 Q2 step
(b), a harder task.** This is step (a) of the owner's
#203 Q2 ruling ("c": lower the effort first, then a harder task if needed).

`evals/calibration-203` put every arm at ceiling: 18/18 primary PASS at
reasoning effort `high`. This check reruns the same task, model, image and
subject with effort `low`. It uses two arms, `baseline` and `natural`, 3
attempts each in seed-`20261004` order: the smallest declaration
`calibration-run` accepts.

- **If either arm falls below PASS:** the task can discriminate at `low`, and
  a full B/N/P declaration at `low` follows for approval.
- **If both stay 3/3:** the task is too easy at either effort. Build a harder
  task (#203 Q2 step b).

Run with
`SKILLC_ALLOW_REAL_AGENT=1 skillc calibration-run evals/calibration-203-low/run-manifest.json`.

## Result

- **Command:** `SKILLC_ALLOW_REAL_AGENT=1 skillc calibration-run evals/calibration-203-low/run-manifest.json`,
  exit 0, from a fresh clone at the declared commit `2d6e452`.
- **Experiment:** `calibration-9063f8d6`.
- **Model:** `gpt-6-astra`, with effort `low` observed on all 6 attempts.

| Arm | Primary PASS | Opened a skill | Mean agent time | Mean tokens |
|---|---|---|---|---|
| `baseline` | 3/3 | - | ~70 s | ~172k |
| `natural` | 3/3 | 0/3 | ~85 s | ~203k |

- **Still at ceiling** at effort `low`: the baseline found and fixed the
  broken gate every time. `gate-ran-nothing` does not discriminate for this
  model at either effort, so the next step is a harder task (#203 Q2 step b).
- **Natural uptake** is now 0/13 across #204, `calibration-203` and this run.
- **All 6 transcripts were retained** (`coverage: complete`), against 0 of 18
  in `calibration-203`. This is #235's fix (PR #239) working on a live run.

