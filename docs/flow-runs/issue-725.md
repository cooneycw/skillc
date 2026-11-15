# Flow run record - issue #725

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=07342ece6c2145e6b97bbc86a72da4b5 -->
## Run 1

- Run-id:            07342ece6c2145e6b97bbc86a72da4b5
- Run-start:         26e686aea67467e80e66f7d622950d0702c0a092
- Issue:             #725
- Base SHA:          26e686aea67467e80e66f7d622950d0702c0a092
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), in-session: "Approve the expanded scope"
- Recorded at:       2026-11-14T20:44:40Z

### Section B evidence
- commits: none on origin/main since the issue was filed (2026-11-14T20:32:45Z); tip 26e686a predates it
- PRs: none merged on or after 2026-11-14
- dup/super: none (searched decay/inspect/dangling/emphasis/"copied passage"; hits #543 #544 #545 #619 #634 #613 #277 #14 #414 unrelated)
- siblings: no worktree on this host has unpushed commits touching the new paths

### Section C - the approved plan
Design: D1 surface (include/exclude globs; CPP = .claude/commands/**/*.md + .claude/skills/*/SKILL.md, codex/skills excluded);
D2 decay rules registered in ALL_RULES, run by `skillc inspect`, plain `check` unchanged;
D3 dangling-reference population (backticked/link relative paths, --map prefixes, flags by source text, out-of-population counted);
D4 expired-marker with fixture or gh, UNKNOWN never fine, plus unmarked bare `until` reported at info;
D5/R3 copied-passage as identical normalised word runs (>= 40 words), shared words per pair;
D6 emphasis-density incl. IMPORTANT; D7/R1/R2 A needs an enforcer with a red case, B only for a named check that does not exist, C owner-only;
D8 STOPPED still lists other findings; D9 exposure ingested from a report; R4 pinned-by-test annotation; R5 inspect charter + purpose control (CPP d5ef0a66 vs #1830 Part 2's twelve); R6 stdlib, offline.

1. `skillc/decay.py` - collection loader, four decay rules, issue-state lookup
2. `skillc/inspect.py` - run rules, exposure ingest, A/B/C/D/UNSORTED sorting, pinned-by annotation, verdict, Markdown + JSON
3. `skillc/checks.py` - CollectionRule type, COLLECTION_RULES, run_collection, ALL_RULES
4. `skillc/cli.py` - _population branch, cmd_inspect, inspect parser
5. `controls/dangling-reference/` - bad/good collection cases
6. `controls/expired-marker/` - bad/good collection cases with issue-state fixtures
7. `controls/copied-passage/` - bad (re-wrapped 40+ word copy) / good (30-word overlap)
8. `controls/emphasis-density/` - bad/good cases
9. `tests/test_records.py` - CollectionRule branch in the minimality test
10. `tests/test_decay.py` - per-rule unit and red cases, all-UNKNOWN summary, blinded rule BLIND
11. `tests/test_inspect.py` - zero subjects, planted/repaired negative control, A with/without red case, report shape
12. `tests/fixtures/inspect/` - planted and repaired collections
13. `docs/specs/inspect.md` - inspect charter, per-rule population and blind spots, #1830 mapping, thresholds
14. `docs/measurements/inspect/` - real-collection proof (CPP d5ef0a66 vs Part 2, CPP main, mattpocock/skills pinned)
15. `README.md` - inspect command, selftest sample count
16. `AGENTS.md` - layout entries for decay.py and inspect.py
17. `changelog.d/725.md` - release note fragment

Scope: about 17 paths plus control case directories, ~1,400-1,800 lines.
Risks: merge conflict with in-flight #719 in cli.py/checks.py; false positives on CPP's ~/.claude/scripts and ../../../docs references; expired-marker blind to other phrasings; CPP d5ef0a66 may not carry all twelve markers verbatim.

### Lanes for this change
Lanes: none - skillc has no .claude/lanes.md (LANE_FILE_AGE: absent at plan time)
