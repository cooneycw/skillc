# Low-effort check for #203: is `gate-ran-nothing` ever not at ceiling?

**Status: approved 2026-10-04, not yet run.** This is step (a) of the owner's
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
