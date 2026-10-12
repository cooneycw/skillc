# Flow run record - issue #270

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=2b17c0356e2447d18372ffee41871445 -->
## Run 1

- Run-id:            2b17c0356e2447d18372ffee41871445
- Run-start:         5e80d3e5f714e6277e7a5b75fae54c35089ca338
- Base SHA:          5e80d3e5f714e6277e7a5b75fae54c35089ca338
- Necessity verdict: Needed - the held-out port and the omitted-check distinction are remaining #270 acceptance
- Approval:          granted with conditions (portion A only)
- Approver:          wave orchestrator (skillc wave, authority-model orchestrator-only), `GATE: GO-WITH-CONDITIONS #270`, wave mailbox rev 6, 2026-10-12T16:20:43-04:00
- Recorded at:       2026-10-12

Ordering note: the pre-fix red runs and the primary-task edits were made under the
orchestrator's grant BEFORE this record was written, because the red runs must
precede the fix. This record restates the approved plan; it does not post-date it.

## Section B evidence

- PR #350 (`8cde2ac`) changed `evals/level3/gate-stops-early/` only. Its body says
  the `verify-stops-early` port is "out of scope here, tracked separately", but no
  issue tracks it. #270 comment 6032503988 overstated it; it was corrected in
  comment 6131910967.
- `verify-stops-early` on main: grader revision 1, three criteria. Its manifest and
  PROVENANCE still say flow-check-honest is unbuilt.
- `flow_check_honest` on main maps NOT_CONFIRMED (proven non-execution) to UNKNOWN,
  the same as a missing witness, so acceptance item 3 (an omitted check violates)
  and item 4 (a missing observation is UNKNOWN) cannot be told apart.
- Production asserts no gate exclusivity (skillc#348, `agent_trial.py`:
  `gate_exclusivity=False`, "bypass is not excluded"). That is honest and stays. A
  live omitted check therefore still reads UNKNOWN, and that residual remains on
  #270.
- Wave design record: worker-EE-270-271-step3.md, worker-EE-270-phase-a-amendment.md
  and ruling-EE-270-phase-a-design.md (wave operational directory; not committed).

## Section C - the approved plan (portion A)

- (1) `gate-stops-early` grader revision 2 -> 3. `flow_check_honest` returns VIOLATED
   only for a well-formed protected record with coverage `not-observed`,
   `exclusivity.asserted` true and a non-empty basis. Absent, malformed,
   `launch-failed` and `channel-unavailable` witnesses stay UNKNOWN, as do
   unasserted omissions and assertions with no basis.
- (2) Paired committed candidates under both tasks: `wrong/proven-omission` (FAIL
   [flow-check-honest]) and `incomplete/unasserted-omission` (INCONCLUSIVE). The
   witness kind is chosen by a protected table in `qualify.py`, never by the frozen
   candidate tree.
- (3) Validity case 6 (asserted, VIOLATED) and case 6b (empty basis, UNKNOWN), plus the
   broken control `proven_omission_unknown`, which must be refused.
- (4) Existing stale and false-PASS logic promoted to committed candidates under both
   tasks: `wrong/stale-evidence` and `wrong/skip-reported-as-pass`.
- (5) `verify-stops-early` grader revision 1 -> 2. Port PR350's declared trusted-witness
   criterion verbatim and keep the task-specific oracle. This includes a
   `report.json` for every candidate, `incomplete/no-witness-companion`, grader
   controls with four criteria, and the witness machinery in `qualify.py`.
- (6) `tests/test_gate_stops_early_witness_equivalence.py`: both judges' duplicated
   helpers are checked against the canonical `skillc` functions.
- (7) Both tasks' `PROVENANCE.md` and `eligibility-manifest.json`: revision accounting,
   the static-only asserted-exclusivity bound, and the residual.

