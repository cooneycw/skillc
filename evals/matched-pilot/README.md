# Matched pilot: the predeclared experiment (#12)

The first bounded matched pilot skillc's own acceptance requires: does the
whole CPP pack help on an already-qualified task, and how much does it cost
in time? See [ADR 0005](../../docs/decisions/0005-runtime-scope-and-cost-rulings.md)
rule 5 for the cost stop this directory's `run-manifest.json` observes, and
[the selection probe](../selection-probe/README.md) (#26) for the sibling
pilot this one deliberately reuses the estimator and manifest shape from -
per the orchestrator's explicit instruction, this pilot does **not** fork a
second cost estimator.

- **Subject:** [cpp-codex](../subjects/cpp-codex/SUBJECT.md), the whole
  74-skill pack, pinned at `85e9b03a` - the same pin #26 uses.
- **Client:** `codex`, codex-cli `0.157.1`.
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
- The cost estimate, computed by the SAME `skillc/cost_estimate.py` #26
  uses (no second estimator), with the same sensitivity lines: $0.675 at the
  stated 50,000-input-token assumption, $4.05 at 500,000, $7.80 (over the
  ceiling) at 1,000,000 - the first live attempt's observed tokens replace
  the placeholder.
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
planning PR" (#12's own text) and the cost stop (ADR 0005 rule 5): no paid
model call, no live agent, no image build, no report GENERATOR (the schema is
defined and validated; producing a real report needs a real run), and no
enforced time/monetary cap at runtime (stated, not yet wired to a running
meter - the same gap #26's manifest already names for its own time caps).
`execution` stays `"incomplete"` until someone approves a budget at or above
the estimate, and never above the $5 ceiling regardless.

## If the estimate for a larger population would exceed $5

Per the orchestrator's explicit instruction: do not shrink the population to
fit under the ceiling. Report the estimate and stop. This pilot's own
6-attempt population is comfortably under ($0.675), but the committed
sensitivity lines show plainly where that stops being true (over $5 at
roughly 1,000,000 assumed input tokens per attempt) - a future repeat-count
increase must re-check this, not assume it still holds.
