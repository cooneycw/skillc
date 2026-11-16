# Flow run record - issue #783

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=f1c739b197084826a7585861f65ba39b -->
## Run 1

- Run-id:            f1c739b197084826a7585861f65ba39b
- Run-start:         f29e3a31c7a688f512a5f3180ab37f95a45acbd5
- Issue:             #783 (PR 1 of 2; PR 2 is #760 items 1-2, stacked on this)
- Base SHA:          f29e3a3 (main, with #770)
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-work orchestrator, GATE: GO-WITH-CONDITIONS #783 (mailbox rev 51, 2026-11-15T19:59Z)
- Recorded at:       2026-11-15T21:20:00Z

### Section B evidence
- owner feedback 2026-11-15: "Output is engine-speak" (#783)
- code at f29e3a3: `_next_line` is keyed on (round, verdict) alone; Result carries no stop reason
- PRs: #782 (/charter-create) queued, not merged; #773 (#736 PR 1) queued
- dup/super: #783 subsumes #760 item 3
- SKILL.md: 523 of 600 words

### Section C - the approved plan
1. `skillc/gauntlet.py` - Result gains `reason` (a stop code set by every non-pass return) and `facts` (counts and names for Found), kept in the host-local display cache, never in the record or the cache key; `run()` prints the plain report first, then the machine lines unchanged; an output mode for plain-only or machine-only
2. `skillc/gauntlet_report.py` - new, pure: Checked / Found / Means / Do next per round from a (round, reason) table, in owner terms with no rule ids, one closing line; Do next names /charter-create only when this skillc has `charter create`, otherwise draft plus confirm; an unmapped reason shows the round's own detail
3. `skillc/cli.py` - `gauntlet run --plain-only | --machine-only`
4. `.claude/skills/skill-gauntlet/SKILL.md` - show the plain report first, then the machine lines; within 600 words
5. `tests/test_gauntlet_report.py` - new: one golden plain report per fixture stop, no rule id, Do next names a command or file; machine lines byte-identical to goldens captured on f29e3a3; an unmapped reason shows its own detail; the output switches
6. `tests/fixtures/gauntlet-report/` - the goldens
7. `tests/test_gauntlet.py` - the AST orchestration check permits exactly `contracts.load`, `contracts.expand`, `charter.skill_names` by name, and still refuses `import skillc.contracts`, any other symbol from those modules, and any import of usage, inspect or charter_confirm; a control that a fourth contracts symbol is refused
8. `docs/specs/gauntlet.md` - the report
9. `README.md` - one line
10. `changelog.d/783.md` - fragment

### Gate conditions (rev 51)
- ruling 1: two PRs; this is PR 1; machine goldens captured on PR 1's base
- ruling 2: only `load`, `expand`, `skill_names` may be imported, by name; the narrowing is a deliberate, bounded change, named under Plan deviations with its controls
- ruling 3: /charter-create named only when available
- the owner's real run quoted in the PR, plain report first

### Lanes for this change

| Lane | Answer |
|---|---|
| Checkout | will test - main checkout; linked worktree: not tested (the output is the same) |
| Run placement | will test - Woodpecker CI (python:3.12-slim, kyleci agent) and host targeted set; real-Docker runner VM: not applicable |
| Execution backend | not applicable |
| Agent client | will test - Claude Code: the owner's /skill-gauntlet run quoted in the PR; Codex: not applicable |
| Client invocation | will test - single attempt; declared resume turns, codex app-server goals: not applicable |
| Static-check target | will test - claude-code (the existing check of the skill, plus its pinned word budget); portable: not tested |
| Subject collection | will test - synthetic (evals/subjects/gauntlet); CPP at pinned SHAs: the existing d5ef0a66 test unchanged |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout (`uv sync`, editable); built wheel in a clean venv: not tested |
| Python version | will test - 3.12 tested; >=3.11 declared: 3.11 not tested |
| Reader: the owner reading the plain report | tested against real output - goldens per stop, and the owner's run quoted |
| Reader: tests and gauntlet verdict reading the machine lines | tested against real output - byte-identical goldens |
| Reader: the engine's resume reading reason/facts from the display cache | tested against real output - a cached run's report |
