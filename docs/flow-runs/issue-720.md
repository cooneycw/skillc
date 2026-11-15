# Flow run record - issue #720

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=64b3d00cdde94acc9f43ed33edcee24a -->
## Run 1

- Run-id:            64b3d00cdde94acc9f43ed33edcee24a
- Run-start:         398c477caf22cb2f0d5c8a8e31d411cfb5fca4c3
- Issue:             #720
- Base SHA:          398c477caf22cb2f0d5c8a8e31d411cfb5fca4c3
- Necessity verdict: Still needed
- Approval:          granted (GO-WITH-CONDITIONS)
- Approver:          wave orchestrator skillc-orch, wave skillc-work policy rev 1 (authority-model orchestrator-only, owner-delegated), mailbox rev 2
- Recorded at:       2026-11-14T23:00:25Z

### Section B evidence
- commits: since 2026-11-14T19:56Z origin/main has only 398c477 (#732), unrelated
- PRs: #735, #734, #733, #732 (merged), #728 - none implements contracts
- dup/super: none (#726 depends on this; #657, #258, #4 are other "contract" senses)
- host: no sibling worktree with unpushed commits on skillc/spec.py or skillc/contracts.py

### Section C - the approved plan
1. `skillc/spec.py` - opt-in YAML-subset extension (lists of mappings, flow lists of scalars) for CHARTER.md only; SKILL.md frontmatter still refuses both
2. `skillc/contracts.py` - new: discover CHARTER.md, parse the top YAML block, nine rules, one-level brace expansion of test paths from the collection root
3. `skillc/checks.py` - ContractRule family (collection-directory subject) joined into ALL_RULES
4. `skillc/cli.py` - skillc contracts command (verdict per contract + CONTRACTS summary; exit 0/1/2/3) and a selftest population branch
5. `controls/contract-shape` - bad/good cases, including unparseable and unsupported-YAML (unfolded wrapped scalar) blocks
6. `controls/clause-backed` - bad/good cases, including a brace expansion with one missing path
7. `controls/negative-backed` - bad/good cases
8. `controls/handoff-bilateral` - bad/good cases
9. `controls/handoff-version` - bad/good cases
10. `controls/reader-exists` - bad/good cases, including contract typo and clause typo
11. `controls/scope-owned` - bad/good cases
12. `controls/duty-single-owner` - bad/good cases
13. `controls/approval-present` - bad/good cases
14. `evals/subjects/contracts-example` - three-skill fixture modelled on eli5 -> auto with the @2/@3 mismatch
15. `tests/test_contracts.py` - rules, brace expansion, fixture BAD then fixed GOOD, none-declared exit 3, exit codes
16. `tests/test_frontmatter_subset.py` - SKILL.md frontmatter still refuses lists of mappings and flow lists
17. `tests/test_records.py` - minimality test learns the ContractRule family
18. `tests/test_readme_drift.py` - contracts command in the parser fixture
19. `docs/specs/contracts.md` - format, both-sides rule, every-clause-needs-a-failable-test rule, YAML subset, version rule, bad-segment convention (presence not failability), exit codes
20. `README.md` - commands block, exit codes, selftest count
21. `AGENTS.md` - layout line
22. `changelog.d/720.md` - changelog fragment

Conditions (orchestrator GO-WITH-CONDITIONS, rev 2): opt-in parser pinned by test and unchanged frontmatter selftest verdicts (before/after counts in PR); unsupported YAML fails contract-shape with a named reason (committed bad case); reader-exists resolves contract AND clause (clause-typo bad case); brace expansion one level, any missing path = unbacked (tested); bad-segment documented as presence not failability; exit codes documented and none-declared tested, CPP pinned-SHA run quoted; merge after #735, re-gate under umask 022.
Scope: ~22 paths, ~1,400 lines. Risks: widening a trusted parser (opt-in, pinned); merge conflicts with #733/#719 in checks.py, cli.py, README, test_records.py, test_readme_drift.py; YAML subset stricter than #718's example (doc fix noted in PR).
