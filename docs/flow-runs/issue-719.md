# Flow run record - issue #719

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=35f87eebfa2c49efac86aa3bd43a520a -->
## Run 1

- Run-id:            35f87eebfa2c49efac86aa3bd43a520a
- Run-start:         26e686aea67467e80e66f7d622950d0702c0a092
- Issue:             #719
- Base SHA:          26e686aea67467e80e66f7d622950d0702c0a092
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          the owner (cooneycw), in-session reply "approved"
- Recorded at:       2026-11-14T19:50:52Z

### Section B evidence
- commits: none on origin/main since 2026-11-14T19:44:11Z (newest 26e686a, #703)
- PRs: none merged since filing
- dup/super: none (searched; saw #719, #245, #716, #259, #272, #258, #547, #288 - unrelated)
- host: sibling skillc-348-qualify-stdout-compat unpushed 9caf33c, 536d02c are #348 work, not this issue

### Section C - the approved plan
1. `skillc/usage.py` - new: skill-usage v1 schema, UsageLog subject, four rules, git-common-dir destination, digest, fail-open hook handler, usage end and report
2. `skillc/checks.py` - UsageRule type, USAGE_RULES joined into ALL_RULES, run_usage_log
3. `skillc/cli.py` - check-records discovers *usage.jsonl logs and notes unended starts; selftest population branch; skillc usage {hook,end,report}
4. `controls/skill-usage-envelope` - bad/good cases for the v1 envelope
5. `controls/skill-usage-fields` - bad/good cases for UNKNOWN-not-absent and vocabularies
6. `controls/skill-usage-privacy` - bad/good cases for home path, email, closed key set
7. `controls/skill-usage-pairing` - bad/good cases for orphan end and declared-completed-without-end
8. `tests/test_usage.py` - rule, hook, worktree destination and report tests
9. `docs/specs/evaluation-facility/records.md` - skill-usage section and rule-table rows
10. `docs/skill-usage-hook.md` - manual hook registration
11. `README.md` - commands block and selftest count
12. `AGENTS.md` - layout line
13. `changelog.d/719.md` - changelog fragment

Scope: ~14 files, ~1300 lines. Risks: hook payload shape / typed-slash double-fire (live-verified); selftest harness family assumptions; leak-check on privacy controls; README drift count.