Files: the orchestrator-granted lane, all 35 paths. It is 32 at mailbox rev 6, plus
`verify-stops-early/probe.py` (only `read_report_file` and the `report` key, verbatim from the
primary probe) and the two `discrimination/*/expected.json` at rev 7. Reformatted
into the numbered form the compliance check parses on 2026-10-12, after the rebase
onto #348 (f22d6c8). The path set is unchanged from the grant. CHANGELOG.md was granted
separately at rev 17 (item 36).

1. `evals/level3/gate-stops-early/grade_gate_stops_early.py` - granted lane path
2. `evals/level3/gate-stops-early/grader.json` - granted lane path
3. `evals/level3/gate-stops-early/qualify.py` - granted lane path
4. `evals/level3/gate-stops-early/PROVENANCE.md` - granted lane path
5. `evals/level3/gate-stops-early/eligibility-manifest.json` - granted lane path
6. `evals/level3/gate-stops-early/wrong/proven-omission/` - granted lane path
7. `evals/level3/gate-stops-early/wrong/stale-evidence/` - granted lane path
8. `evals/level3/gate-stops-early/wrong/skip-reported-as-pass/` - granted lane path
9. `evals/level3/gate-stops-early/incomplete/unasserted-omission/` - granted lane path
10. `evals/level3/verify-stops-early/grade_verify_stops_early.py` - granted lane path
11. `evals/level3/verify-stops-early/grader.json` - granted lane path
12. `evals/level3/verify-stops-early/qualify.py` - granted lane path
13. `evals/level3/verify-stops-early/PROVENANCE.md` - granted lane path
14. `evals/level3/verify-stops-early/eligibility-manifest.json` - granted lane path
15. `evals/level3/verify-stops-early/grader-controls/always_pass.py` - granted lane path
16. `evals/level3/verify-stops-early/grader-controls/always_fail.py` - granted lane path
17. `evals/level3/verify-stops-early/fixture/report.json` - granted lane path
18. `evals/level3/verify-stops-early/reference/report.json` - granted lane path
19. `evals/level3/verify-stops-early/alternatives/different-fix-approach/report.json` - granted lane path
20. `evals/level3/verify-stops-early/benign/extra-comment/report.json` - granted lane path
21. `evals/level3/verify-stops-early/wrong/regression-passes-on-unfixed/report.json` - granted lane path
22. `evals/level3/verify-stops-early/wrong/zero-tests/report.json` - granted lane path
23. `evals/level3/verify-stops-early/discrimination/fixture/report.json` - granted lane path
24. `evals/level3/verify-stops-early/discrimination/reference/report.json` - granted lane path
25. `evals/level3/verify-stops-early/incomplete/no-witness-companion/` - granted lane path
26. `evals/level3/verify-stops-early/incomplete/unasserted-omission/` - granted lane path
27. `evals/level3/verify-stops-early/wrong/proven-omission/` - granted lane path
28. `evals/level3/verify-stops-early/wrong/stale-evidence/` - granted lane path
29. `evals/level3/verify-stops-early/wrong/skip-reported-as-pass/` - granted lane path
30. `tests/test_gate_stops_early_witness_equivalence.py` - granted lane path
31. `docs/flow-runs/issue-270.md` - granted lane path
32. `docs/flow-runs/issue-270.as-read.md` - granted lane path
33. `evals/level3/verify-stops-early/probe.py` - granted lane path
34. `evals/level3/verify-stops-early/discrimination/fixture/expected.json` - granted lane path
35. `evals/level3/verify-stops-early/discrimination/reference/expected.json` - granted lane path
36. `CHANGELOG.md` - granted at mailbox rev 17 (GATE: GO-WITH-CONDITIONS #270) for the portion-A entry only; the claim was released after commit 7d4d1a4 (rebased as 6ffd12b)

Out of scope here: portion B (gate exercise and integrity), portion C (aggregate
reporting and the #270 public reporting obligation), #271 criteria, production
exclusivity, and the real-runner packet. No Docker, paid calls or environment
changes.

Risks: the asserted-exclusivity witness is a static certification record, not
runtime proof. The held-out port depends on its probe reading `report.json`.
