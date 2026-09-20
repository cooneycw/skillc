# Evaluation protocol

- Status: Planning baseline, not an implemented runner or wire schema
- Date: 2026-09-20
- Governing scope: [Specification](spec.md)
- Record ownership and conformance: [Interface contracts](interfaces.md)

## 1. Prepare the experiment before observing results

Record the hypothesis, task population, applicability/exclusions, subject and
baseline identities, client/model configuration, resource budgets, repeat count,
stopping policy and grader revision. Report a single task as a bounded probe;
reserve claims about broader capability for representative task families.

The goal is the agent-facing request. Acceptance specifies the result that counts
as success. A goal alone, such as "make the project better", is not a reproducible
benchmark without a fixture, constraints and observable success criteria.

Keep development examples distinct from held-out task variations. Held-out tests
must check published requirements and accept valid alternative solutions. Check
the starting fixture fails the intended completion test and a reference outcome
passes before asking a model to solve it.

## 2. Comparison arms

| Experiment | Fixed conditions | Deliberate difference |
|---|---|---|
| Revision regression | Tasks, evaluator, client/model, environment and budget | Subject revision |
| Scaffolding benefit | Tasks, ordinary project requirements, evaluator, client/model, tools and budget | Selected scaffold or minimal baseline |
| Collection comparison | Common eligible tasks and matched configuration | Collection A versus B |
| Single-skill ablation | Otherwise identical scaffold and task | One identified skill or instruction treatment |
| Detection control | Same grader and relevant fixture | A known-bad artifact or documented degraded variant |

Do not compare a restricted baseline with an unrestricted candidate and attribute
the difference to skills. If required capabilities make matched arms impossible,
report a compatibility/product comparison rather than a causal benefit claim.
Additional model calls made by scaffolding count toward the same declared budget.

Use a clean environment and fresh conversation for each independent trial. Reset
persistent client memory and caches that could carry task answers across arms.
Any intentional memory study is a different, declared experiment.

Interleave/randomize arm order where practical. Record provider/model identities
and time of execution; model services can change despite a stable display name.
Seeds, where supported, are useful metadata but do not promise determinism.

## 3. Trial lifecycle

1. Resolve immutable subject, task, grader and environment identities.
2. Validate compatibility, scope, trial count and budgets. Empty selections refuse.
3. Prove the grader on correct and deliberately incorrect outcomes.
4. Prepare the isolated environment and observe the selected installation.
5. Invoke the actual client, providing the goal and declared interaction policy.
6. Observe tool events, interruptions, costs and stopping conditions externally.
7. Retain final artifacts and partial evidence, then run independent grading.
8. Classify the result and emit a record even when setup or execution failed.
9. Clean up only resources owned by this trial; retain teardown failures separately.

If installation is itself the case's goal, installation failure is evaluated as
task failure. If a missing facility dependency prevents an unrelated task, use
the infrastructure classification. Predeclare this role of setup in the case.

Stopping because the agent consumed its task budget is a failed completion, not
an excuse to omit the attempt. Operator cancellation or a facility malfunction
without enough grading evidence is inconclusive, with its reason retained.

## 4. Result semantics

Store execution status and per-criterion outcomes as well as the overall label.
A hard observed violation remains visible even if another criterion could not
be evaluated. Mandatory constraints cannot be averaged away by optional quality.

| Label | Meaning | Example |
|---|---|---|
| PASS | All mandatory acceptance is observed and satisfied | Independent functional and constraint checks pass |
| FAIL | A mandatory violation is observed, or task budget expires before required completion | Records lost; unauthorized action; incomplete result at the deadline |
| UNAVAILABLE | An identified dependency prevents execution or grading without an already-established task failure | Selected client missing or provider unreachable |
| INCONCLUSIVE | Evidence is incomplete/conflicting or the measurement itself failed | Grader crashed, trace lost, or operator cancelled before a conclusion |
| NOT_RUN | A planned trial was not started | Overall experiment budget prevented scheduling it |

A grader crash is not a detected subject defect. A process exiting zero without
required evidence is not PASS. A model declaring its own success is not grading.
Numeric scores, if later used, retain these labels instead of mapping unknown
states into successful or unsuccessful task scores without explanation.

