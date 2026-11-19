# Flow run record - issue #555

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=69e4fce986894ebb9e8c79d605242211 -->
## Run 1

- Run-id:            69e4fce986894ebb9e8c79d605242211
- Run-start:         a2f9ffd67c2f109b7056852ac6a46657a4fd0912
- Issue:             #555
- Base SHA:          a2f9ffd67c2f109b7056852ac6a46657a4fd0912
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (in-session "approved", 2026-11-19)
- Recorded at:       2026-11-19T11:27:28Z

### Section B evidence
39 commits since 2026-10-24 touch the paths (incl. aa5ddc6, 7c31067, 12da2e5, f29e3a3, fd8804a, 11acf2a, 5e10683, 097c1dd, 75636b9, feb6c85, 4345eb0, 46898ac, a87afb8, 5d04193, 9a62b80); none fixes an item (each re-grepped). PRs mentioning #555: none. Related: #64 (item 9 transfer), #237 CLOSED 2026-10-12 (unblocks item 5). Sibling worktree skillc-348-qualify-stdout-compat unpushed 9caf33c, 536d02c: unrelated (#348).

### Section C - the approved plan
1. `skillc/demo.py` - PasteBackRefused carries categories/count; message never holds a finding value.
2. `skillc/cli.py` - selection-probe site uses exc.categories; cmd_degrade_subject persists skills first, writes receipt last atomically, removes partial output on failure.
3. `skillc/degrade.py` - refuse --remove-file of a manifest-listed file unless the operator also edits the manifest; docstring updated.
4. `skillc/git_fixture.py` - Refused('empty-stash') when git stash push created no refs/stash.
5. `skillc/uptake_study.py` - migrate to surface_mapping(task_surface(...)); target_selected bool/int site ruled out as inert.
6. `skillc/collection_conformance.py` - delete deprecated _fixture_surface and _FIXTURE_SRC_DIRNAME.
7. `skillc/calibration_run.py` - summarize_arms uses isinstance(..., bool).
8. `tests/test_demo.py` - refusal message carries no value; refusal still fires (control).
9. `tests/test_degrade.py` - manifest-listed deletion refused; unlisted deletion accepted (control); receipt absent after a failed persist.
10. `tests/test_git_fixture.py` - empty-stash refusal.
11. `tests/test_calibration_run.py` - integer skill_opened not counted observed.
12. `tests/test_uptake_study.py` - run_study delivers the unified task surface.
13. `tests/test_collection_conformance.py` - drop _fixture_surface references.

Ruled out (recorded on #555, no code): item 8 (CI cannot reach GitHub API), item 9 (transferred to #64 as precondition), item 6 (claude has no provider-only egress at all; needs its own egress policy + measured transcript shapes).
Scope: ~13 files, ~150 lines.
Risks: a caller reading str(PasteBackRefused) findings (only selection-probe found); uptake surface gains executable key; refusing manifest-listed deletion could reject an existing spec (none committed).

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable |
| Run placement | will test: Woodpecker CI, targeted local run |
| Execution backend | will test: DockerBackend via fake tests; ManagedBackend not covered (item 9 transferred to #64) |
| Agent client | not applicable (item 6 ruled out) |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | will test: synthetic fixtures (degrade) |
| Subject installation | not applicable |
| skillc distribution | not applicable |
| Python version | will test: 3.12 tested; not >=3.11 declared |
