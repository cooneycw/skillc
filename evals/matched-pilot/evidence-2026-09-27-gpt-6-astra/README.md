# Matched pilot, re-run with the model pinned: live evidence (#147, for #12)

The #12 matched pilot, run again under the dated declaration
[`run-manifest-2026-09-27-gpt-6-astra.json`](../run-manifest-2026-09-27-gpt-6-astra.json).
The question is the same: does installing the whole cpp-codex pack change task
outcome or completion time on an already-qualified task? This time the run
matches its declaration exactly, with **no protocol deviation**, and its
records check fully clean.

**Answer at this size: nothing measurable, again.** All six attempts passed,
three per arm. The completion-time differences go both ways and are the size
of attempt-to-attempt noise. This is a canary of six attempts, and it makes
**no qualification claim and no broad-benefit claim** for the pack.

The first run (2026-09-27, [`../evidence/`](../evidence/README.md), experiment
`matched-pilot-6ab82dc6`) is superseded but kept as it was: its model
deviation and its pre-#139 records stay on the record.

## What ran

- `SKILLC_ALLOW_REAL_AGENT=1 uv run --no-sync skillc pilot-run --manifest
  evals/matched-pilot/run-manifest-2026-09-27-gpt-6-astra.json --evidence
  evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/records`, from the #147
  branch at `4eed059` (main `2b60616` plus the replace-another-experiment
  guard), 2026-09-28 08:31Z.
- The run exited 0 and took about 5 minutes. Experiment `matched-pilot-64396611`.
- Client: codex-cli 0.157.1 on the operator's normal subscription login (ADR
  0005 rule 6). No judge tier, $0 metered.
- **Model: `gpt-6-astra`, reasoning effort `high`, on all six attempts**, as
  declared. Both were passed at launch (`-m gpt-6-astra -c
  model_reasoning_effort="high"`, #141) and read back from each attempt's own
  rollout. This run is the first live proof that codex 0.157.1 honours both
  flags. `protocol_deviations: []` and `model_ineligible: []`.
- Image `sha256:d1b2ced9...6eefc`, as declared, for all six trials. The
  grader is pinned by digest in the ledger (#139).
- Subject cpp-codex at `85e9b03a`: 74 skills in the treatment arm, nothing in
  the baseline arm. Task `slug-small-fix` revision 2. Order T, B, T, B, T, B.
  Caps: 900 s per attempt, 5400 s in total. Neither was reached.

## Every scheduled attempt

| # | arm | repeat | disposition | graded | criteria | setup s | agent s | grading s | total s | input tokens | output tokens | skills invoked (heuristic) | claim | claim accurate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | treatment | 1 | captured | PASS | 5/5 SATISFIED | 7.9 | 41.4 | 0.7 | 50.0 | 102,388 | 832 | none | success | yes |
| 2 | baseline | 1 | captured | PASS | 5/5 SATISFIED | 0.5 | 37.6 | 0.7 | 38.9 | 89,660 | 779 | none | success | yes |
| 3 | treatment | 2 | captured | PASS | 5/5 SATISFIED | 7.6 | 40.2 | 0.7 | 48.5 | 102,296 | 777 | none | success | yes |
| 4 | baseline | 2 | captured | PASS | 5/5 SATISFIED | 0.5 | 46.0 | 0.7 | 47.2 | 75,082 | 924 | none | success | yes |
| 5 | treatment | 3 | captured | PASS | 5/5 SATISFIED | 7.7 | 37.6 | 0.7 | 46.0 | 102,241 | 760 | none | success | yes |
| 6 | baseline | 3 | captured | PASS | 5/5 SATISFIED | 0.5 | 42.3 | 0.8 | 43.5 | 89,741 | 884 | none | success | yes |

- **Interventions:** 0 on every attempt. None asked a clarifying question.
- **Uncertainty:** each entry notes only that codex skill detection is a
  heuristic.
- **Model and effort:** `model_matches_declaration` and
  `reasoning_effort_matches_declaration` are `true` on every entry.

**Graded PASS, stored INCONCLUSIVE.** Each attempt's stored
`verified-result` (#139) has status INCONCLUSIVE, while the report's
`graded_status` is PASS. The two answer different questions, and neither is a
failure:

- `graded_status` is the TASK grade: the fixture's five criteria, all satisfied.
- The stored result also carries an `installation-ready` criterion. The agent
  path can't establish it (there is no installation receipt), so it is
  UNKNOWN, and one UNKNOWN mandatory criterion makes the derived status
  INCONCLUSIVE.

**Cost.** The agent's dollar cost is `UNKNOWN`. The subscription login has no
per-attempt price, so the observed tokens stand in for it. Setup and grading
are local containers with no metered call.

## Matched comparison (successful pairs only)

| repeat | treatment agent s | baseline agent s | treatment - baseline |
|---|---|---|---|
| 1 | 41.4 | 37.6 | +3.7 |
| 2 | 40.2 | 46.0 | -5.8 |
| 3 | 37.6 | 42.3 | -4.6 |

Median difference: -4.6 s. No attempt failed, so every repeat is a matched
pair. No significance test was run. At n = 3 this describes the sample; it
doesn't support an inference about the pack.

The pattern matches the first run:

- **The pack costs context, and no use of it was detected.** Treatment
  attempts read about 12,500-27,300 more input tokens than baseline (the
  installed skill listing). The codex heuristic detected no skill invocation
  on any attempt. That is not proof of non-use: the heuristic only sees a
  `SKILL.md` read through an `exec` call, and misses other reader tools and
  relative paths.
- **Setup takes longer with the pack installed** (7.6-7.9 s against about
  0.5 s). This is the cost of delivering 273 skill files, a harness cost
  rather than an agent cost.
- **Every closing claim was accurate.** With no failed attempt, six accurate
  claims say nothing about claims on failures.

## Records and what `check-records` says

`records/` holds 26 records: the ledger, and six each of lifecycle, artifact
manifest, agent observation and verified result, plus the `pilot-report`.

**`skillc check-records records/` reports 0 errors.** This bundle is not in
`matched_pilot.KNOWN_GAP_EXPERIMENTS`; that tolerance covers only the first
run's `matched-pilot-6ab82dc6`. `tests/test_matched_pilot.py` pins both
facts.

## Claims review

`claims.json` records the reviewed classification of each closing message.
The messages themselves are transcript content and stay private. `skillc
pilot-report <run_dir> --claims claims.json` merged the classifications into
the report, as a re-export of the same experiment.

## Raw artifacts

Per the declaration's `artifact_retention`, committed before the run in
`4eed059`: the trial store, the per-attempt outcomes and the closing messages
are kept privately in the operator's
`~/.local/share/skillc/pilot-runs/20260928T083132Z-0db97e/`. They are not
committed, because rollouts carry account identifiers.
