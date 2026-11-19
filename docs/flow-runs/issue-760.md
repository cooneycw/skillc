# Flow run record - issue #760

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=5608388be35747b9aa8fe7556e5ff254 -->
## Run 1

- Run-id:            5608388be35747b9aa8fe7556e5ff254
- Run-start:         e992a7b29e78d828358df81ecdf972c5d9910b9d
- Issue:             #760 (PR 2 of 2 for #783/#760; items 1-2, item 3 is #783 PR 1)
- Base SHA:          e992a7b (#785's head, stacked; main 12da2e5 + #783 PR 1)
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-work orchestrator, GATE: GO-WITH-CONDITIONS #760 (rev 37) and #783 (rev 51, two PRs), repo-key ruling rev 57
- Recorded at:       2026-11-15T22:00:00Z

### Section B evidence
- code at e992a7b: `_SKIP_DIRS` skips .skillc/.venv/node_modules from round 1's and round 2's collection digest; round 2's key holds no repository; `round0` reads only `usage report`'s exit code
- PRs: #785 (#783 PR 1) authorized, last in the order; nothing else touches these lines
- dup/super: #783 subsumed item 3

### Section C - the approved plan
1. `skillc/gauntlet.py` - round 1's key adds `declared-tests` (every test path any charter declares, via contracts.load and expand, missing recorded "absent", paths under skipped dirs included); round 2's key adds `origin` (the raw `git remote get-url origin`, or "none", plus --repo when given; ruling rev 57) and `skipped-subjects` (include-glob matches under the skipped dirs, names listed and only matches hashed, a cap past which round 2 reads UNKNOWN naming why); round 0 parses `usage report`'s "by skill and digest:" lines against charter.skill_names with aliases: OBSERVED with a count, else UNKNOWN naming the names and log count, an unreadable shape UNKNOWN; aliases join round 0's key
2. `skillc/gauntlet_report.py` - plain entries for the new stops (round 0 skill-not-in-log, report-unreadable; round 2 skipped-cap)
3. `tests/test_gauntlet.py` - reds on e992a7b: deleting a declared .skillc/check.py re-runs round 1; changing origin re-runs round 2; a new .venv/x/SKILL.md matched by --include re-runs round 2; the cap reads UNKNOWN; a log holding only beta reads UNKNOWN for alpha and OBSERVED with --alias beta; a renamed report heading reads UNKNOWN; controls: unchanged inputs read (cached), alpha's own log reads OBSERVED
4. `docs/specs/gauntlet.md` - what each round's key covers (the over-invalidation trade-off of the raw origin URL), what round 0's OBSERVED means
5. `changelog.d/760.md` - fragment

### Gate conditions (rev 37, 51, 57)
- no fourth allowed import: the AST allowlist stays exactly contracts.load, contracts.expand, charter.skill_names
- the skipped-dir walk lists names only, hashes only include-glob matches, and past N entries reads UNKNOWN with the reason, never scanning forever
- round 0 parses the text pinned to real output; an unreadable shape reads UNKNOWN, never OBSERVED
- the plain report's machine goldens stay byte-identical where a stop is unchanged

### Lanes for this change

| Lane | Answer |
|---|---|
| Checkout | will test - main checkout; linked worktree: not tested (the keys are checkout-independent) |
| Run placement | will test - Woodpecker CI (python:3.12-slim, kyleci agent) and host targeted set; real-Docker runner VM: not applicable |
| Execution backend | not applicable |
| Agent client | not applicable - no client is invoked |
| Client invocation | not applicable |
| Static-check target | not applicable - no skill text changes |
| Subject collection | will test - synthetic (evals/subjects/gauntlet); CPP at pinned SHAs: the existing d5ef0a66 test unchanged |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout (`uv sync`, editable); built wheel in a clean venv: not tested |
| Python version | will test - 3.12 tested; >=3.11 declared: 3.11 not tested |
| Reader: round 0 reading `usage report` text | tested against real output - the real command on the fixture logs |
| Reader: round 1's key reading declared tests via contracts.load | tested against real output |
| Reader: the plain report reading the new reasons | tested against real output - goldens |
