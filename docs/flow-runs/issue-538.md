# Flow run record - issue #538

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=29a8974240cd4a0396abba5f0abdf0ff -->
## Run 1

- Run-id:            29a8974240cd4a0396abba5f0abdf0ff
- Run-start:         ea2704cb57c2133ffda54c962b7a5bab34de9da2
- Issue: #538
- Base SHA: ea2704cb57c2133ffda54c962b7a5bab34de9da2
- Necessity verdict: Still needed
- Approval: granted
- Approver: skillc-update orchestrator, clearance-538-source-modes-implementation
- Recorded at: 2026-10-28T01:05:49.133022+00:00

### Section B evidence

Issue filed 2026-10-24T10:42:34Z. Earlier a282164b/PR506 (#505) established
source modes and explicitly deferred selection/pilot forwarding. Post-filing
scoped changes ea2704cb/PR592, f0cea733/PR589, 1c7c4c73/PR583,
1fcf690/PR567, 9a62b80/PR562 and afce0e4/PR560 do not supply them.
No post-filing change touches selection_probe.py. Related #545 remains separate.
All local worktrees were inspected for unpublished relevant commits; sibling348
9caf33c4 and 536d02c8 concern runtime supply/witness, not this omission, and
remain untouched. No prior538 branch/worktree/remote pickup was found.
Public AgentTrialRunner omits modes; common adapter already supports them.
The existing os.access source-mode policy is reused without modification.

### Section C - the approved plan

1. `skillc/cli.py` - derive modes from the same acquired file population; pilot computes bytes and modes before discard.
2. `skillc/selection_probe.py` - optional treatment modes on factory and appended defaulted public runner field; known modes only in treatment, preserving None call shape.
3. `skillc/matched_pilot.py` - optional treatment modes forwarded through the existing common adapter, with baseline empty.
4. `tests/test_selection_probe.py` - actual old-CLI assertion red at attempt boundary, public API, source permissions and baseline/default/opposite controls.
5. `tests/test_matched_pilot_run.py` - actual old-CLI assertion red through real pilot/common adapter, pre-discard acquisition and public API controls.
6. `evals/selection-probe/README.md` - current source-mode installation note, preserving dated evidence.
7. `evals/matched-pilot/README.md` - future source-mode installation note, preserving historical runs.
8. `changelog.d/538.md` - document source-mode forwarding and preserved baseline/default behavior.
Scope: eight product paths, ceiling650 added+deleted INCLUDING a later genuine receipt (reserve60); two canonical workflow records separately ceiling250. No receipt filename/lane yet granted.

Risks: deriving modes after pilot discard; baseline contamination; conflating source
executability with suffix/stat guesses. Existing validation and mode policy stay
unchanged. First preserve two assertion reds before production changes; a new API
TypeError or expected dispatch sentinel does not count. Focused approved modules,
mode and unsafe-path controls, mutation opposites, Ruff/types only. No checkpoint,
review, receipt, full, PR or545/frozen/identity edits under this grant.
