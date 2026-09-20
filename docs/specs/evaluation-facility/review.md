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
| Q2 | Treatment and baseline | Native CPP Codex surface versus proven absence, with ordinary project requirements/tools fixed | [#7](https://github.com/cooneycw/skillc/issues/7) defines the effective installed surface; [#12](https://github.com/cooneycw/skillc/issues/12) freezes the experiment arms |
| Q3 | Client/model, repeats and budget | One Codex client initially; deterministic probes before paid runs | [#12](https://github.com/cooneycw/skillc/issues/12) records exact versions, interaction policy, repeats and approved spending limits before invocation |
| Q4 | Backend reuse | Coder Eval first, replaceable and subject to conformance | [#6](https://github.com/cooneycw/skillc/issues/6) adopts/wraps/rejects based on the pinned code and bounded probes |
| Q5 | Artifact retention | Local/private controller-owned evidence; no automatic publication or secrets | [#8](https://github.com/cooneycw/skillc/issues/8) sets location/access/retention and export rules before real private evidence |
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
6. Is a null result accepted, or does the task change until the preferred subject wins?
7. Does the level reflect observed task demands, and are revisions versioned?
8. Can candidate code alter the verifier's result channel while it is being graded?
9. Which costs/events are unobserved, especially across nested workers or external tools?
10. Would the first milestone remain useful without a dashboard, scheduler or extra model?

Review the concrete implementation and retained control evidence against these
questions. Further wayfinder/grilling discussion should resolve a named decision
or counterexample rather than turn into an additional generic planning phase.
