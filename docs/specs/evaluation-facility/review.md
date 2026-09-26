# Decision tracking for evaluation delivery

- Status: planning choices recorded; execution choices assigned to issues
- Basis: [specification](spec.md), [interfaces](interfaces.md), [protocol](protocol.md),
  [ADR 0002](../../decisions/0002-independent-goal-driven-evaluation.md)
- Delivery order: [PLAN.md](../../../PLAN.md)

The owner authorized the plan, documentation PR/merge and issue scaffolding.
There is enough context to proceed with these deliverables. Remaining choices
belong to the tasks below; they do not require restarting discovery or blocking
the documentation merge. No named third-party grilling skill has been run.

## Decisions and their owners

| ID | Topic | Planning position | Resolution owner and gate |
|---|---|---|---|
| Q1 | First goal | CPP small-fix/slug pilot is the fixture seed, used as a measurement canary | [#5](https://github.com/cooneycw/skillc/issues/5) pins provenance and finalizes public acceptance and controls |
| Q2 | Treatment and baseline | Native CPP Codex surface versus proven absence, with ordinary project requirements/tools fixed | [#7](https://github.com/cooneycw/skillc/issues/7) defined the installed surface on 2026-09-26: all 74 `codex/skills/` directories at a pinned revision, with baseline absence and arm parity observed through the client ([subject](../../../evals/subjects/cpp-codex/SUBJECT.md), [materialization](materialization.md)); [#12](https://github.com/cooneycw/skillc/issues/12) freezes the experiment arms |
| Q3 | Client/model, repeats and budget | One Codex client initially; deterministic probes before paid runs | [#12](https://github.com/cooneycw/skillc/issues/12) records exact versions, interaction policy, repeats and approved spending limits before invocation |
| Q4 | Backend reuse | Resolved 2026-09-26: no external evaluation runtime; Coder Eval and Harbor are references only | [#6](https://github.com/cooneycw/skillc/issues/6) via [ADR 0003](../../decisions/0003-no-external-evaluation-runtime.md); runner work moves to [#8](https://github.com/cooneycw/skillc/issues/8) and [#10](https://github.com/cooneycw/skillc/issues/10) |
| Q5 | Artifact retention | Resolved 2026-09-26: explicit local store outside source, host client homes and any git work tree; owner-only; no publication or expiry; secrets excluded at export | [#8](https://github.com/cooneycw/skillc/issues/8) via [capture.md](capture.md#storage-access-and-retention-reviewmd-q5) |
| Q6 | Second collection | Tiny independently authored collection, same client/task/grader | [#11](https://github.com/cooneycw/skillc/issues/11) selects provenance/layout and proves genericity before product claims |
| Q7 | Qualification | Exploratory profiles until task breadth/repeats/uncertainty can be calibrated | [#15](https://github.com/cooneycw/skillc/issues/15) defines level criteria from observations; deferred without blocking early probes |
| Q8 | Observable evidence | Separate install receipt, ledger, captured artifacts and verified outcome | [#4](https://github.com/cooneycw/skillc/issues/4) defines schemas/coverage; [#9](https://github.com/cooneycw/skillc/issues/9) proves required distinctions |

These are planning defaults and issue responsibilities, not completed compatibility
experiments. Changes to a hard boundary update the spec and ADR. Backend adoption
and a live-run budget must be explicit; document presence is not their evidence.

## Questions for each implementation review

1. Could the baseline lose because ordinary requirements or tools were removed?
2. Could a legitimate alternative solution fail an implementation-specific grader?
3. Can the subject forge success, replace tests or contaminate another attempt?
4. Can missing skills, empty populations, crashes or lost evidence look successful?
5. Is installation native and observed, or only asserted by a setup process?
6. What decision does this output inform, and is a null result accepted without changing the task until the preferred subject wins?
7. Does the level reflect observed task demands, are revisions versioned, and what evidence supports the interpretation and where does it stop?
8. Can candidate code alter the verifier's result channel while it is being graded?
9. Which costs/events are unobserved, especially across nested workers or external tools?
10. Did the change introduce a requirement, is its scope and phase explicit, and would the first milestone remain useful without a dashboard, scheduler or extra model?

Review the concrete implementation and retained control evidence against these
questions. Further wayfinder/grilling discussion should resolve a named decision
or counterexample rather than turn into an additional generic planning phase.

## September 25 supplemental review

Reviewed for [#22](https://github.com/cooneycw/skillc/issues/22) against this working
tree, the September 25 issue snapshots and the governing documents. This is
scaffolding, not implementation acceptance. The follow-up issues filed from it
deliver no capability by existing; the existing issues retain their gates.

Existing coverage and changed assumptions affect the proposed mechanisms:

- [Subject acquisition](spec.md#subject-acquisition) and
  [installation contracts](interfaces.md#installation-and-execution-lifecycle)
  already distinguish discovery, availability, invocation and outcome. Selection
  experiments need cases and observations, not a second definition of success.
- [Protocol comparison arms](protocol.md#2-comparison-arms),
  [accounting](protocol.md#7-aggregation-and-progression) and
  [evidence identities](protocol.md#6-minimum-evidence-record) already cover
  ablation, overhead and revision binding. Cards and pruning are uses of that
  evidence, not new evidence authorities or automatic removal policies.
- The [September 15 assessment](../../reviews/2026-09-15-skills-as-code-harness.md#proposed-first-milestone)
  required demonstrated improvement and preferred an installed plugin runner.
  Those are historical recommendations: the current
  [completion boundary](spec.md#9-evidence-limits-and-completion) accepts null
  results, and [ADR 0002](../../decisions/0002-independent-goal-driven-evaluation.md#decision)
  makes backend adoption conditional. Neither old proposal adds an acceptance gate.
- The September 20 planning baseline predates executable
  [record validation](records.md#boundary). All four record forms now exist
  (#4); evidence authentication and the runtime that produces them remain open. The
  baseline's historical six-rule/12-test counts are not current completion evidence.
- [#9](https://github.com/cooneycw/skillc/issues/9) protects the evaluator;
  [#14](https://github.com/cooneycw/skillc/issues/14) measures the subject's behavior.
  A subject resisting hostile instructions does not prove grader isolation, or
  conversely. [Independent exploration](protocol.md#7-aggregation-and-progression)
  is already permitted; no change to qualification or dependency order is needed.

| Recommendation | Disposition | Rationale and owner |
|---|---|---|
| Skill selection and non-selection evaluations | accepted bounded follow-up | [#26](https://github.com/cooneycw/skillc/issues/26), after [#7](https://github.com/cooneycw/skillc/issues/7) and [#10](https://github.com/cooneycw/skillc/issues/10): one intended-use request, one near miss and one overlapping-skill choice in a pinned native installation. Measure selection separately from independently graded outcomes; successful non-invocation can be valid. Adapt the proposal to allow unknown invocation and declared manual-only skills, rather than impose a universal trigger score. |
| Pruning and interaction measurements | deferred with a revisit trigger | Revisit after [#12](https://github.com/cooneycw/skillc/issues/12) yields accounted outcomes and overhead, and a maintainer can name a subset and a decision it could change. The small canary may have ceiling effects; another arm without an informative contrast need not help. Use [protocol arms](protocol.md#2-comparison-arms) for baseline/full/one chosen subset if warranted. That contrast cannot isolate all interactions. Reject exhaustive subset search and automatic removal; no experiment owner is assigned before this trigger. |
| Compact evidence cards | deferred with a revisit trigger | Revisit after [#12](https://github.com/cooneycw/skillc/issues/12) produces an authoritative report and a named reader identifies a recurring interpretation or retrieval problem. [Minimum evidence](protocol.md#6-minimum-evidence-record) and [report semantics](interfaces.md#reporting-semantics) already own the facts. Start with one derived readable summary if needed; JSON needs a concrete consumer. Reject a parallel evidence database, recommender or global rating. |
| Author feedback and installation verification | accepted bounded follow-up | [#27](https://github.com/cooneycw/skillc/issues/27), after [#2](https://github.com/cooneycw/skillc/issues/2), [#3](https://github.com/cooneycw/skillc/issues/3) and [#10](https://github.com/cooneycw/skillc/issues/10): exercise one local author consumer of existing findings, concise repair guidance and the packaged checker's clean installation/selftest. Keep this distinct from subject installation. Missing required references/helpers are already [#7](https://github.com/cooneycw/skillc/issues/7)'s declared dependency closure; reject a general Markdown-link heuristic as readiness proof. No new rule catalog or CI expansion is required here. |
| Subject-side trust and recovery cases | accepted bounded follow-up | Refine [#14](https://github.com/cooneycw/skillc/issues/14), retaining its [#13](https://github.com/cooneycw/skillc/issues/13) dependency: bound conflicting instructions/hostile references and tool loss/partial failure as separate fixture-service cases. Reuse [#9](https://github.com/cooneycw/skillc/issues/9)'s protected grading, without treating evaluator controls as subject success. Exploratory observations do not require [#15](https://github.com/cooneycw/skillc/issues/15)'s qualification delivery or establish a level claim. |
| Failure-to-regression and evidence refresh | accepted bounded follow-up | [#28](https://github.com/cooneycw/skillc/issues/28), after [#8](https://github.com/cooneycw/skillc/issues/8) and the first useful [#26](https://github.com/cooneycw/skillc/issues/26) or [#12](https://github.com/cooneycw/skillc/issues/12) evidence: sanitize one observed failure into a development regression, and compare its evidence identities with one changed configuration. Reuse [protocol lineage](protocol.md#6-minimum-evidence-record); changed skill/helper/client inputs make the old evidence historical for the new configuration, not false for the old one. Reject automatic reruns and contamination of held-out comparisons. |

The accepted outcomes use the phased amendments in
[spec sections 1 and 6](spec.md#1-objective). EF-01 through EF-11 and initial
milestone acceptance are unchanged. The
[traceability table](../../../PLAN.md#supplemental-decision-traceability) separates
accepted scope from delivered evidence; deferred work is not completed work.
No protocol change or new interface schema is needed for these dispositions.

## September 26 config-drift-checker review

Reviewed for [#38](https://github.com/cooneycw/skillc/issues/38) against these
documents and the ADRs. The source is
[jameskomo/config-drift-checker at 0aca62b](https://github.com/jameskomo/config-drift-checker/tree/0aca62bf43fcc6c9e873b507dcb6f2a4455f2de1)
by @jameskomo (FSL-1.1-Apache-2.0), read statically. Its eval cases use the format
of Anthropic's `claude plugin eval`. Provenance, upstream locations and declined
ideas are in the [lessons note](../../research/config-drift-checker-lessons.md).
Per [ADR 0003](../../decisions/0003-no-external-evaluation-runtime.md), skillc
takes ideas, not code.

No concept below conflicts with an ADR. Each either fits an existing clause or is
translated to one before adoption.

| Concept | Disposition | Rationale and owner |
|---|---|---|
| Discovered versus invoked | accepted bounded follow-up | [Spec section 5](spec.md#subject-acquisition) and [interfaces.md](interfaces.md#installation-and-execution-lifecycle) already keep invocation distinct and require unknown when it is unobservable. Records version 2 has no field for it. [#39](https://github.com/cooneycw/skillc/issues/39) first decides whether a required stream is a version change, then adds the observation with controls. Depends on #8; prerequisite for #26. |
| Near-miss non-trigger case | already in scope | [#26](https://github.com/cooneycw/skillc/issues/26) owns it. Selection stays an observation, separate from outcome, unless a case declares invocation a requirement. |
| Degraded-description variant | already in scope | [Protocol section 2](protocol.md#2-comparison-arms) "Detection control", kept distinct from benefit comparisons by ADR 0002. #26's manifest states which property its variant proves. |
| Client/model drift | accepted, documented here | Added as a [protocol section 2](protocol.md#2-comparison-arms) row ([#40](https://github.com/cooneycw/skillc/issues/40)). An additional arm is not a hard boundary, so no ADR amendment. No watcher or scheduler. |
| Repeat-variance (noise band) flagging | deferred with a revisit trigger | As built upstream it learns thresholds from observed history, operates on scores that average graders, and downgrades in-band drops to warnings. That conflicts with [protocol section 7](protocol.md#7-aggregation-and-progression), [records derivation](records.md#derivation) and PLAN section D. Revisit when #12 yields repeated, accounted outcomes and #15 takes up Q7. It is then admissible only as a predeclared policy over per-criterion outcomes, with a committed case where a real break inside the band still goes red. |
| Autonomous subject repair | rejected | [Spec section 4](spec.md#4-scope-and-boundaries) excludes subject changes; #26 and #28 exclude subject edits and automatic reruns. |

EF-01 through EF-11 and initial milestone acceptance are unchanged. Apart from the
added client/model drift row, no protocol change or new interface schema is made
here; #39 owns the one record change.
