# Matched pilot: live evidence (#12)

The first bounded matched pilot, run on the
[predeclared](../run-manifest.json) schedule, with **one protocol deviation**
(the model, below): does installing the whole cpp-codex pack change task
outcome or completion time on an already-qualified task?

**Answer at this size: nothing measurable.** All six attempts passed, three
per arm. The completion-time differences go both ways and are the size of
attempt-to-attempt noise. This is a first canary of six attempts. It makes
**no qualification claim and no broad-benefit claim** for the pack, and
nothing below should be quoted as one.

## What ran

- `SKILLC_ALLOW_REAL_AGENT=1 uv run --no-sync skillc pilot-run`, at commit
  `3e1e3fb`, 2026-09-27 13:26Z. Exit 0. The exported bundle was leak-checked
  (14 scanned, 0 found).
- Client: codex-cli 0.157.1 on the operator's normal subscription login (ADR
  0005 rule 6). **Observed model: `gpt-6-astra`, reasoning effort `high`**,
  read from every attempt's own rollout.
- **Protocol deviation: the model.** The manifest declared `gpt-5.1-codex`,
  but nothing in the invocation pinned it, so codex used its own default.
  All six attempts ran `gpt-6-astra`. Both arms ran the same model, so the
  comparison between them is still matched. The run is not, though, "the
  declared model", and every report entry says so
  (`model_matches_declaration: false`, and the summary's
  `protocol_deviations`). The declaration stays as written; `observed_at_run`
  in the manifest records what ran. A future pilot should pin the model in
  the invocation.
- Image `sha256:d1b2ced9...6eefc`. The manifest declared it before the run,
  and the ledger records it for all six trials. The runner now refuses any
  other image and runs by the resolved digest rather than the tag; at run
  time (`3e1e3fb`) it checked only that the digest resolved, and the
  counter-model review added the comparison afterwards.
- Subject cpp-codex at `85e9b03a`: 74 skills in the treatment arm, nothing in
  the baseline arm. The run checked the pin against the subject declaration
  before starting.
- Task `slug-small-fix` revision 2, graded by its own deterministic grader in
  a `network=none` container. No judge tier, and $0 metered.
- Order: T, B, T, B, T, B, as declared. Caps: 900 s per attempt and 5400 s in
  total. Neither was reached: the whole run took about 5 minutes.

## Every scheduled attempt

| # | arm | repeat | disposition | graded | criteria (5) | setup s | agent s | grading s | total s | input tokens | output tokens | skills invoked (heuristic) | claim | claim accurate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | treatment | 1 | captured | PASS | all SATISFIED | 13.5 | 36.5 | 0.8 | 50.8 | 101,912 | 715 | none | success | yes |
| 2 | baseline | 1 | captured | PASS | all SATISFIED | 4.4 | 51.2 | 0.8 | 56.4 | 89,413 | 716 | none | success | yes |
| 3 | treatment | 2 | captured | PASS | all SATISFIED | 9.8 | 37.1 | 2.5 | 49.4 | 101,687 | 727 | none | success | yes |
| 4 | baseline | 2 | captured | PASS | all SATISFIED | 0.7 | 40.3 | 0.8 | 41.8 | 89,573 | 765 | none | success | yes |
| 5 | treatment | 3 | captured | PASS | all SATISFIED | 14.7 | 43.2 | 0.9 | 58.8 | 102,043 | 759 | none | success | yes |
| 6 | baseline | 3 | captured | PASS | all SATISFIED | 0.6 | 38.3 | 0.7 | 39.6 | 77,438 | 719 | none | success | yes |

Interventions: 0 on every attempt, because the attempts are non-interactive
by declaration. Uncertainty per attempt is in `records/report.json`. Its only
entry is that codex skill detection is a heuristic.

**Cost.** The agent's dollar cost is `UNKNOWN` on every attempt. The runs use
a subscription login, which has no per-attempt price, so the observed tokens
stand in for it. Setup and grading are local containers with no metered call
(`0`). The committed quota estimate in the manifest is priced for
`gpt-5.1-codex` and does not apply to the observed model.

## Matched comparison (successful pairs only)

| repeat | treatment agent s | baseline agent s | treatment - baseline |
|---|---|---|---|
| 1 | 36.5 | 51.2 | -14.6 |
| 2 | 37.1 | 40.3 | -3.2 |
| 3 | 43.2 | 38.3 | +4.9 |

Median difference: -3.2 s. No attempt failed, so every repeat forms a
matched pair and no failure is set aside. No significance test was run. At
n = 3 this is a description of the sample, not an inference about the pack.

Three things are clearer than the timing:

- **The pack cost context, and the agent didn't use it.** Treatment attempts
  read about 12,000-25,000 more input tokens than baseline (the installed
  skill listing), and no attempt invoked a skill by the codex heuristic. On a
  task this small, the pack is overhead the agent did not use.
- **Setup takes longer with the pack installed** (9.8-14.7 s against
  0.6-4.4 s). This is the cost of delivering 273 skill files into the
  container, and it is a harness cost, not an agent cost.
- **Every closing claim was accurate.** Each agent said it had fixed and
  verified the helper, and each was graded PASS. Six agreeing claims can't
  show whether claims would be wrong when an attempt fails: no attempt
  failed.

## Claims review

`claims.json` records the reviewed classification of each closing message.
The messages themselves are transcript content and stay private. `skillc
pilot-report <run_dir> --claims claims.json` merged the classifications into
the report.

## Records and what `check-records` says

`records/` holds the ledger, the six lifecycle records, the six artifact
manifests and the `pilot-report`. `skillc check-records records/` passes the
`pilot-report` rule (every scheduled attempt present, well formed) and
`ledger-binding`. It reports **6 `attempt-accounting` errors, one per
attempt: "captured but has no result"**. That is a true statement, not a
formatting problem. The agent-trial driver (#106) grades through
`verify.grade_files` and does not store a `verified-result` record. Storing
one needs an installation receipt that path does not write. The grades above
come from that same grader. They are in the report, but not yet recorded as
first-class results. Tracked as
[#139](https://github.com/cooneycw/skillc/issues/139). `tests/test_matched_pilot.py` pins this as the only
finding, so any other one fails the suite, and `skillc pilot-run` refuses to
publish a bundle with any other finding.

## Raw artifacts

Per the manifest's `artifact_retention`, decided before capture: the trial
store (journals, captured objects), the per-attempt outcomes and the closing
messages are kept privately in the operator's
`~/.local/share/skillc/pilot-runs/20260927T132600Z-0c308c/`. They are not
committed, because rollouts carry account identifiers.
