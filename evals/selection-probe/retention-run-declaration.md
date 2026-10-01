# Selection probe: detection control + transcript retention, combined (#26)

Declared under [ADR 0005](../../docs/decisions/0005-runtime-scope-and-cost-rulings.md)
rule 5, before any paid invocation. Operator ruling: #203, decisions 2 and 5
("yes"/"yes"), recorded verbatim at
https://github.com/cooneycw/skillc/issues/203#issuecomment-5940026476 - #26's
smallest remaining live attempt runs first (before any #203 candidate) and is
approved.

## What this run adds

#143 (the `--detection-control` command) and #163 (transcript retention) have
each shipped, but the detection control's own live run (`evidence/README.md`
§2, 2026-09-27) predates #163, so the two have never been exercised in the
SAME attempt - this is #26's own stated "still owed" item.

No code or flag change is needed to close it. `AgentTrialRunner.__call__`
(`skillc/selection_probe.py`) has passed `retain_transcript=True`
unconditionally on every attempt since #163 merged, so the first run of
`SKILLC_ALLOW_REAL_AGENT=1 skillc selection-probe --detection-control` on
current main IS the combined run - there is no separate "retention mode" to
opt into.

## Declared identities (ADR 0005 rule 5)

- **Client:** `codex`, codex-cli `0.157.1` (`docker/trial/pinned-versions.json`,
  unchanged), under the operator's normal ChatGPT/Codex subscription login
  (OAuth), never an API key (ADR 0005 rule 6).
- **Subject:** `cpp-codex` @ `85e9b03ad2af1c41020ff6d92d36fa257bdacd2b`, the
  whole 74-skill pack (`evals/subjects/cpp-codex/subject.json`), unchanged
  from the prior run.
- **Image:** `skillc-trial:latest`; the digest is resolved at run time
  (`docker inspect`), as the prior run did - no new image is declared here.
- **Goal population:** the detection-control declaration only
  ([`detection-control.json`](detection-control.json), revision `d1`,
  unchanged) - the single `selection-probe-intended-use` base case, canary
  named `qa-test`. This is a control, not a selection result (its own
  `_comment` field is explicit about this).
- **Arms:** treatment (the collection installed) vs. baseline (nothing
  installed), per `detection-control.json`.
- **Repeat schedule:** 1 attempt/arm, 2 attempts total, per
  [`run-manifest.json`](run-manifest.json)'s `repeat_schedule` (unchanged) -
  #26 names no reason to repeat this control.
- **Arm order:** treatment then baseline, per `run-manifest.json`.
- **Per-attempt / total time caps:** 900s / 5400s
  (`run-manifest.json.time_caps`, unchanged) - stated, not yet enforced by any
  committed control, the same caveat the original manifest already carries.
- **Monetary ceiling:** $5 (ADR 0005 rule 6, `skillc.cost_estimate.authorize`).
  Trivially satisfied: no judge tier is enabled for this probe (judge spend is
  $0), and the agent attempts themselves run under the subscription-login
  ruling, so they are a usage/quota figure, never dollar-metered or compared
  against this ceiling.

## Prepared without spending anything

- **An empty attempt ledger**, produced by calling the REAL planning path -
  `selection_probe.load_cases`, `load_detection_control`,
  `detection_control_cases`, `plan_selection_probe`, which calls
  `trial.plan()` - against this unchanged declaration, with clearly-labelled
  placeholder digests (`sha256:aa...`/`bb...`/`cc...`) standing in for the
  values a real `materialize`/`docker inspect` call would supply. Produced a
  real `ledger.json` with two planned trials
  (`t1-intended_use_treatment`, `t2-intended_use_baseline`), one attempt each,
  zero results recorded - exactly the shape a live run's own planning step
  would produce, with none of its side effects. Not committed here, matching
  the existing precedent that per-run observation records and ledgers live in
  the operator's own run store, never in the repository.
- **A dry run exercising everything except the paid call:** `tests/test_
  selection_probe.py`'s existing 58 tests (`uv run pytest tests/test_
  selection_probe.py`, all passing), which already plan every case and the
  detection control through this same real controller against a fake backend
  and a scripted (non-billing) client, and assert the manifest's cost
  estimate matches what `skillc/cost_estimate.py` computes. There is no
  dedicated `--dry-run` flag on `skillc selection-probe` itself; this
  existing suite is the closest equivalent tooling already provides.

## Execution

Incomplete. Requires an environment with a Docker daemon, as #26's prior
live runs used, and the operator's own subscription login (ADR 0005 §6).
The subject-environment check is performed at run time, before the first
attempt.
