# Flow run record - issue #763

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=eaea2f51bf7644ebb886bdd084758afc -->
## Run 1

- Run-id:            eaea2f51bf7644ebb886bdd084758afc
- Run-start:         b02fc5ebfd85df576b88a20426e8d795054b422b
- Issue:             #763
- Base SHA:          b02fc5ebfd85df576b88a20426e8d795054b422b
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-work orchestrator, GATE: GO-WITH-CONDITIONS #763 (mailbox rev 13, 2026-11-15T14:36Z)
- Recorded at:       2026-11-15T14:36:37Z

### Section B evidence
- commits since 2026-11-15T14:33Z: none touching Makefile, scripts/ or .claude/skills on main 8e0e02e
- PRs: none for #763; #754 (this lane, waiting for a CI slot) is its dependency, and this branch is stacked on its head (approved)
- dup/super: none (#738 parent; CPP registration is a separate CPP coordination issue)
- host: ~/.claude/skills holds only real directories; no symlinked user skill exists yet

### Section C - the approved plan
1. `scripts/install_skill.py` - install/uninstall the ~/.claude/skills/skill-gauntlet link to the MAIN checkout's .claude/skills/skill-gauntlet (git --git-common-dir); SKILLC_SKILLS_DIR override; idempotent; refuses a foreign link or a real entry (exit 1); uninstall removes only our link; refuses outside a git checkout (exit 2)
2. `Makefile` - install-skill and uninstall-skill targets (python3, stdlib)
3. `.claude/skills/skill-gauntlet/scripts/gauntlet.sh` - launcher: resolve its own real path to the checkout, check skillc/gauntlet.py and .venv, run uv run --project <checkout> --no-sync skillc gauntlet run; otherwise SKILL_GAUNTLET: cannot find a usable skillc, exit 2, no ROUND line
4. `.claude/skills/skill-gauntlet/SKILL.md` - Run it calls scripts/gauntlet.sh from the skill's base directory; the cannot-find line is reported and the skill stops; inside the 600-word budget
5. `tests/test_install_skill.py` - install, idempotent, refuse real dir, refuse foreign link, uninstall own only, linked worktree links the main checkout, launcher from an unrelated cwd reaches ROUND lines, launcher with no skillc reports cannot-find (exit 2, no ROUND), dangling link means no listing and no verdict, no account path in the committed files
6. `README.md` - install section: make install-skill, update by pull, remove by make uninstall-skill
7. `docs/specs/gauntlet.md` - From any session: the link, the launcher, the dangling-link and present-but-broken cases (ruling 1)
8. `changelog.d/763.md` - fragment

Scope: 8 files, ~350 lines with tests.
Risks: Claude Code following a symlinked user skill dir is unverified on this host (the real session is the check; stop on failure); a uv or .venv difference (the launcher checks and reports); CPP's installer pruning or overwriting ~/.claude/skills entries (read before installing; stop if it would refuse or break).

### Lanes for this change

| Lane | Answer |
|---|---|
| Checkout | will test - main checkout and linked worktree: install from a linked worktree links the main checkout |
| Run placement | will test - Woodpecker CI (python:3.12-slim, kyleci agent) and host `make verify` (targeted set only); real-Docker runner VM (installed runner pin vs requested commit): not tested |
| Execution backend | not applicable |
| Agent client | will test - Claude Code: a real session opened in CPP; Codex: not tested |
| Client invocation | not applicable |
| Static-check target | will test - claude-code: skillc check on the skill with its scripts/; portable: not tested |
| Subject collection | will test - synthetic (evals/subjects/gauntlet) and CPP at pinned SHAs (its current checkout, the real session); mattpocock-skills: not tested |
| Subject installation | will test - skill surface into a disposable host home (tmp skills dir) and the real ~/.claude/skills once at acceptance; profile dependency closure, cold container, cached / uncached dependencies: not tested |
| skillc distribution | will refuse - built wheel in a clean venv: scripts/ and .claude/ are not in the wheel, and the installer refuses outside a git checkout; source checkout (`uv sync`, editable): will test |
| Python version | will test - 3.12 tested; >=3.11 declared: 3.11 not tested |
| Reader: Claude Code's user-skill loader (through the link) | tested against real output - the real session in CPP |
| Reader: SKILL.md reading the launcher's output | tested against real output - launcher tests and the real session |
| Reader: the owner reading install-skill / uninstall-skill messages | tested against real output - installer tests assert each message |
