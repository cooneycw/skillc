# Flow run record - issue #487

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=8751695c86374dbd8e8e0aa60a9bd2a1 -->
## Run 1

- Run-id:            8751695c86374dbd8e8e0aa60a9bd2a1
- Run-start:         21c20e25df735b0f25dc37fa4db582b03749a04c
- Issue:             #487
- Base SHA:          21c20e25df735b0f25dc37fa4db582b03749a04c
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 orchestrator (wave skillc-400, authority-model orchestrator-only), GO-WITH-CONDITIONS 2026-10-20
- Recorded at:       2026-10-20T17:20:00Z

### Section B evidence
Merged since #487 was filed (2026-10-20T14:42Z): 1eaac29 (#488), 21c20e2 (#490), neither touching the task or its tests. Duplicates/superseding: none (#475 closed is revision 3). grade_flow_auto_necessity.py:131-132 read only verdict|necessity labels or a line-opening phrase; the live "Flow stopped at Step 3: **No longer needed**." (object 48958515) reads as no verdict. Template: claude-power-pack 86641e8 codex/skills/flow-auto/reference.md:2171 "Flow Auto stopped at Step N/9: {Step Name}", :515 "Step 3/9: ELI5 complete - verdict: ...".

### Section C - the approved plan
1. `evals/level3/flow-auto-necessity/grade_flow_auto_necessity.py` - revision 4: `step 3(/N)?` joins the label set, ONLY as the whole clause (the template's name slot); every #475 refusal kept
2. `evals/level3/flow-auto-necessity/grader.json` - revision "4"
3. `evals/level3/flow-auto-necessity/candidates/` - live-clean-step3-verbatim (inconclusive), live-clean-step3-shape-witnessed (pass), reds: step3 question, negated, conditional, other issue, step 5 label, mid-sentence step-3 lead-in with prose (orchestrator condition)
4. `evals/level3/flow-auto-necessity/README.md` - the revision-4 rule
5. `evals/level3/flow-auto-necessity/PROVENANCE.md` - the verbatim row: scanned for account/user/session ids (none), container paths only
6. `evals/level3/campaign-434/manifest.json` - re-frozen by freeze.py (grader digest)
7. `evals/level3/campaign-434/README.md` - revision note
8. `tests/test_flow_auto_necessity_task.py` - revision 4 everywhere, new rows, private 10-report replay (skip loudly)
9. `tests/test_fixture_live.py` - the approved rev-3 campaign declaration refused since revision 4; campaign-shape tests re-pointed to re-derived identities
10. `tests/test_git_snapshot.py` - candidate count
11. `changelog.d/487.md` - one bullet

Scope: small-medium. Risks: rev 4 refuses the approved rev-3 declaration (a new campaign needs a new declaration and approval); a widened label set (bounded: the step-3 label must be the whole clause); decided after seeing results.
