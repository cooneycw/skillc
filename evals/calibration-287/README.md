# #287 declaration skeleton (preparation only - not approved, not a valid declaration)

Drafted per #287 acceptance item 1 ("Select the primary contract contrast and
endpoint; size repeats from measured costs and the declared uncertainty
target, not an invented large matrix") and item 5 ("leave the declaration
unapproved until explicit study authorization"). This is the skeleton, not
the declaration: every open input is an explicit `PENDING` placeholder in
`run-manifest.skeleton.json`, not a guessed value, and the file does not
parse under `skillc.calibration.parse_declaration` on purpose.

**No live model trials are authorized by this branch, this issue, or this
README.** A separately approved declaration is required under ADR 0005; the
existing #203/#237 priority ruling is unchanged (#287's own stated exclusion).

## Files

- `run-manifest.skeleton.json` - the declaration skeleton: arms (baseline,
  intact, degraded), the two Fisher's-exact contrasts it will test
  (discrimination: intact-vs-degraded; improvement: intact-vs-baseline,
  sharing the intact arm's attempts), and every still-open field named
  `PENDING` with what it is waiting on.
- `power_cost_table.py` - computes the power/cost table below. Run it to
  reproduce (`python3 evals/calibration-287/power_cost_table.py`); it writes
  `power_cost_table.json`. Exact integer arithmetic (`math.comb`), not an
  approximation.
- `power_cost_table.json` - the computed output.
- `tests/test_calibration_287_power_table.py` (repo root) - a committed
  negative control for the table's formula: a hand-verified positive case
  (n=10's breakpoint checked against independently expanded `math.comb`
  values) and a red case (a plausible off-by-one hypergeometric
  parameterization that must, and does, disagree with the correct answer at
  every declared n).

## The power/cost table

For a fixed n attempts per arm, pin the better arm (intact, or baseline in
the improvement contrast) at its most favorable observable outcome - every
attempt passes, n/n - and ask: what is the largest number of passes the
worse arm (degraded, or baseline in the discrimination contrast) can show
and still let a one-sided Fisher's exact test reach p < 0.05? Below that
count the design cannot show significance even in the best case the data
could hand it. The full derivation is in `power_cost_table.py`'s docstring.

| n/arm | best case | max worse-arm passes (p<0.05) | p at that count | p at one more pass | total attempts (3 shared arms) | worst-case quota-equiv. cost |
|---|---|---|---|---|---|---|
| 10 | 10/10 | 6/10 | 0.0433 | 0.1053 | 30 | $9.19 |
| 15 | 15/15 | 11/15 | 0.0498 | 0.1121 | 45 | $13.78 |
| 20 | 20/20 | 15/20 | 0.0236 | 0.0530 | 60 | $18.38 |
| 30 | 30/30 | 25/30 | 0.0261 | 0.0562 | 90 | $27.56 |

Reading the n=10 row: even if the intact arm passes all 10 attempts, the
degraded arm must fail at least 4 of its 10 (pass at most 6) for the
discrimination test to reach significance at all. That is a real, large
effect size requirement - not a formality - and it is why "size repeats from
measured costs and the declared uncertainty target" (acceptance item 1)
cannot be done before #270/#271 hand over an observed pass-rate gap.

**Cost basis.** 125,000 input + 15,000 output tokens/attempt (~140k total, the
assigned planning assumption for this table - not the #26/matched-pilot
figure of 55k, which predates this study and this case). Priced at
`gpt-5.1-codex`, $1.25/M input + $10.00/M output, source: pricepertoken.com,
2026-09-26 (third-party aggregator, not independently confirmed against
OpenAI's own page) - the SAME price `evals/selection-probe` and
`evals/matched-pilot` already cite, kept identical for comparability.

**This is a quota-equivalent figure, not a dollar charge (ADR 0005 rule
6).** Agent attempts (#26's and #12's treatment/baseline shape, which this
study follows) run under the operator's normal Claude Code/Codex
subscription login, not a pay-per-use API key - their token/price figures are
a usage-quota indicator for comparability only, never billed and never
compared against `skillc.cost_estimate`'s `CEILING_USD` ($5, ADR 0005 rule
6's "don't worry about the cost estimate... i expect it's under $5" ruling,
which applies to judge spend). This study, as currently scoped, enables no
judge tier (deterministic grading only, per #270/#271's bounded scope), so
there is no dollar-metered spend to gate at all - `skillc.cost_estimate.
authorize(..., agent_uses_subscription_login=True)` would return cleanly on
`judge_estimated_usd=0.0` regardless of which row above is chosen. The table
is still reported in dollar-equivalent terms because that is the unit the
$5 ceiling and every prior calibration manifest already use for
comparability, not because this spend is metered.

## Design risk 1: #150's non-discriminating result

`evals/discriminating-run` (#150) is the only live discriminating-run attempt
to date: `finish-close-ref`, one NORMAL and one DEGRADED attempt, both PASS.
Verdict: **non-discriminating**. Cause unresolved between two explanations
that evidence could not separate (transcripts were never retained for that
run): the model's default behaviour needing no CPP instruction at all, or
residual CPP content still enforcing the rule in the degraded arm (that
run's `gh-pr-merge.sh` kept its own negation-handling code even after the
prose rule was removed).

**What this means for #287:** the declaration cannot simply name a case and
a mutation; it must say, for that specific case, exactly what the degraded
arm removes, and verify - via `skillc profile diagnose` (#295, already
shipped) - that no other installed skill or helper still carries equivalent
enforcement. A repeat of #150's shape would reproduce a non-discriminating
result at whatever n the table above justifies, which spends the whole
pilot's quota to learn nothing about reliability, only that the mutation
was incomplete. This is recorded as `design_risks[0]` in the skeleton and is
exactly why `arms[].degraded.subject.revision` in the skeleton stays
`PENDING` rather than naming a plausible-looking mutation now.

## Design risk 2 (new finding, not in the original assignment): the attempts-per-arm cap

`skillc/calibration.py:70` sets `MIN_ATTEMPTS_PER_ARM, MAX_ATTEMPTS_PER_ARM =
3, 8`, enforced by `parse_declaration` at line 324-325. The power table above
shows that reaching p<0.05 at all, even in the best case, needs n=10 at the
very least against a large effect (degraded failing >=40% of its attempts),
and the #150 experience (design risk 1) suggests effects may be smaller than
that in practice. So this study may need an n the existing calibration
schema structurally refuses to accept, independent of cost or operator
approval.

This is not fixed here - #287 is preparation only, and widening a validated
cap is its own decision with its own review, not a side effect of a
declaration skeleton. Filed as a Nit Store finding on skillc's open Nit
Store issue (#20) rather than as a new ticket, since it is not yet a live
correctness/security/data-loss problem - it is a contract (the 3-8 range)
narrower than a caller (#287) now needs, to be resolved once #270/#271's
actual effect size is known and this stops being speculative.

## What is NOT yet decided, and why that is correct at this stage

Per #287's own exclusions ("No live model trials are authorized by this
issue... Existing approvals and the #203/#237 priority ruling are
unchanged"): this skeleton commits to no model, no client, no final n, and
no subject revision. Every one of those waits on #270/#271 landing a
certified case (so the task/grader/subject exist to pin) and on a separate
operator ruling authorizing pilot spend (so an observed pass-rate gap can
replace the `PENDING` placeholders in `tolerance` and `attempts_per_arm`
with real numbers, per acceptance item 1's "not an invented large matrix").
Filling those in now would be exactly the invented matrix that item warns
against.
