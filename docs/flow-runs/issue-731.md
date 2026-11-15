# Flow run record - issue #731

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=ad311c8b07584f5bb4e0226eaaa52ed4 -->
## Run 1

- Run-id:            ad311c8b07584f5bb4e0226eaaa52ed4
- Run-start:         a092ac2c99754d5152988ea5d2822969ac8f3cce
- Issue:             #731
- Base SHA:          a092ac2 (stacked on #733's head, per the orchestrator; merges after #733)
- Necessity verdict: Still needed
- Approval:          granted (with conditions)
- Approver:          skillc-orch (wave skillc-work, policy rev 1, authority-model orchestrator-only), outbox rev 5, "GATE: GO-WITH-CONDITIONS #731"
- Recorded at:       2026-11-14T23:25:00Z

### Section B evidence
- commits: 398c477 (#732) only, touching neither decay.py nor inspect.py
- PRs: #732 (unrelated)
- dup/super: none
- reproduced on a092ac2: all four defects as filed

### Section C - the approved plan
1. `skillc/inspect.py` - enforcers_named skips paths under controls/<id>/{bad,good,targets}/
2. `skillc/decay.py` - $( ) handled as a stack; file arguments do not take flag ownership; copied_passage anchors with backward extension, plus a fallback that is labelled a bounded estimate
3. `tests/test_inspect.py` - the issue's exact bad/-input line goes UNSORTED; the control root is still A; the bounded-estimate summary label
4. `tests/test_decay.py` - the issue's exact inputs for (2), (3) and (4) in both orders; the label is present on purely repetitive input and absent on the 110-word case; test_repetitive_text_stays_bounded unchanged
5. `docs/specs/inspect.md` - control-input exclusion, command-vs-argument rule plus the `a.sh b.sh --x` blind spot, anchor/fallback and the estimate label
6. `docs/measurements/inspect/` - CPP and mattpocock re-runs, with every count change explained per rule and per bucket
7. `changelog.d/731.md` - release note

Conditions (orchestrator): exact inputs, each red on a092ac2; estimate label tested both ways; bounded test not loosened; an unexplained count change blocks; blind spot documented.
Scope: ~150-250 lines. Risks: 2b shell semantics; copy-count changes on CPP; stacked on #733.

### Lanes for this change
Lanes: none - .claude/lanes.md is not on this branch (PR #728 is unmerged); PR #728's lanes are answered in the Step 3 report and will be in the PR
