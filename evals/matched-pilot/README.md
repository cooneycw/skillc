# Matched pilot: the predeclared experiment (#12)

The first bounded matched pilot skillc's own acceptance requires: does the
whole CPP pack help on an already-qualified task, and how much does it cost
in time? See [ADR 0005](../../docs/decisions/0005-runtime-scope-and-cost-rulings.md)
rule 5 for the cost stop this directory's `run-manifest.json` observes, rule 6
for the subscription-login ruling below, and
[the selection probe](../selection-probe/README.md) (#26) for the sibling
pilot this one deliberately reuses the estimator and manifest shape from -
this pilot does **not** fork a second cost estimator.

- **Subject:** [cpp-codex](../subjects/cpp-codex/SUBJECT.md), the whole
  74-skill pack, pinned at `85e9b03a` - the same pin #26 uses.
- **Client:** `codex`, codex-cli `0.157.1`, under the operator's normal
  Codex CLI **subscription login** (the normal rotating OAuth login, never a
  long-lived key) - not a pay-per-use API key (ADR 0005 rule 6, owner ruling
  2026-09-27: "Normal Claude and codex"). The in-container credential path
  for a subscription-login agent run (issue #98) is not yet built; that is
  the real remaining blocker, not a dollar gate.
- **Task:** the already-qualified [slug-small-fix](../level1/slug-small-fix/README.md)
  goal and grader (#5), used verbatim - unlike #26, this pilot measures
  task-outcome benefit and completion time, not selection behavior, so there
  is no prompt addendum.
- **Matched arms:** treatment (the whole pack installed) vs. baseline
  (nothing installed) - 3 repeats per arm, 6 attempts total, a small first
  pilot rather than a full-power study.

## What this delivers, and what it does not (#12's own "planning PR" scope)

Delivered and tested (`tests/test_matched_pilot.py`):

- The predeclared experiment record (`run-manifest.json`'s
  `predeclared_experiment_record`): exact model/client/subject identities,
  the image digest named explicitly as **owed to the live build** rather than
  invented, the goal population (the reused `slug-small-fix` grader), the
  treatment-vs-baseline definition, the repeat schedule and arm order, time
  and monetary caps (the same $5 operator ceiling #26 uses), and stated
  clarification/approval behavior.
- The pilot actually PLANS through `skillc/trial.py`'s real controller
  against a throwaway store - 6 trials (2 arms x 3 repeats), not a
  hand-written fixture standing in for it.
- **The agent-attempt quota (not a dollar charge).** ADR 0005 rule 6's
  subscription-login ruling covers these agent attempts, computed by the
  SAME `skillc/cost_estimate.py` #26 uses (no second estimator): 0.675
  quota-usd-equivalent at the stated 50,000-input-token assumption, with the
  same sensitivity lines as #26's probe (4.05 at 500,000, 7.80 at
  1,000,000) - the first live attempt's observed tokens replace the
  placeholder. Never billed, never compared against the $5 ceiling; judge
  calls, which the ruling does not cover, would be (none are enabled here).
- **The evidence-report schema** (#12's acceptance: "Report every scheduled
  attempt by protocol disposition, per-criterion success, uncertainty, claim
  accuracy, intervention counts, time and observed cost with missing values
  explicit"): a new `pilot-report` record kind (`skillc/records.py`), whose
  own rule checks each attempt's disposition, per-criterion outcomes,
  uncertainty, intervention count, and a cost/time split into setup, agent
  and grading - each split value either a non-negative number or the
  explicit literal `"UNKNOWN"`, never a silently absent key. `ledger_binding`
  separately refuses a report that omits an attempt the ledger scheduled, or
  names one it never planned - the committed control this issue's acceptance
  names explicitly (`controls/ledger-binding/{bad,good}/pilot-report-*`).

Explicitly NOT delivered here, per "keep runtime implementation out of the
planning PR" (#12's own text), the cost stop (ADR 0005 rule 5), and the
in-container credential prerequisite (rule 6, issue #98): no live agent
attempt, no image build, no report GENERATOR (the schema is defined and
validated; producing a real report needs a real run), and no enforced
time/monetary cap at runtime (stated, not yet wired to a running meter - the
same gap #26's manifest already names for its own time caps). `execution`
stays `"incomplete"` until #98's in-container credential path and
`skillc/trial.py`'s real execution loop both exist - not blocked on a dollar
budget, since this pilot enables no judge tier. A judge-call spend over the
$5 ceiling would still be refused regardless of any approved budget, exactly
as before.

## If the judge-call estimate for a larger population would exceed $5

Do not shrink the population to fit under the ceiling. Report the estimate
and stop. Judge calls are not enabled for this pilot, so there is currently
no dollar-metered spend to check against the ceiling; the agent-attempt
quota (0.675 quota-usd-equivalent for 6 attempts) is informational only
under ADR 0005 rule 6 and is never checked against it. The committed
sensitivity lines show where that quota figure would have crossed $5 had it
still been dollar-metered (roughly 1,000,000 assumed input tokens per
attempt) - kept for comparability, not because it is gated.
