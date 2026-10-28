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
