# Flow run record - issue #729

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=30bbac0bec144033bbdedab8994cd4af -->
## Run 1

- Run-id:            30bbac0bec144033bbdedab8994cd4af
- Run-start:         26e686aea67467e80e66f7d622950d0702c0a092
- Issue:             #729
- Base SHA:          26e686aea67467e80e66f7d622950d0702c0a092
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          the owner (cooneycw), in-session reply "approved"
- Recorded at:       2026-11-14T21:08:47Z

### Section B evidence
- commits: none since filing (origin/main 26e686a)
- PRs: none merged since filing
- dup/super: none (#470 added the encoded detector, #235 the slash exemptions; neither covers this)
- host: no sibling worktree with unpushed commits on skillc/leak.py or tests/test_leak.py

### Section C - the approved plan
1. `skillc/leak.py` - conditional_exemptions also exempts the encoded twin -home-<name> of each placeholder home, same exact match and host-account check
2. `tests/test_leak.py` - red/good cases: the encoded user placeholder is silent, longer names (users, username) still fire, a host account named user makes it fire, the u and proof placeholders alike; shown failing pre-fix
3. `changelog.d/729.md` - changelog fragment

Scope: 3 files, ~40 lines. Risk: widens an instrument; guarded by exact match + account check, pinned by red cases.
