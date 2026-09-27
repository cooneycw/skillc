# Selection probe: three predeclared cases (#26)

Probes native skill selection and non-selection - does the maintainer need to
revise the selected skills' applicability descriptions, or does the current
selection behavior already work for the tested requests? See
[docs/specs/evaluation-facility/records.md](../../docs/specs/evaluation-facility/records.md#skill-invocations-an-optional-declared-observation-39)
for the `skill-invocations` observation this probe's cases require
(`case.observes_selection: true`), and
[ADR 0005](../../docs/decisions/0005-runtime-scope-and-cost-rulings.md) rule 5
for the cost stop this directory's `run-manifest.json` observes, and rule 6
for the subscription-login ruling below.

- **Subject:** [cpp-codex](../subjects/cpp-codex/SUBJECT.md), the whole 74-skill
  pack, pinned at `85e9b03a`.
- **Client:** `codex`, codex-cli `0.157.1` (matching `docker/trial/pinned-versions.json`),
  under the operator's normal Codex CLI **subscription login** (the normal
  rotating OAuth login, never a long-lived key) - not a pay-per-use API key
  (ADR 0005 rule 6, owner ruling 2026-09-27: "Normal Claude and codex"). The
  in-container credential path for a subscription-login agent run (issue #98)
  is not yet built; that is the real remaining blocker, not a dollar gate.
- **Task:** the already-qualified [slug-small-fix](../level1/slug-small-fix/README.md)
  goal and grader (#5), reused verbatim or with a short addendum below - every
  case grades the SAME public task outcome, independent of what it observes
  about selection.
- **Matched arms:** treatment (the whole pack installed) vs. baseline (nothing
  installed), the same arm shape `skillc materialize` already uses. Each case
  plans BOTH arms as its own trial - the baseline arm still needs a real
  attempt (it must show no skill invoked, which needs the same live call the
  treatment arm does), so the population below counts 6 attempts (3 cases x
  2 arms), not 3.
- **Agent-attempt quota (not a dollar charge).** ADR 0005 rule 6's
  subscription-login ruling covers these agent attempts, so the figure below
  is a usage/quota indicator computed at public per-token prices for
  comparability, never billed: 0.675 quota-usd-equivalent for 6 attempts at
  the stated token assumption. It is never compared against the $5 ceiling.
- **Judge-call cost (dollar-metered, if ever enabled).** The ruling does NOT
  cover judge calls - `mcp-second-opinion` (#69) uses provider API keys and
  stays dollar-metered, subject to the $5 ceiling, enforced by
  `skillc.cost_estimate.authorize`. No judge tier is enabled for this probe,
  so judge spend is $0.
- **Token-assumption sensitivity.** The published 50,000-input-token
  assumption reads like a single turn; a real multi-turn agentic Codex
  session re-sends its context (including the 74-skill listing) every turn,
  so real input could run 10-20x higher. At the same prices and 6 attempts:
  500,000 input tokens/attempt -> **4.05** quota-usd-equivalent;
  1,000,000 input tokens/attempt -> **7.80** quota-usd-equivalent. Neither
  crosses the $5 ceiling, because the ceiling gates judge spend, not this
  quota figure. The first live attempt's observed tokens replace this
  placeholder.

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
  authorize any dollar-metered (judge) spend without an approved budget, and
  separately refuses ANY such spend over the $5 operator ceiling regardless
  of approved budget. Under ADR 0005 rule 6's subscription-login ruling, this
  probe's agent-attempt quota is not dollar-metered and needs no budget
  approval by itself - a committed control in `tests/test_cost_estimate.py`
  proves a large agent quota with under-ceiling judge spend is authorized,
  and judge spend over the ceiling is refused regardless of the agent quota.

Explicitly NOT delivered here, per the cost stop (ADR 0005 rule 5) and the
in-container credential prerequisite (rule 6, issue #98): no live agent
attempt, no image build (`image.digest` in the plan is a named placeholder -
#77's Docker backend implementation is a follow-up PR), and no enforced
time/monetary cap (the manifest's `time_caps` are stated, not yet wired to
any committed control). `execution` stays `"incomplete"` until #98's
in-container credential path and `skillc/trial.py`'s real execution loop
both exist - not blocked on a dollar budget, since this probe enables no
judge tier.
