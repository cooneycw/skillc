# Screening-probe agreement check (#238): the probe agrees with full runs

**Run 2026-10-06, 10:13-10:44Z. Result: AGREES.** On every cell, the 45 s
probe's majority verdict matches #237's full-run result. No cell's rate
differs from the full run's by more than 0.1 (the criterion allowed 0.4).
It shows both directions: the broad rewrite over-selecting on near-miss
(5/5), and the selective rewrite not (0/5).

## Run

- **Command:** two `skillc uptake-study` runs with `probe.cutoff_seconds: 45`,
  from a fresh clone at PR #310's head `1ef3003`, which is the commit that
  merged.
- **Experiments:** `uptake-1e827527` (published vs broad) and
  `uptake-af5eda18` (published vs selective).
- **Identities:** codex-cli 0.157.1, `gpt-6-astra` effort `high`, image
  `sha256:eb17e8c7…`.
- **Integrity:** every attempt that ran was confirmed and model-eligible, and
  **every one acted before the cut-off**. None was undecided by the probe's
  own rule: no zero-call, pending-call or unrecognized-type cases.

## Results against the full-run answer key

| Description | Case | Full run (#237) | Probe (45 s) | Match |
|---|---|---|---|---|
| published | intended-use | 0/20 | 0/4, then 0/4 | yes |
| published | near-miss | 0/10 | 0/4, then 0/4 | yes |
| broad ("Use before you report a change as done ...") | intended-use | 20/20 | 4/4 | yes |
| broad | near-miss | 9/10 | 5/5 | yes (0.9 vs 1.0) |
| selective ("Use when you are asked to run ...") | intended-use | 20/20 | 4/4 | yes |
| selective | near-miss | 0/10 | 0/5 | yes |

Mean probe wall time was about 46 s per attempt, including container setup,
against about 60-80 s for full attempts. Most tokens in a full attempt come
after the selection point, so the probe is cheaper still in tokens.

## Deviation: 6 of 40 scheduled attempts never ran

Each run declared `total_seconds = 20 × 45 = 900`, with no allowance for
per-attempt setup and grading overhead (about 10 s). The total cap stopped
each run after 17 of its 20 attempts. The 6 attempts are `not-run`, with the
runner's note "total time cap reached". **They are not probe results.** The
table above uses the 34 attempts that ran.

The run report's `undecided=3` counter included those `not-run` attempts. A
never-run attempt has no transcript, so it fell into "undecided". That
conflates two different things, and I record it separately. The cell
counts are unaffected: neither kind enters a denominator.

## Verdict for #238

The probe may stand in for full attempts **as a screen**, for selection on
this kind of case. #238's design still confirms any winning description once,
with full attempts, on held-out cases.

Next follow-ups:
- **The total cap must budget for overhead.** For a probe it should be at
  least `attempts × (cutoff + 30 s)`.
- **`not-run` must be reported separately from `undecided`.**
