# Flow run record - issue #765

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=3f10e92e5cee41b7b0bfe06a7bce58b0 -->
## Run 1

- Run-id:            3f10e92e5cee41b7b0bfe06a7bce58b0
- Run-start:         63883c6d749bf8e622f14020f09c1b1593c7cfee
- Issue:             #765
- Base SHA:          63883c6d749bf8e622f14020f09c1b1593c7cfee
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-work orchestrator, GATE: GO-WITH-CONDITIONS #765 (mailbox rev 38, 2026-11-15T17:25Z)
- Recorded at:       2026-11-15T17:30:00Z

### Section B evidence
- commits on main since 2026-11-15T14:53Z on these paths: none since #768 (63883c6)
- PRs: none open on these paths
- dup/super: none; related: the rev 34 link decision (link vs copy) would change checkout discovery, not this check
- code read: `g.__file__.startswith(checkout + "/")` is the only guard; skillc.cli is imported, never checked

### Section C - the approved plan
1. `.claude/skills/skill-gauntlet/scripts/gauntlet.sh` - the import check compares realpath of skillc.gauntlet.__file__ and skillc.cli.__file__ with realpath of <checkout>/skillc/gauntlet.py and <checkout>/skillc/cli.py; a mismatch gives the cannot-find line, exit 2, naming the module relative to the checkout (no account path)
2. `tests/test_install_skill.py` - reds on main: a non-editable skillc copy under <checkout>/.venv/.../site-packages refused; only skillc.cli from the copy refused; negative controls: the editable install runs, and a checkout reached through a symlinked path component still runs
3. `changelog.d/765.md` - fragment

### Gate conditions (rev 38)
- do it now, independent of the link decision; nothing under ~/.claude is touched, and the PR says so
- the non-editable install is simulated by layout; lanes say "built wheel: simulated by layout, not built"
- push in a free slot after #772, behind the wave queue order

### Lanes for this change

| Lane | Answer |
|---|---|
| Checkout | will test - temp checkouts, including one reached through a symlinked path component |
| Run placement | will test - Woodpecker CI (python:3.12-slim, kyleci agent) and host targeted set; real-Docker runner VM: not applicable |
| Execution backend | not applicable |
| Agent client | not applicable - the launcher is invoked directly |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | not applicable |
| Subject installation | will test - editable install runs; a non-editable copy inside the checkout's .venv is refused |
| skillc distribution | will test - source checkout; built wheel: simulated by layout, not built |
| Python version | will test - 3.12 tested; >=3.11 declared: 3.11 not tested |
| Reader: the owner and /skill-gauntlet reading the SKILL_GAUNTLET line | tested against real output - the launcher's own stderr and exit asserted |
