# Flow run record - issue #724

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=789ed24f39ea45c3ad92acbce5c942c6 -->
## Run 1

- Run-id:            789ed24f39ea45c3ad92acbce5c942c6
- Run-start:         188f761b3ee992252b6e4ea9129380f32656df9b
- Issue:             #724
- Base SHA:          188f761b3ee992252b6e4ea9129380f32656df9b (origin/issue-722-skill-usage-ignore-guard-misses-a-later-negation-s, PR #740; stacked)
- Necessity verdict: Needs reframing
- Approval:          granted (with conditions)
- Approver:          wave orchestrator skillc-orch (policy rev 1, orchestrator-only), mailbox rev 8 "GATE: GO-WITH-CONDITIONS #724"
- Recorded at:       2026-11-14T23:33:49Z

### Section B evidence
- commits: none on origin/main touching skillc/usage.py; stack commits 441e5a3, 68a1059, cd5a737 do not touch destination()/collection_of()
- PRs: none for #724
- dup/super: none
- host: no worktree with unpushed commits on usage.py
- reframing: git worktree list names the git dir in submodule and separate-git-dir layouts (measured git 2.43); posted https://github.com/cooneycw/skillc/issues/724#issuecomment-6885955520

### Approval conditions (orchestrator, rev 8)
- reframing posted on #724 and linked from the PR
- separate-git-dir linked worktree refuses loudly
- core.worktree read through git config --file <common>/config, no hand parser
- the extra lookups folded into one rev-parse call
- each recording case and the loud-refusal case shown red on 188f761

### Section C - the approved plan
1. `skillc/usage.py` - main_checkout(cwd) shared by destination() and collection_of(): bare/outside None; git-dir == common-dir -> show-toplevel; linked worktree -> common config core.worktree (via git config) else common.parent for .git; else raise MainCheckoutUnknown (loud refusal); one rev-parse call
2. `tests/test_usage.py` - submodule main + linked worktree, separate-git-dir main record; separate-git-dir linked worktree refuses loudly; collection names the submodule; superproject status stays clean; each red on 188f761 first
3. `docs/specs/evaluation-facility/records.md` - Writer paragraph: main-checkout resolution and the refusing layout
4. `docs/skill-usage-hook.md` - one or two sentences naming the tests
5. `changelog.d/724.md` - entry

Scope: 5 files, ~90-130 lines.
Risks: loud refusal for a separate-git-dir linked worktree (ruled); core.worktree read from the common config only; plain-repo behaviour unchanged; git calls folded into one rev-parse.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | will test: main checkout AND linked worktree, in each of plain repo (existing cases), submodule (both), and separate-git-dir (main records; linked worktree refuses) |
| Run placement | will test: Woodpecker CI and host make targets. Real-Docker runner VM: not applicable |
| Execution backend | not applicable |
| Agent client | will test: Claude Code via the PreToolUse payload stand-in. Codex: not applicable |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | will test: a skill collection hosted in a submodule is named by the submodule's checkout (collection_of) |
| Subject installation | not applicable: resolve_skill()'s lookup is unchanged |
| skillc distribution | will test: source checkout. Built wheel: not covered |
| Python version | will test: 3.12. 3.11: not covered (project-wide) |
| Reader: `collection` field read by usage report and the skill-usage-fields rule (COLLECTION_RE) | tested against real output: a log produced in a submodule is run through check-records with zero findings |
| Reader: Claude Code harness (hook stderr) | reader unchanged: the new refusal text uses the same "nothing recorded (...)" shape, asserted |
| Reader: `skillc usage end` callers | tested against real output |
