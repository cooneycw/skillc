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
| Client/model drift | Subject revision, tasks, evaluator, environment and budget | Client version or resolved model identity |

Do not compare a restricted baseline with an unrestricted candidate and attribute
the difference to skills. If required capabilities make matched arms impossible,
report a compatibility/product comparison rather than a causal benefit claim.
Additional model calls made by scaffolding count toward the same declared budget.

These arms compare outcomes. Whether an explicitly requested workflow is
carried out dependably, and whether packaging it as a skill matters, are the
workflow-contract lanes of section 10.

Client/model drift binds both identities in the ledger. A trial whose client or
model differs from the declared one is a different comparison, not drift evidence.
The arm is adapted from
[config-drift-checker](https://github.com/jameskomo/config-drift-checker/tree/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1)
by @jameskomo (FSL-1.1-Apache-2.0), which re-runs a pinned suite on each Claude Code
release; see [its lessons note](../../research/config-drift-checker-lessons.md) (#40).
No release watcher is adopted, and repeat-variance flagging stays deferred to #15.

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
none is specified for the first experiment. Workflow-contract studies use the
repeat, interval and accounting defaults of section 10.5.

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

Harbor ([harbor-framework/harbor](https://github.com/harbor-framework/harbor),
Apache-2.0; [provenance](../../research/README.md#harbor)) separates task
instructions, environments and verification, and documents
an opt-in separate verifier environment. It is a design reference only: skillc
takes no runtime dependency on it ([ADR 0003](../../decisions/0003-no-external-evaluation-runtime.md)).
[Task overview](https://docs.harborframework.com/core-concepts/tasks/overview),
[Separate verifier](https://docs.harborframework.com/core-concepts/tasks/separate-verifier)

## 10. Workflow-contract lanes (#246, #264)

Sections 2 and 7 compare outcomes. They cannot tell whether a workflow a user
*explicitly requests* is carried out dependably: a baseline that finds the fix is
compatible with a skill being valuable as a short, repeatable contract. This
section freezes what an explicit workflow test measures, before any such test is
built or scored. It specifies; the statistics belong to
[#273](https://github.com/cooneycw/skillc/issues/273) and the declaration fields
and instruction assembly to [#274](https://github.com/cooneycw/skillc/issues/274).
The first worked case is
[`evals/workflow-contracts/flow-check`](../../../evals/workflow-contracts/flow-check/README.md).

Nothing here revises an existing study. #203's primary endpoint, its approvals
and its current pause, and #237's approved design, are unchanged. An existing
declaration does not acquire a lane, an obligation or an authorization through
this section; every live arm still needs its own approved declaration
([ADR 0005](../../decisions/0005-runtime-scope-and-cost-rulings.md)).

### 10.1 The three lanes

| Lane | Question | Arms | Scored |
|---|---|---|---|
| **Explicit contract** | When a user explicitly invokes a published workflow, is it carried out as published, every time? | One treatment arm is sufficient; a model/client contrast is optional | Adherence, preservation and honesty against the invoked contract; task outcome beside them |
| **Matched outcome** | Does the treatment change the project outcome under matched conditions? (#203's lane) | Baseline vs treatment, natural discovery or a declared nudge | Common project acceptance only |
| **Expanded instruction** | Does packaging the workflow as a skill matter, versus giving the same obligations as prose? | Explicit skill invocation (S) vs the equivalent expanded instructions (E) | Adherence, preservation, honesty and outcome on one shared obligation set, plus convenience |

Rules shared by all three:

- **Common project requirements are identical across arms.** They come from
  the task's public goal and the fixture's own documents (`goal.md`,
  `CONTRIBUTING.md`), and the task grader scores them.
- **Treatment-specific obligations are labelled separately.** They come only
  from the published contract the user explicitly invoked. They are scored only
  in a lane where that contract was invoked or its equivalent was given: the
  explicit-contract lane and both arms of the expanded-instruction lane.
- **No arm fails for lacking the treatment's artifacts.** A baseline or natural
  arm never fails, in any lane, for not naming a skill, not emitting a CPP
  artifact (a receipt, a table, a JSON record), or not following a procedure
  nobody asked it to follow.
- **The matched-outcome lane scores no adherence.** Treatment-specific
  observations may be reported beside the outcome there, never as part of it.

The expanded arm E is built from the pinned published contract, obligation by
obligation. It may restate; it may not add an obligation, a hint about the task
or a hint about the fixture. Both arms get the same helpers at the same paths
with the same modes (helper parity), and a reviewer audits E's text against the
contract before approval. The prompt bytes and startup context of both arms are
recorded in full, so instruction length is measured, not assumed.

### 10.2 Where obligations come from

An obligation is admissible only if it has a public source:

- the task's public requirements;
- the fixture's own documents;
- the explicitly invoked published contract, at its pinned revision, with the
  line cited.

A grader may observe an obligation but never invent one. A property the contract
does not state is not a violation, even when it would be good practice. If a
reviewer thinks it should be one, that is a finding about the contract, routed
to its owner. Each obligation declares:

| Field | Meaning |
|---|---|
| `source` | The public file, revision and line that states it |
| `class` | `outcome`, `adherence`, `preservation` or `honesty` (10.3) |
| `scope` | `common` (every arm) or `treatment` (only where the contract was invoked or given) |
| `evidence` | The observation that decides it: controller-owned events, the delivered tree, or the final message |
| `rule` | When it is SATISFIED, when VIOLATED, and when UNKNOWN |
| `applies_when` | A predicate over the **starting fixture**, evaluated before any attempt; false makes it NOT_APPLICABLE for that case |

Verdicts are `SATISFIED`, `VIOLATED` or `UNKNOWN`:

- **UNKNOWN is a measurement gap, never a quiet pass or fail.** The deciding
  evidence was not captured: a lost transcript, no event stream, or an
  ambiguous command.
- **NOT_APPLICABLE is a denominator exclusion, not a verdict.** It is decided
  from the fixture, never from the attempt, and is listed in the selection
  ledger like any other exclusion.
- **An empty case is refused for adherence.** A case whose treatment
  obligations are all NOT_APPLICABLE contributes nothing to that lane's
  adherence measure. Counting such a case as compliant is the empty-population
  green this repository forbids.

### 10.3 Measures kept apart

| Measure | What it counts | Note |
|---|---|---|
| Task outcome | The task grader's mandatory criteria, by `records.derive_status` | Unchanged; #203's primary endpoint is this measure |
| Adherence | Each treatment obligation's verdict | Scored per obligation; a "compliant attempt" is one with every applicable obligation SATISFIED |
| Preservation | State the workflow promised not to change (a read-only check commits, pushes and edits nothing) and other approved work | A preservation violation is a hard failure of adherence, never offset |
| Honesty | Whether the final report matches what was observed | A claimed PASS for a check that never ran is VIOLATED even when every other obligation holds |
| Convenience | Proxies in 10.6 | Reported only; never an obligation and never a score |

Partial progress is diagnostic. It cannot cancel a VIOLATED mandatory
obligation, and adherence never offsets a task-outcome FAIL, nor the reverse.

Four observation states are recorded per attempt and never merged:

- **skill-present:** the installation receipt shows it listed.
- **read-observed:** the transcript shows its `SKILL.md` or `reference.md` read.
- **execution-observed:** controller-owned events show the commands the
  procedure prescribes.
- **compliant:** every applicable obligation is SATISFIED.

Each state has its own denominator. A read-observed attempt is not thereby
compliant, and a compliant attempt need not have read the skill: obligations
are defined by behaviour, not by which file was opened.

### 10.4 Treatment inventory and identities

A lane's declaration pins, before any attempt:

- **The treatment question.** It is one of two:
  - *product*: the skill as installed, prose plus bundled helpers;
  - *prose*: identical helpers in every arm, only the instructions differ.

  The expanded-instruction lane is a prose question by construction.
- **The inventory.** Every file of the skill, by content identity: `SKILL.md`,
  references and each bundled script with its mode, plus startup instructions
  and listing metadata. A residual-content note records where a retained file
  could teach a removed rule (#203).
- **Helper parity.** Which helpers each arm can reach, at which paths. An arm
  that cannot reach a helper the contract names is a different treatment, not
  a matched arm.
- **Identities.** Model, reasoning effort, client and version, image digest,
  tools, permissions and budgets, identical across arms.
- **Nudges.** The natural-discovery arm gets no covert naming hint. Any text
  that names or describes a skill is a declared nudge. An explicit invocation
  is recorded verbatim.
- **Manual-prompt accounting.** Every byte the user supplies (goal plus any
  added instruction) and every byte of startup context (instruction files, the
  client's skill listing) is recorded by digest and length per arm.

### 10.5 Repeats, intervals and accounting

These are the declared defaults. A study declaration may predeclare another
method with a stated justification, before any attempt; never after.

- **Unit and cluster.** The attempt is the unit. The task instance is the
  cluster. Repeats of one task are not independent evidence about other tasks.
- **Reliability.** For one task and arm, with `n` evaluable attempts of which
  `c` succeed:
  - all-k = C(c,k)/C(n,k), defined only for n >= k. With n < k the cell
    reports `insufficient`, never 0.
  - all-k is not pass@k = 1 - C(n-c,k)/C(n,k), which rewards occasional
    success. Both may be shown, labelled.
  - A pooled success rate across heterogeneous tasks is never raised to the
    k-th power.
  - A population all-k is the declared-weight mean (equal weights by default)
    of per-task all-k over the tasks that have n >= k, with the excluded tasks
    listed.
  - The estimator assumes attempts within a cell are exchangeable, which
    seeded interleaving supports and a drifting service may break, so the
    report states that assumption and the task population.
  - Method: [tau-bench](https://arxiv.org/html/2406.12045v1) pass^k.
- **Intervals.** 95% two-sided:
  - a single cell's rate: Clopper-Pearson exact;
  - a within-task difference between independent arms: the Newcombe hybrid
    score interval;
  - pooled across tasks: a task-cluster percentile bootstrap (seeded, 10000
    resamples), only with at least 5 tasks. With fewer, only per-task results
    are reported, because 2 or 3 tasks cannot support a population interval.
  - An exact McNemar test, where pairing exists, is a hypothesis test, not an
    interval (#203).
- **Pairing and order.** Arms are interleaved in a seeded order recorded in the
  declaration. Attempts are paired only where the design pairs them, such as
  the same task instance in adjacent slots. Repeat index alone is not a pairing.
- **All-attempt accounting.** The denominator is the scheduled population.
  - Every report shows scheduled, started, evaluable (PASS or FAIL) and
    coverage counts (UNAVAILABLE, INCONCLUSIVE, NOT_RUN) per cell, with
    infrastructure availability separate.
  - A timeout or resource limit reached by the agent is a FAIL (section 3),
    never UNAVAILABLE.
  - Missing data is never imputed as success or failure.
- **Retries.**
  - Only a slot that ended UNAVAILABLE before the agent's first observed turn
    may be retried, at most the declared number of times.
  - The retry is a new attempt ID linked to the original, which stays in
    coverage.
  - A FAIL, an INCONCLUSIVE, or any attempt where the agent started is never
    replaced.
  - Reliability uses the first `n` evaluable attempts per cell in slot order,
    so a retry can fill a slot but cannot select a better outcome.
- **Multiple comparisons.** Per-skill or per-obligation contrasts are
  exploratory unless a confirmatory family and its correction (Holm by
  default) were predeclared.

### 10.6 Convenience proxies

These are reported per arm beside success, and also conditional on success,
never folded into a score:

- user-supplied instruction length, in bytes and whitespace-delimited words;
- clarification and correction turns. These are `not applicable` for a
  non-interactive run, not 0;
- approvals requested, split into *necessary* (an authorization the public
  rules require) and *redundant* (an action that needed none, or one already
  authorized);
- wall time per phase, and tokens where observable, otherwise UNKNOWN.

They are proxies. A claim about human time needs a user study. Skipping a
required authorization lowers the turn count but is a VIOLATED preservation or
authority obligation, never a convenience gain. A cheap failed run is not a
cheaper success (section 7).

### 10.7 Development and held-out tasks

- **Development tasks.** Every task whose outcome has already been observed is
  a development task, and so is every task a contract was worked against.
  Today that is `gate-ran-nothing`, `helper-different-question` and
  `slug-small-fix`.
- **Held-out tasks.** A held-out family is committed, with its graders and
  contract revision frozen by content identity, before any scored run on it.
  No held-out outcome may change a contract, a grader or an obligation. A
  change after scored runs starts a new, separately declared study.
- **Null results stay.** Null, negative and ceiling results are kept and
  reported.
- **No fixture chosen to make a treatment win.** A case is admitted because its
  obligations apply, never because of the result it is expected to give.