Unsupported tasks excluded before scheduling are reported in the selection
ledger. They are not hidden failed trials and are not counted as passed tasks.

## 5. Graders and their controls

Use deterministic checks for functional outcomes, state preservation and explicit
boundaries. Use observed events for properties such as approval preceding edits
or a new file appearing in review input. Phrase matching can locate a claim but
cannot establish that the claimed action happened.

For subjective quality, publish the rubric, keep judge configuration stable,
blind the judge to treatment identity where feasible, and calibrate with human
review. Retain disagreements. A judgment cannot override a failed mandatory
functional or authority criterion.

Each load-bearing grader has a known-good/bad pair. The evaluator's handling of
those controls is also tested against a grader that always passes, one that always
fails, one that crashes and one that emits no result. Add targeted mutations
where they establish that named protections actually matter. A written list of
protections is not a census of every protection the system has.

## 6. Minimum evidence record

| Group | Required fields or observation |
|---|---|
| Identity | Experiment/trial IDs; parent comparison; task family/level; case and grader revisions; skillc revision |
| Subject | Source locator, resolved revision/content digest, selected skills, adapter and installation evidence |
| Execution | Client/model identities and relevant settings, image digest, environment profile, permission/network policy, budgets and interaction script |
| Inputs and outputs | Initial fixture digest, agent-visible request, final patch/artifact identity, observed events, grader results and diagnostics |
| Outcome | Execution status, each mandatory criterion, overall result, cause, exclusions and unresolved evidence |
| Resource use | Setup/execution/grading time separately, interventions, calls/tokens and cost where observable |
| Lifecycle | Start/end times, stop reason, retries, cancellation and cleanup outcome |

Unknown fields are explicitly unknown. Store the metadata required to reproduce
configuration, never credential values. Access and retention for private project
artifacts require the policy chosen in review Q5. Externally retained evidence is
referenced by stable identity; a path to an overwritten directory is insufficient.

A rerun gets a new ID and links to the original. Regrading creates a new result
linked to the unchanged original artifact and new grader revision. Neither
operation erases the earlier attempt.

## 7. Aggregation and progression

Start every report with the declared population and counts of PASS, FAIL,
UNAVAILABLE, INCONCLUSIVE and NOT_RUN. If reporting pass rate among completed
gradable trials, show that denominator and the scheduled population alongside it.
Report infrastructure availability separately. Never drop awkward attempts.

Keep task success, constraint violations, completion-claim accuracy, intervention
burden and cost separate. A cheap run that failed is not a cheaper successful
delivery. Report total experiment spend, including retries and evaluator costs,
as well as subject-execution cost.

Use paired results where tasks and configurations match. Multiple repeats of one
task do not establish performance across many tasks. Statistical intervals and
promotion thresholds need a justified sampling plan after pilot calibration;
none is specified for the first experiment.

Levels may be explored independently. Qualification requires a predefined task
population, repeat policy, controlled graders, mandatory acceptance and regression
evidence from relevant earlier levels. Report levels as not evaluated,
exploratory, qualified or regressed, with supporting configuration and evidence.
No global 0-10 rating or public badge is produced by default.

## 8. Qualification examples

- Passing one unfamiliar task while repeatedly failing simple fixes is an uneven
  exploratory profile, not a qualified Level 6 result.
- Identical candidate/baseline outcomes on a small sample support "no observed
  benefit on this sample", not "the skill is useless".
- A collection outside the coordination domain has that suite excluded by scope,
  not a fabricated coordination score of zero.
- A container-only demonstration supports its tested environment, not a host or
  managed-session claim. Environment coverage is independent of difficulty.

## 9. Research grounding

Anthropic's guidance separates task outcomes from an agent's account and treats
repeated attempts as trials. That informs the measurement approach here; it does
not establish that our proposed tasks or thresholds are valid.
[Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

Harbor separates task instructions, environments and verification, and documents
an opt-in separate verifier environment. It is a reuse candidate, not an adopted
dependency or proof that its defaults meet this protocol.
[Task overview](https://docs.harborframework.com/core-concepts/tasks/overview),
[Separate verifier](https://docs.harborframework.com/core-concepts/tasks/separate-verifier)
