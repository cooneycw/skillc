# Flow run record - issue #545

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=cb48308680c346f39ed88624e941e6a5 -->
## Run 1

- Run-id:            cb48308680c346f39ed88624e941e6a5
- Run-start:         a87afb81215365e862007c9b6e390c298ee6ac8b

- Issue: #545
- Base SHA: a87afb81215365e862007c9b6e390c298ee6ac8b
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: root orchestrator, clearance-545-b1-selected-grader-identity-implementation.md
- Recorded at: 2026-10-28T03:46:03.455756+00:00

## Section B - evidence
Issue created 2026-10-24T11:56:21Z. Still missing actual selected grader/digest binding.
Since filing: a87afb81/PR594 modes, a26d8a49/PR593 optional policy,
ea2704cb/PR592 image declaration, 1fcf690/PR567 resumed attribution,
9a62b809/PR562 preflight, afce0e48/PR558 export; none implements B1.
Older PR187/c6cd6a6 already added both --task flags (known Nit6457871088).
PR146/f5b9099 fixed agent results, not selection; PR422/a2eb2c8 retained
trusted bytes, not regrade authority. Related #538/#544/#139/#418/#26/#20;
no superseding B1 issue found. Sibling348 unpublished 9caf33c/536d02c touch
calibration CLI only and remain untouched. Full searches/caller inventory
are retained in the external Step3 report SHA711e74d0a2de4dada58f0619282feda91648ae50828341e289dde943faa9b873.

## Section C - approved plan
1. `skillc/selection_probe.py` - optional planner grader/full identity; preserve declared-task standalone default, one-call execution default, and check all trial pins/population before any runner/grading without backfill.
2. `skillc/cli.py` - resolve selected/default grader once before planning, pass same object to planner and execution; preserve task/modes/pilot/regrade behavior.
3. `tests/test_selection_probe.py` - real old-CLI assertion reds then same greens; default/API compatibility, actual-consumer bad/good pin/byte/population controls and five mutation discriminators using temporary copies only.
4. `changelog.d/545-selection-grader-pin.md` - direct one-bullet note, no heading or stored-result/regrade/whole-issue claim.
Scope: four product paths, HARD350 A+D including <=60 future genuine receipt reserve; workflow <=250 separate. No receipt leaf grant. Workflow bookkeeping: docs/flow-runs/issue-545.md and docs/flow-runs/issue-545.as-read.md only.
Risks: preserve optional API/default sources; validate every trial before dispatch, not first-only or incrementally. B1 is pre-dispatch identity binding, not immutable grading execution or stored results. No historical repinning, copied hash algorithm, #544 optional-policy or #538 mode changes. A trusted regrade/B2 stored-accounting/C baseline DEFERRED; #545 remains OPEN. Root must judge tested uncommitted diff before later lifecycle gates; #542 keeps sole heavy full.

<!-- flow-run n=2 id=ed6706f418af4344aea27284f7fed7a2 -->
## Run 2

- Run-id:            ed6706f418af4344aea27284f7fed7a2
- Run-start:         46898ac1836c240eeafda93202ad221bc5f996a5

- Issue: #545
- Base SHA: 46898ac1836c240eeafda93202ad221bc5f996a5
- Necessity verdict: Partially addressed
- Approval: granted
- Approver: root orchestrator, clearance-545-b2-selection-stored-results-implementation.md
- Recorded at: 2026-10-28T05:28:04.364076+00:00

## Section B - evidence
B1 PR596/46898 binds new selected-grader identities but leaves grade_files result storage owed.
PR595/000753 changelog input guards, PR594/a87afb8 source modes and PR593/a26d8a4
optional-criterion digest policy do not implement selection stored results.
PR146/f5b9099 supplies the existing agent assembler; PR422/a2eb2c8 retains trusted
bytes without authorizing regrade replay; PR187/c6cd6a6 already delivered --task.
Refreshed post-filing history/PRs and related #139/#106/#142/#418/#538/#544/#26/#548/#20.
Preserved sibling348 witness commits9caf33c/536d02c are not a selection implementation.
Actual full Step3 source/caller/alternatives ledger: external report SHA14bb83a69270b604cc6758a661a78ec536f93f699a7df5c86bcd86c55d9b6d3e.

## Section C - approved plan
1. `skillc/selection_probe.py` - concrete real adapter only: reject foreign experiment/host grading before dispatch; capture all and establish attendance first, then hold reentrant experiment lock across reopen/stored-observation binding/one grade_agent_attempt call. Existing assembler owns admission; add trailing optional result_id/result_status to ArmResult, keep task grade separate from readiness UNKNOWN. Preserve synthetic fixture grade_files semantics with no authoritative IDs; no real transcript-byte fallback.
2. `tests/test_selection_probe.py` - genuine old realdriver storage ASSERT red first and actual CLI-to-store companion, complete-population one-result/pin/frozen/readiness links; committed actual-store accounting bad/healthy and policy/binding opposites, five meaningful restored mutants, scoped fake-only checks.
3. `evals/selection-probe/README.md` - future real versus synthetic result/readiness semantics and limits, preserve dated historical studies.
4. `changelog.d/545-selection-stored-results.md` - direct single bullet for partial B2, no heading or whole545 closure claim.
Scope: four product paths, HARD600 A+D INCLUDING <=60 future genuine receipt reserve; workflow <=250 separately. No receipt leaf or wildcard granted. Workflow: docs/flow-runs/issue-545.md and docs/flow-runs/issue-545.as-read.md append only this fresh run/snapshot, preserving B1 prefixes.
Risks: private observation reader coupling, lock/reopen binding, additive result fields, synthetic callback limits, capture-ineligible grading still owed. No authenticated-origin/freshness/global atomicity/replay guarantee. No A trusted regrade/C baseline migration, core verifier/backend/CLI/schema/grader/modes/frozen/historical changes; whole545OPEN. Return tested UNCOMMITTED diff before checkpoint/review/receipt/full. Owner02 cold542 sole heavy work untouched.
