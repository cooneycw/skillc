# Flow run record - issue #470

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=1643bcb63aba44bbbab5f5301688125a -->
## Run 1

- Run-id:            1643bcb63aba44bbbab5f5301688125a
- Run-start:         abf81bb2ee54e836c839d91bf8065bd6620f1cfe
- Issue:             #470
- Base SHA:          (origin/main at start)
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated), "approved #470, as planned", 2026-10-18
- Recorded at:       2026-10-18T16:20:00Z

### Section B evidence
none - leak.py has only the literal `/(home|Users)/<name>` form. A dry sweep of main with the planned patterns found a real leak: a scratchpad traceback path in two stage-samples files.

### Section C - the approved plan
1. `skillc/leak.py` - encoded-home-path, claude-scratchpad and session-path-segment detectors (a synthetic repeated-digit UUID is exempt), plus the docstring
2. `tests/test_leak.py` - reds and benign twins for each detector
3. `controls/leak-check/bad/planted-encoded-home/sample.txt` - red fixture
4. `controls/leak-check/good/planted-encoded-home/sample.txt` - benign twin
5. `controls/leak-check/bad/planted-claude-scratchpad/sample.txt` - red fixture
6. `controls/leak-check/good/planted-claude-scratchpad/sample.txt` - benign twin
7. `controls/leak-check/bad/planted-session-segment/sample.txt` - red fixture
8. `controls/leak-check/good/planted-session-segment/sample.txt` - benign twin
9. `evals/level3/gate-stops-early/stage-samples/test-failed.stdout` - real leak normalized to <TREE>
10. `evals/level3/gate-stops-early/stage-samples/samples.json` - re-pinned digest
11. `evals/level3/verify-stops-early/stage-samples/test-failed.stdout` - real leak normalized to <TREE>
12. `evals/level3/verify-stops-early/stage-samples/samples.json` - re-pinned digest
13. `tests/test_calibration_p3_bindings.py` - planted scratchpad path built at runtime
14. `changelog.d/470.md` - one bullet
15. `docs/flow-runs/issue-470.md` - this record

Scope: about 15 files, 1 PR, Closes #470. No git history rewrite (orchestrator ruling: the value is the owner's public handle plus a session id).
