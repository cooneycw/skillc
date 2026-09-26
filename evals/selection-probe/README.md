# Selection probe: three predeclared cases (#26)

Probes native skill selection and non-selection - does the maintainer need to
revise the selected skills' applicability descriptions, or does the current
selection behavior already work for the tested requests? See
[docs/specs/evaluation-facility/records.md](../../docs/specs/evaluation-facility/records.md#skill-invocations-an-optional-declared-observation-39)
for the `skill-invocations` observation this probe's cases require
(`case.observes_selection: true`), and
[ADR 0005](../../docs/decisions/0005-runtime-scope-and-cost-rulings.md) rule 5
for the cost stop this directory's `run-manifest.json` observes.

- **Subject:** [cpp-codex](../subjects/cpp-codex/SUBJECT.md), the whole 74-skill
  pack, pinned at `85e9b03a`.
- **Client:** `codex`, codex-cli `0.157.1` (matching `docker/trial/pinned-versions.json`).
- **Task:** the already-qualified [slug-small-fix](../level1/slug-small-fix/README.md)
  goal and grader (#5), reused verbatim or with a short addendum below - every
  case grades the SAME public task outcome, independent of what it observes
  about selection.
- **Matched arms:** treatment (the whole pack installed) vs. baseline (nothing
  installed), the same arm shape `skillc materialize` already uses. Each case
  plans BOTH arms as its own trial - the baseline arm still needs a real,
  paid attempt (it must show no skill invoked, which needs the same live
  call the treatment arm does), so the cost estimate below counts 6 attempts
  (3 cases x 2 arms), not 3.
- **Cost ceiling:** $5.00 for the whole run (operator ruling, relayed
  2026-09-26 via master: "don't worry about the cost estimate... i expect
  it's under $5"), enforced in code by `skillc.cost_estimate.authorize` -
  refused regardless of any approved budget above it. The estimate below is
  $0.675, comfortably under.
- **Token-assumption sensitivity.** The published 50,000-input-token
  assumption reads like a single turn; a real multi-turn agentic Codex
  session re-sends its context (including the 74-skill listing) every turn,
  so real input could run 10-20x higher. At the same prices and 6 attempts:
  500,000 input tokens/attempt -> **$4.05** (still under the ceiling);
  1,000,000 input tokens/attempt -> **$7.80** (OVER the $5 ceiling -
  `authorize()` would refuse it, before any cache discount). The first live
  attempt's observed tokens replace this placeholder.

## The three cases (`cases.json`)

Published here, before any attempt runs, per this issue's own requirement to
publish allowed choices before observing results.

| Case | Prompt addendum | Applicable skill(s) | Allowed choices |
|---|---|---|---|
| `selection-probe-intended-use` | "run this project's own test suite... report the result" | `qa-test` | invoke `qa-test`; or run tests directly without it (still valid) |
| `selection-probe-near-miss` | none - the bare goal | none | invoke no skill; any invocation is a false positive |
| `selection-probe-overlapping-choice` | "check whether your change introduces any security issue" | `security-scan`, `security-deep` | either, both, or neither if judged unnecessary |

Invocation is never outcome success on its own, and a correct result without
unnecessary invocation can be valid - the grader scores the slug fix exactly
as `slug-small-fix` already does, unmodified by which of these choices an
attempt makes. Manual-only skill declarations are respected: none of the
three named skills are manual-only in the pinned CPP revision, so no case
here exercises that path (a future case would need to, if one adds it).

## What this delivers, and what it does not (#26's own "no-run" scope)

Delivered and tested (`tests/test_selection_probe.py`):

- The case format itself, extended with `case.observes_selection` (#26,
  `skillc/trial.py` and `skillc/records.py`), and #39's own last control -
  a `skill-invocations` observation is now REQUIRED, not merely optional,
  for an attempt whose trial declares it (`skillc/records.ledger_binding`).
- The three cases actually PLAN through `skillc/trial.py`'s real controller
  against a throwaway store - not a hand-written fixture standing in for it.
- `run-manifest.json`'s cost estimate, computed by `skillc/cost_estimate.py`
  from stated, clearly-labeled assumptions (no attempt has ever run against
  this subject, so there is nothing to measure yet) - and asserted equal to
  what the code computes, so the two cannot silently drift apart.
- The spend gate itself (`skillc.cost_estimate.authorize`): refuses to
  authorize execution without an approved budget, and separately refuses ANY
  estimate over the $5 operator ceiling regardless of approved budget -
  exactly as `run-manifest.json`'s own `"execution"` field states.

Explicitly NOT delivered here, per the cost stop (ADR 0005 rule 5): no paid
model call, no live agent, no image build (`image.digest` in the plan is a
named placeholder - #77's Docker backend implementation is a follow-up PR),
and no enforced time/monetary cap (the manifest's `time_caps` are stated, not
yet wired to any committed control). `execution` stays `"incomplete"` until
someone approves a budget at or above the estimate.
