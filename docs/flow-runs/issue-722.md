# Flow run record - issue #722

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=13cf05965630406695f29c7ad38b3e60 -->
## Run 1

- Run-id:            13cf05965630406695f29c7ad38b3e60
- Run-start:         b6843aa72358919b6321c5839358ee432480ebd2
- Issue:             #722
- Base SHA:          b6843aa72358919b6321c5839358ee432480ebd2 (origin/issue-721-skill-usage-hook-follows-symlinked-skillc-files-wh, PR #734; stacked)
- Necessity verdict: Still needed
- Approval:          granted (with conditions)
- Approver:          wave orchestrator skillc-orch (policy rev 1, authority-model orchestrator-only), mailbox rev 5 "GATE: GO-WITH-CONDITIONS #722"
- Recorded at:       2026-11-14T23:22:33Z

### Section B evidence
- commits: none on origin/main touching skillc/usage.py; none on #719's branch after 6aaebf6; #721 (b6843aa) left the line-set check at usage.py:591-592
- PRs: none for #722; #735 (#719) and #734 (#721) open, not addressing it
- dup/super: none
- host: no worktree with unpushed commits on usage.py/test_usage.py

### Approval conditions (orchestrator, rev 5)
- refuse when git will not ignore the log, and when check-ignore errors, times out or git is missing; hook stays fail-open
- ask git on every path, including the freshly-created .gitignore branch
- bounded check-ignore timeout, with a monkeypatched timeout/no-git refusal test
- both negation shapes and the tracked-log case fail on b6843aa first, named in the PR with red output
- #724 is a separate PR, stacked next

### Section C - the approved plan
1. `skillc/usage.py` - ensure_ignored(state_fd, checkout) asks `git check-ignore -q` on every path (bounded timeout); on not-ignored appends a final /usage.jsonl and re-asks; still not ignored, error, timeout or no git raises so nothing is appended; new _git_status helper; append() passes the checkout
2. `tests/test_usage.py` - git-judged cases for both negation shapes and a tracked log (red on b6843aa first), monkeypatched timeout and no-git refusal tests
3. `docs/specs/evaluation-facility/records.md` - Writer clause: ignore status asked of git; a log git would not ignore is not written
4. `docs/skill-usage-hook.md` - one sentence of fact naming the tests
5. `changelog.d/722.md` - entry

Scope: 5 files, ~70-100 lines.
Risks: refusing to record when git cannot ignore the log (ruled: refuse); one extra git subprocess per hook call; global excludes are lower precedence and cannot mask a .skillc negation; lands after #734.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | will test: main checkout and linked worktree. The negation is planted in main's .skillc/.gitignore, the hook is run from a `git worktree add` checkout, and check-ignore runs against main |
| Run placement | will test: Woodpecker CI and host make targets (pytest). Real-Docker runner VM: not applicable |
| Execution backend | not applicable: host hook, no trial backend |
| Agent client | will test: Claude Code via a PreToolUse payload stand-in (#719 fixture shape). Codex: not applicable (no Codex hook surface) |
| Client invocation | not applicable |
| Static-check target | not applicable: no rule or control changes |
| Subject collection | not applicable |
| Subject installation | not applicable |
| skillc distribution | will test: source checkout. Built wheel: not covered by these cases |
| Python version | will test: 3.12. 3.11: not covered (project-wide gap) |
| Reader: git (does usage.jsonl show as untracked) | tested against real output: real git 2.43 in a temp repo, never a parsed copy of the rules |
| Reader: Claude Code harness (hook exit + stderr) | reader unchanged: exit 0, the same "nothing recorded (...)" shape. The new refusal text is asserted |
| Reader: skillc usage end callers (stdout SKILLC_USAGE:) | tested against real output: the "not recorded" line asserted for the refusal |
