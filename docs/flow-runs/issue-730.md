# Flow run record - issue #730

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=09b683181b2a424dbebe83c2deeff7de -->
## Run 1

- Run-id:            09b683181b2a424dbebe83c2deeff7de
- Run-start:         a2f9ffd67c2f109b7056852ac6a46657a4fd0912
- Issue:             #730
- Base SHA:          a2f9ffd67c2f109b7056852ac6a46657a4fd0912
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), in-session "approve"
- Recorded at:       2026-11-20T10:48:01Z

### Section B evidence
Commits since filing touching skillc/leak.py or tests/test_leak.py: 398c477 (PR #732, Closes #729, the parent that introduced the enumeration). Merged PRs since filing inspected: #734-#791, none touch leak-check. Duplicate/superseding issues: none (search returns only #730).

### Section C - the approved plan
1. `skillc/leak.py` - keep the getpwall() enumeration and add two checks that do not depend on its completeness: per-match getpwnam() probing of the candidate account names built from the following 1-3 dashed segments under every mix of -, . and _ separators (cached); and the scanning account by uid, so its own encoded home is never exempt.
2. `tests/test_leak.py` - regression cases driving real getpwall/getpwnam: listing holds only root but getpwnam resolves user.operator, must fire (shown red on pre-fix code); current account user-x by uid, must fire; nothing resolves, stays exempt (negative control).
3. `changelog.d/730.md` - one fragment.

Scope: small, one concern, 3 files.
Risks: a directory account with 4+ separators after the placeholder escapes the probe (still caught when enumerated); up to ~39 name lookups per distinct match on a directory-backed host, bounded by the cache.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable - no checkout resolution |
| Run placement | will test - Woodpecker CI (full-suite gate); host targeted tests/test_leak.py only; real-Docker runner VM not applicable |
| Execution backend | not applicable |
| Agent client | not applicable |
| Client invocation | not applicable |
| Static-check target | not applicable - leak-check is not a SKILL.md rule |
| Subject collection | not applicable |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout via the suite; built wheel not covered |
| Python version | not covered - 3.12 only |

Readers:
- Reader: `skillc leak-check` (CI leak-check step, receipts) - the encoded placeholder exemption is withheld in more cases, never granted in more. Compatibility: existing #729 tests unchanged and green.
