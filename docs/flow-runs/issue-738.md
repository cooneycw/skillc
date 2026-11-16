# Flow run record - issue #738

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=e1084a90a414491a9b87060c64e21760 -->
## Run 1

- Run-id:            e1084a90a414491a9b87060c64e21760
- Run-start:         0af3768fafacde6cad47a651155a794ab9b30cc1
- Issue:             #738 (one checklist item: the installer and the drift check look at untracked files; comment 6907655223)
- Base SHA:          0af3768
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-work orchestrator, GATE: GO-WITH-CONDITIONS #738 (rev 82)
- Recorded at:       2026-11-16T06:20:00Z

### Section B evidence
- code at 0af3768: `install_skill.payload()` walks the source skill dir with os.walk; gauntlet.sh's drift check walks both sides; both include untracked files (the owner's GAUNTLET.json, seen in #774's installs and fresh session)
- PRs: #788 (round-3 task identity) and #717 (docs) touch other files; no commit since the finding touches these files
- dup/super: none

### Section C - the approved plan
1. `scripts/install_skill.py` - the source set is `git ls-files -z --cached -- .` on the skill dir (tracked by path, read from the working tree); refuse when the source is not a git work tree or git fails (install from an export is not supported, said in the text); refuse a tracked path missing on disk; the installed side is still walked in full
2. `.claude/skills/skill-gauntlet/scripts/gauntlet.sh` - the drift check's checkout side: a git work tree reads the ls-files set; NOT a repository (no .git up the tree, a `git archive` export) walks in full, since that is the tracked set; a .git present but git missing or failing skips with one note line; never `-c safe.directory`; the installed-side walk also lstats directory entries (dir symlinks)
3. `tests/test_install_skill.py` - reds on 0af3768 with twins: untracked file not copied / tracked file copied; untracked file no warning / tracked change warns; archive-style checkout differing warns / identical silent; .git with failing git prints the note, no warning; dir symlink in the copy warns / none silent; installer refuses with no git work tree; a tracked-but-deleted file is refused
4. `README.md` - git-tracked files only, tracked by path
5. `docs/specs/gauntlet.md` - the three checkout cases of the drift check and the installer's one
6. `changelog.d/738-tracked.md` - fragment

### Gate conditions (rev 82)
- the three checkout cases, detected as "rev-parse fails AND no .git up the tree" for the archive case, never as any git failure
- no `-c safe.directory`
- every red run on 0af3768 and said so; the five make gates before push; targeted set only; body edited only after headRefOid == local HEAD; Refs #738, never close it; merge after #788

### Lanes for this change

| Lane | Answer |
|---|---|
| Checkout | will test - main checkout; linked worktree: not tested |
| Run placement | will test - Woodpecker CI and host targeted set; real-Docker runner VM: not applicable |
| Execution backend | not applicable |
| Agent client | not applicable - no client is invoked |
| Client invocation | not applicable |
| Static-check target | not applicable - no skill text changes |
| Subject collection | not applicable |
| Subject installation | will test - skill surface, disposable host home (tmp HOME, synthetic checkouts incl. an archive-style one); profile dependency closure, cold container, cached, uncached dependencies: not tested |
| skillc distribution | will test - source checkout; the archive-style checkout stands in for Kyle's `git archive` staging |
| Python version | will test - 3.12 tested; 3.11 not tested |
| Reader: Kyle's staging of the copy | not tested - Kyle #2535 reads the copy; only its archive shape is simulated |

<!-- flow-run n=2 id=ebc2bdc443b34b95a472f2830eb607a4 -->
## Run 2

- Run-id:            ebc2bdc443b34b95a472f2830eb607a4
- Run-start:         feca1b4fa5a9f6652a9a8f0bb095e91c38a94377
- Issue:             #738 (owner ruling 2026-11-16: exclude all of skillc from Kyle containers; the installer writes .kyle-exclude on every install)
- Base SHA:          feca1b4
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          wave skillc-work orchestrator, GATE: GO-WITH-CONDITIONS #738 (rev 87)

### Section B evidence
- code at feca1b4: `_build` writes only LOCATOR and MARKER; INSTALL_FILES = (LOCATOR, MARKER); a refresh drops kyle-cli-helper's hand-made `.kyle-exclude`; tests lines 759-770 assert its removal (#777)
- commits on scripts/install_skill.py: 63883c6 (#768), 36e791e (#777), feca1b4 (#789); none since
- dup/super: none

### Section C - the approved plan
1. `scripts/install_skill.py` - KYLE_EXCLUDE in INSTALL_FILES (out of payload, adopt comparison and digest); `_build` writes it empty; the marked "already installed" shortcut also requires it as a regular file; docstring three files
2. `tests/test_install_skill.py` - reds on feca1b4: fresh install writes it; refresh keeps it; a current marked copy missing it gets it back; an unmarked copy with a hand-made one is adopted and hashes the same; a symlinked one is repaired; uninstall removes it; drift guard pair (dotfile silent, non-dot extra warns); replace the 759-770 test
3. `README.md` - Kyle containers exclude skillc through .kyle-exclude (owner ruling 2026-11-16); launcher contract kept, Kyle no longer stages it
4. `docs/specs/gauntlet.md` - the same
5. `changelog.d/738-kyle-exclude.md` - fragment

### Gate conditions (rev 87)
- .kyle-exclude stays out of the marker digest; asserted in the adopt case
- a red for each case on feca1b4, said in the PR body; the drift pair is a guard if gauntlet.sh is unchanged
- gauntlet.sh untouched unless the drift test goes red, and then the orchestrator is told first
- the five make gates before push; targeted set only; body edited only after headRefOid == local HEAD; Refs #738; one push under the slot rules; MERGE token asked after green CI

### Lanes for this change

| Lane | Answer |
|---|---|
| Checkout | will test - main checkout; linked worktree: not tested |
| Run placement | will test - Woodpecker CI and host targeted set; real-Docker runner VM: not applicable |
| Execution backend | not applicable |
| Agent client | not applicable - no client is invoked |
| Client invocation | not applicable |
| Static-check target | not applicable - no skill text changes |
| Subject collection | not applicable |
| Subject installation | will test - skill surface, disposable host home (tmp skills dir); profile dependency closure, cold container, cached, uncached dependencies: not tested |
| skillc distribution | will test - source checkout |
| Python version | will test - 3.12 tested; 3.11 not tested |
| Reader: Kyle's staging of the copy | not tested - Kyle's #2518 .kyle-exclude reader is not run; the file's presence is asserted |
