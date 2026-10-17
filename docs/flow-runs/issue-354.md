# Flow run record - issue #354

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=51a714efad654dea87b58c8add85e818 -->
## Run 1

- Run-id:            51a714efad654dea87b58c8add85e818
- Run-start:         3c9a569fe7a1e607f4926e0d0193483cd051e161
- Issue:             #354
- Base SHA:          450445d (the preserved work's own base), merged forward to origin/main
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated) - "#354: DRIVE APPROVED. Your triage serves as the ELI5 for steps 1-5", 2026-10-17
- Recorded at:       2026-10-17T16:30:00Z

### Section B evidence
- origin/main has no skill_digests / skill_digest_pins implementation (one unrelated test name in tests/test_coverage.py).
- No PR has referenced #354; no duplicate issue. Comments of 2026-10-12 record the preserved, uncommitted worktree and that caller adoption (calibration_run.plan_calibration, uptake plan path) is separate.
- Triage on a throwaway main checkout: 3-way apply clean except CHANGELOG.md; affected tests 420 passed; ruff clean; mypy 1 error at skillc/records.py:267.

### Section C - the approved plan
1. `skillc/records.py` - preserved ledger-binding and trial-ledger skill_digests checks; fix the mypy error at :267.
2. `skillc/profile.py` - preserved skill_digest_pins(inventory).
3. `skillc/trial.py` - preserved trial.plan acceptance and type-check of skill_digests.
4. `docs/specs/evaluation-facility/records.md` - preserved spec text.
5. `tests/test_profile.py` - preserved tests.
6. `tests/test_trial.py` - preserved tests.
7. `CHANGELOG.md` - preserved entry, re-positioned after merging current main.
8. `controls/ledger-binding/bad/skill-evidence-stale-digest/` - preserved bad control (stale).
9. `controls/ledger-binding/bad/skill-evidence-unpinned-skill/` - preserved bad control (unpinned).
10. `controls/ledger-binding/bad/skill-evidence-digest-omitted-under-pin/` - preserved bad control (omitted under pin).
11. `controls/ledger-binding/good/skill-evidence-pinned-current/` - preserved good control.
12. `controls/trial-ledger/bad/skill-digests-duplicate-path.json` - preserved bad ledger control.
13. `controls/trial-ledger/bad/skill-digests-missing-fingerprint.json` - preserved bad ledger control.
14. `controls/trial-ledger/bad/skill-digests-not-a-list.json` - preserved bad ledger control.
15. `controls/trial-ledger/good/skill-digests-declared.json` - preserved good ledger control.

Scope: medium (salvage + one type fix + evidence); no design change.
Risks: the preserved work was never gated - make verify, the blind-check reds and the pre-change reds are the evidence; caller adoption is out of scope and tracked separately.
