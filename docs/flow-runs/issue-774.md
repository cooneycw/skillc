# Flow run record - issue #774

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=4929476c45b64bd2af776b8225288364 -->
## Run 1

- Run-id:            4929476c45b64bd2af776b8225288364
- Run-start:         a8677a5de288d5917ec743eecfb82c65fea4a632
- Issue:             #774
- Base SHA:          a8677a5 (stacked on #765's branch, itself on main 63883c6d749bf8e622f14020f09c1b1593c7cfee)
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-work orchestrator, GATE: GO-WITH-CONDITIONS #774 (mailbox rev 41, 2026-11-15T17:48Z)
- Recorded at:       2026-11-15T17:55:00Z

### Section B evidence
- kyle-cli-helper's copy at ~/.claude/skills/skill-gauntlet: 3 regular files, `diff -rq` identical to the checkout's skill, no marker, no locator (read only)
- commits on main touching install_skill.py, gauntlet.sh or test_install_skill.py since #768: none
- PRs: none open; #765 (stacked under this) edits the launcher's import check
- dup/super: none

### Section C - the approved plan
1. `scripts/install_skill.py` - copy mode: regular files only (a source symlink or special file refused); a HOME-relative locator `.skillc-checkout` (absolute only outside $HOME) and a marker `.skillc-install` (kind, schema, digest; no paths, no host name); build in `${XDG_CACHE_HOME:-~/.cache}/skillc/install-tmp/` on the same device as the skills dir (else refuse), rename the old copy aside, rename the new one in, remove the old; ours = a marked copy, an old skillc link to this checkout (migrated), or an unmarked byte-identical copy (adopted); anything else refused and named; already current means no write; uninstall removes only a marked copy or an old skillc link
2. `.claude/skills/skill-gauntlet/scripts/gauntlet.sh` - the locator first (`~` expanded), else its own real path; #765's exact-file check unchanged; a drift warning by direct content comparison that never blocks and never changes the exit code
3. `tests/test_install_skill.py` - copy-mode controls: no symlink in the installed tree; a source symlink refused; launcher runs through the locator; missing or wrong locator gives cannot-find; foreign entry and differing unmarked copy refused; identical unmarked copy adopted; old link migrated; re-install replaces with no temp tree under the skills dir; uninstall removes only the marked copy; drift warned without changing the exit; a tmp-HOME install writes `~/...` never the expanded path; different-device temp refused; no committed account path
4. `Makefile` - help text only, if it says link
5. `README.md` - the install section
6. `docs/specs/gauntlet.md` - "From any session"
7. `changelog.d/774.md` - fragment

### Gate conditions (rev 41)
- temp trees never under ~/.claude; same st_dev as the skills dir or refuse; the absent window between the renames named
- the marker holds no paths and no host name; the locator is HOME-relative under $HOME
- the drift warning never blocks; asserted
- the real install on the owner's host only after kyle-cli-helper confirms this design via the orchestrator; until then nothing is written under ~/.claude or ~/.cache
- stacked on #765; two PRs; merge #765 then #774

### Lanes for this change

| Lane | Answer |
|---|---|
| Checkout | will test - main checkout and linked worktree: an install from a linked worktree locates the main checkout |
| Run placement | will test - Woodpecker CI (python:3.12-slim, kyleci agent) and host targeted set; the real host install only after kyle-cli-helper's confirmation |
| Execution backend | not applicable |
| Agent client | will test - a fresh Claude Code session in claude-power-pack, after the confirmed real install |
| Client invocation | will test - single attempt (/skill-gauntlet through the installed copy in that session); declared resume turns, codex app-server goals: not applicable |
| Static-check target | not applicable |
| Subject collection | not applicable |
| Subject installation | will test - skill surface (the copy); disposable host home (tmp HOME and skills dir); profile dependency closure: not applicable; cold container: not tested; cached / uncached dependencies: not applicable |
| skillc distribution | will test - source checkout (editable); built wheel: not tested |
| Python version | will test - 3.12 tested; >=3.11 declared: 3.11 not tested |
| Reader: Kyle deploy (operator_config.py:404) reading ~/.claude/skills | tested against its rule - no symlink in the installed tree asserted; Kyle's own deploy not run |
| Reader: the launcher reading `.skillc-checkout` | tested against real output - written by the real installer |
| Reader: install/uninstall reading `.skillc-install` | tested against real output - the real installer's own marker |
