# Matched pilot: the predeclared experiment (#12)

**Current declaration: [`run-manifest-2026-09-27-gpt-6-astra.json`](run-manifest-2026-09-27-gpt-6-astra.json)**
(issue #141). `skillc pilot-run` uses it by default
(`skillc.matched_pilot.CURRENT_MANIFEST_PATH`). It pins the model at launch:
`gpt-6-astra` at reasoning effort `high`, passed to codex as
`-m gpt-6-astra -c model_reasoning_effort="high"`. It supersedes
[`run-manifest.json`](run-manifest.json), #12's own predeclaration, and the
run made under it. That file is not edited. It declared `gpt-5.1-codex`,
nothing passed that to the client, and all six attempts ran `gpt-6-astra`.
The deviation stays on the record as it happened. Everything else the new
declaration states is #12's, unchanged (`tests/test_matched_pilot.py` checks
this). It has not been run yet.

How the pin is enforced:
- `pilot-run` refuses a `--client-argv` that chooses the model or its effort
  itself (`-m`, `--model`, `-c model=...`, `-p`/`--profile`, `--oss`, ...),
  before any run directory is made.
- After each attempt, the model in the client's own rollout must equal the
  declared one. An attempt with another model, or with no observed model, is
  recorded as `model_eligible: false`, left out of the matched pairs, and
  listed under `model_ineligible`. The run exits 1.
- The run directory records the model it declared. `pilot-report` scores the
  run against that model, never against whichever declaration is current
  later.

The next change of pin is a new dated declaration and a one-line change of
`CURRENT_MANIFEST_PATH`, never an edit to a declaration that has already run.

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
  for a subscription-login agent run (`skillc/credential.py`,
  `docker_backend.DockerBackend.deliver_home_file`/`read_home_file`, issue
  #98), the agent trial driver (#106) and `skillc pilot-run` (#12) are
  built, and the pilot has run (see [evidence/](evidence/README.md)).
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

**Run (2026-09-27, #12's own PR):** `skillc pilot-run`
(`skillc/matched_pilot.py`) runs this schedule as declared. It checks the
pins, enforces both time caps, and exports a leak-checked bundle. The live
run and its results are in [evidence/](evidence/README.md): all 6 attempts
passed, there's no measurable difference between the arms at this size, and
the report makes no broad-benefit claim. Two things the planning PR could
not know are now recorded under `observed_at_run` in `run-manifest.json`:
- the model is `gpt-6-astra`, not the assumed `gpt-5.1-codex`;
- input tokens ran 77k-102k per attempt, not the assumed 50k.

Still not delivered: a stored `verified-result` per attempt for THIS run. The
agent path stores one since #139, but this run predates that, and its ledger
pins no grader digest, so its results cannot be stored after the fact. A clean
bundle needs a new run; the evidence README states the gap.

## If the judge-call estimate for a larger population would exceed $5

Do not shrink the population to fit under the ceiling. Report the estimate
and stop. Judge calls are not enabled for this pilot, so there is currently
no dollar-metered spend to check against the ceiling; the agent-attempt
quota (0.675 quota-usd-equivalent for 6 attempts) is informational only
under ADR 0005 rule 6 and is never checked against it. The committed
sensitivity lines show where that quota figure would have crossed $5 had it
still been dollar-metered (roughly 1,000,000 assumed input tokens per
attempt) - kept for comparability, not because it is gated.
