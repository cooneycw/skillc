# Flow run record - issue #499

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=8d18cc7f3f9849b6883238c1b28dc5ed -->
## Run 1

- Run-id:            8d18cc7f3f9849b6883238c1b28dc5ed
- Run-start:         8d4eaf7571738634d79b29c9e4cdf265db43f7c7
- Issue:             #499
- Base SHA:          8d4eaf7571738634d79b29c9e4cdf265db43f7c7
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 orchestrator (wave skillc-400, authority-model orchestrator-only), GO-WITH-CONDITIONS 2026-10-20
- Recorded at:       2026-10-21T00:50:00Z

### Section B evidence
Merged since #487 (ad38f82): 6fd94b6 (#492), 64321b2 (#494), 7c1d408 (#493), 7cdf37a (#495), d5903e5 (#496), 522e2d6 (#497), 8d4eaf7 (#498); none touches grade_flow_auto_necessity.py. Duplicates/superseding: none. Rev-4 replay over all 20 retained reports: campaign 20261020T141529Z-3585c9 10/10 correct; campaign 20261020T195431Z-fab3ce misreads exactly t1 (verdict+disposition), t8 (verdict), t4/t5/t7 (disposition). Template: claude-power-pack 86641e8 codex/skills/flow-auto/reference.md:483 (Section C "framed as a plan"), :487-491 ("Run the close only with reviewer assent"), :515, :2171.

### Section C - the approved plan
1. `evals/level3/flow-auto-necessity/grade_flow_auto_necessity.py` - revision 5: "stopped at Step 3 with verdict X" inside the template lead-in; `proposed (changes|plan)` heading; "(may|shall) I close #1" as a recommendation; every rev 2-4 refusal kept
2. `evals/level3/flow-auto-necessity/grader.json` - revision "5"
3. `evals/level3/flow-auto-necessity/candidates/` - live-clean-rev4-verbatim and live-twin-rev4-verbatim (inconclusive), shape-witnessed passes per shape, reds per bound
4. `evals/level3/flow-auto-necessity/README.md` - the revision-5 rule
5. `evals/level3/flow-auto-necessity/PROVENANCE.md` - the verbatim rows: id scan and leak-check stated, container paths only
6. `evals/level3/campaign-434/manifest.json` - re-frozen by freeze.py (grader digest)
7. `evals/level3/campaign-434/README.md` - revision note
8. `tests/test_flow_auto_necessity_task.py` - revision 5, grammar units, rev-4 monkeypatch reds, private 20-report replay (skip loudly)
9. `tests/test_fixture_live.py` - the approved rev-4 campaign declaration refused since revision 5; tests re-pointed to re-derived identities
10. `tests/test_git_snapshot.py` - candidate count
11. `changelog.d/499.md` - one bullet

Scope: small-medium. Risks: post-hoc widening (bounded: positive template grammar, committed reds); shape 1 is template-adjacent not verbatim; rev 5 spends the rev-4 approval (PR-B brings a new declaration); decided after seeing results.

<!-- flow-run n=2 id=8aabae8434eb4c20bfe37caa5f92984a -->
## Run 2

- Run-id:            8aabae8434eb4c20bfe37caa5f92984a
- Run-start:         15de1552a8be7a55de4abffcada17bfca5770dfa
- Issue:             #499
- Base SHA:          15de1552a8be7a55de4abffcada17bfca5770dfa
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 orchestrator (wave skillc-400, authority-model orchestrator-only), GO-WITH-CONDITIONS 2026-10-20 (PR-B as planned in run 1's Step 3; re-ordered after #500 by the 2026-10-21 ruling)
- Recorded at:       2026-10-21T04:05:00Z

### Section B evidence
PR-A merged as f168121 (#501): grader revision 5; the approved revision-4 campaign declaration (90accda5) is refused as spent. #500 merged as 15de155 (#502) between them; it does not touch fixture_live or the campaign-434 files. Duplicates/superseding: none.

### Section C - the approved plan
1. `evals/level3/campaign-434-live/campaign-declaration-rev5.json` - NEW: the revision-4 declaration's terms unchanged; only the task identities (grader revision 5), run_store and the comment differ; no approval
2. `tests/test_fixture_live.py` - append-only: allow-list identity to the approved revision-4 declaration with a tamper control, the draft pinned and unapproved, and the private no-false-stop check over the spent revision-4 run (20261020T195431Z-fab3ce) with its control
3. `evals/level3/campaign-434-live/README.md` - the revision-5 declaration
4. `changelog.d/499-campaign-rev5.md` - one bullet

Scope: small. Risks: a term drifting from the approved one (bounded: the allow-list test); a false containment stop (bounded: the no-false-stop check over the spent run's 10 attempts); rev 5 missing new wordings again (reported, not patched without the owner).
