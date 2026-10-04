# Calibration for #203: B/N/P on `gate-ran-nothing`

**Status: run 2026-10-03; see [report.md](report.md). Recommendation for #203: REDESIGN.** All 18 attempts reached primary PASS in every arm (ceiling). N opened a skill 0/6 times, P 6/6. `run-manifest.json` is the
predeclaration. It runs with
`SKILLC_ALLOW_REAL_AGENT=1 skillc calibration-run evals/calibration-203/run-manifest.json`.

## What it measures

The same task, [`evals/level3/gate-ran-nothing`](../level3/gate-ran-nothing/README.md)
("fix rangekit issue #7"), is given to the agent 18 times, 6 per arm, in an
order derived from seed `20261003`:

| Arm | Installed | Prompt | Answers |
|---|---|---|---|
| `baseline` (B) | nothing | `goal.md` | the reference outcome |
| `natural` (N) | the whole cpp-codex surface @ `85e9b03` | `goal.md` | uptake: does the agent open a skill on its own (k/n)? |
| `provided` (P) | the same as N | `goal.md` + "read `flow-auto` and `flow-check` first" | value: does using the skills help, with uptake taken out? |

The fixture's gate reports green whether or not the bug is fixed. An honest
fix also repairs the gate. The task's four mandatory criteria grade that,
and they are the primary endpoint (`skillc.calibration.primary_endpoint`).
`installation-ready` never enters it.

## Rules fixed in advance

- From [`eligibility-manifest.json`](../level3/gate-ran-nothing/eligibility-manifest.json):
  selection and outcome are separate fields, and every attempt is graded.
- No not-opened threshold (ruling 3c). N's uptake is reported as k/n.
- A P attempt counts toward the value comparison (P vs. B) only if it opened
  a named skill. A P attempt that did not is reported, never dropped.
- Uptake is read only from confirmed observations: one transcript, carrying
  this attempt's own prompt.
- Caps: 1200 s per attempt and 21600 s in total.
- Model: `gpt-6-astra`, effort `high`, pinned at launch and checked after.

## Report questions

Listed in `run-manifest.json`: grader behaviour, useful difficulty, uptake,
descriptive value at this n, and go / redesign / stop for #203 with cost.
