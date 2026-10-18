# Flow run record - issue #439

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=0df21c38590e4ab7931901cde0b98bfe -->
## Run 1

- Run-id:            0df21c38590e4ab7931901cde0b98bfe
- Run-start:         f0fe0b4cb7eefd271281ef1397e17daafc254323
- Issue:             #439
- Base SHA:          f0fe0b4cb7eefd271281ef1397e17daafc254323
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T19:47:56Z

### Section B evidence
#439 filed 2026-10-17 from Nit Store #20 issuecomment-6239283992 plus the union-merge probe; no commits, merged PRs or duplicate issues since filing implement fragments. Audit of today's 18 merged PRs found no CHANGELOG corruption (recorded on #439).

### Section C - the approved plan
1. `ci/changelog_check.py` - a skillc/ PR passes only by adding a changelog.d/<issue>[-slug].md fragment (or a new non-blank line in one) whose first non-blank line starts with "- "; Changelog-exempt trailer kept; Unreleased-only edits no longer pass; messages name the fragment path.
2. `tests/test_changelog_check.py` - committed good/bad controls, including both directions against the old and the new checker, and the real-git CLI test reworked for fragments.
3. `ci/changelog_assemble.py` - new: folds fragments (ordered by issue number, then name) into the top of ## [Unreleased], deletes them, refuses a malformed fragment with no partial write.
4. `tests/test_changelog_assemble.py` - new: ordering, insertion, existing entries untouched, fragments removed, malformed refused, bullets contiguous, two same-issue -slug fragments both folded in deterministic order.
5. `changelog.d/README.md` - new: the rule.
6. `changelog.d/439.md` - new: first fragment (dogfood).
7. `README.md` - contributor wording.
8. `AGENTS.md` - changelog-check bullet wording.
9. `CHANGELOG.md` - one-line header note pointing at changelog.d/ (existing entries untouched).
10. `.github/PULL_REQUEST_TEMPLATE.md` - fragment instruction.
11. `.woodpecker/ci.yml` - comment above changelog-check (wording only).

Scope: medium (~80 src, ~150 test, ~30 doc lines). Risks: contributors trained on Unreleased edits fail until they adapt (message says what to add); fragments accumulate until assemble runs; in-flight PRs handled by ORDER (#439 merges last, after #432/#437/#431/#280/#276).
Approver conditions: (1) grep every other consumer of ## [Unreleased] and update or list it; (2) committed controls in both states (Unreleased-only passes old/fails new; fragment-only fails old/passes new); (3) assemble covers two same-issue -slug fragments, deterministic order, neither dropped.
