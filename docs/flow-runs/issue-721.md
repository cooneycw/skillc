# Flow run record - issue #721

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=57303a2d067448379328d46da1d61f75 -->
## Run 1

- Run-id:            57303a2d067448379328d46da1d61f75
- Run-start:         6aaebf6916b414d3b459baa88f5a3d9c7b738e01
- Issue:             #721
- Base SHA:          6aaebf6916b414d3b459baa88f5a3d9c7b738e01 (origin/issue-719-skill-usage-records-and-a-hook-that-writes-them-sk; stacked on #719)
- Necessity verdict: Needs reframing
- Approval:          granted
- Approver:          owner (interactive, this session: "1. approve. 2. stacking.")
- Recorded at:       2026-11-14T21:32:34Z

### Section B evidence
- commits: none on main touching skillc/usage.py (origin/main 26e686a); code exists only on origin/issue-719-... fdf89bd..6aaebf6
- PRs: none for #719 or #721; #728 (lane file) open
- dup/super: none; #722 is a sibling defect in the same function (ensure_ignored)
- host: no worktree with unpushed commits on usage.py/test_usage.py; #719 worktree clean, claim held by a live session
- reframing: stack on #719's tip; native blocked-by #719 added to #721

### Section C - the approved plan
1. `skillc/usage.py` - refuse a symlinked .skillc/ (lstat / O_DIRECTORY|O_NOFOLLOW dir fd), open the log and .gitignore with O_NOFOLLOW (create .gitignore with O_EXCL); refusals raise into the existing fail-open paths (exit 0)
2. `tests/test_usage.py` - red cases for symlinked usage.jsonl, .gitignore and .skillc/ through usage hook and usage end, asserting target bytes unchanged, exit 0 and the refusal line; run red on 6aaebf6 first
3. `docs/specs/evaluation-facility/records.md` - one clause in the Writer paragraph: symlinked .skillc/, .gitignore or log is refused and nothing is written
4. `docs/skill-usage-hook.md` - one sentence of fact naming the test ids
5. `changelog.d/721.md` - changelog entry

Scope: 5 files, ~90-120 lines.
Risks: cannot merge before #719 and needs a rebase after its squash-merge; #722 rewrites the same ensure_ignored(); O_NOFOLLOW guards only the last component (parent covered by the directory check); main-checkout path from git-common-dir is trusted as in #719.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | will test: main checkout and linked worktree - symlink planted in the main checkout's .skillc/, hook run from a git worktree add checkout |
| Run placement | will test: Woodpecker CI and host make verify; real-Docker runner VM not applicable (no real_docker file changes) |
| Execution backend | not applicable: hook runs on the host in a Claude session, not through a trial backend |
| Agent client | will test: Claude Code via a PreToolUse payload of the shape #719's tests use (stand-in); Codex not applicable, #719 defines no Codex hook surface |
| Client invocation | not applicable: no trial invocation path changes |
| Static-check target | not applicable: no rule, control or selftest target changes |
| Subject collection | not applicable |
| Subject installation | not applicable: resolve_skill() symlink-following read of installed skills unchanged and intended |
| skillc distribution | will test: source checkout; built wheel not covered by these cases |
| Python version | will test: 3.12; 3.11 not covered (project-wide gap) |
| Reader: Claude Code harness (hook exit + stderr) | reader unchanged: still exit 0, same "nothing recorded (...)" line; test asserts both |
| Reader: skills calling skillc usage end (stdout SKILLC_USAGE: line) | tested against real output: declare_end printed line asserted |
| Reader: check-records / selftest / usage report | reader unchanged: log format unchanged; only writing is refused; read-side symlink handling out of scope (nit store) |
