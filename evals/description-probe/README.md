# Description screening probe: agreement check (#238)

**Status: run 2026-10-06; see [report.md](report.md). AGREES:** every cell's majority
verdict matches #237's full runs (max rate difference 0.1), with both directions shown.
6 of 40 attempts did not run (the total cap left no room for setup overhead).

The probe is #238's cheap selection screen: an `uptake-study` attempt cut off
at **45 s** (`probe.cutoff_seconds`, equal to `shared.per_attempt_seconds`).
Selection is read from the transcript the agent wrote before the cut-off:
- in #237, every observed selection came within 31 s and 3 tool calls;
- an attempt with no tool call by the cut-off is **undecided**, never "not
  selected";
- the task grade is not measured.

Before the probe replaces full runs, it must reproduce #237's full-run
results on the same conditions:

| Run | Arms | Full-run reference |
|---|---|---|
| `agreement-broad/` | published vs "Use before you report a change as done ..." | published 0/20 and 0/10; broad 20/20 and **9/10** |
| `agreement-selective/` | published vs "Use when you are asked to run ..." | published 0/20 and 0/10; selective 20/20 and **0/10** |

Each run is 5 attempts per cell, 20 attempts in total.

**Agreement criterion, declared in advance:** every cell's majority verdict
matches the full run, and no cell's probe rate differs from the full run's by
more than 0.4. Both directions must show: the broad rewrite over-selecting on
near-miss, and the selective one not. A probe that only ever says "no" fails.

```bash
skillc degrade-subject cpp-codex --checkout <cpp at 85e9b03> --override-file flow-check:SKILL.md=<override> --out <runs>/<name>
SKILLC_ALLOW_REAL_AGENT=1 skillc uptake-study evals/description-probe/<name>/run-manifest.json --rewritten <runs>/<name>
```
