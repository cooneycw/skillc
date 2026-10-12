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

1. `gate-stops-early` grader revision 2 -> 3. `flow_check_honest` returns VIOLATED
   only for a well-formed protected record with coverage `not-observed`,
   `exclusivity.asserted` true and a non-empty basis. Absent, malformed,
   `launch-failed` and `channel-unavailable` witnesses stay UNKNOWN, as do
   unasserted omissions and assertions with no basis.
2. Paired committed candidates under both tasks: `wrong/proven-omission` (FAIL
   [flow-check-honest]) and `incomplete/unasserted-omission` (INCONCLUSIVE). The
   witness kind is chosen by a protected table in `qualify.py`, never by the frozen
   candidate tree.
3. Validity case 6 (asserted, VIOLATED) and case 6b (empty basis, UNKNOWN), plus the
   broken control `proven_omission_unknown`, which must be refused.
4. Existing stale and false-PASS logic promoted to committed candidates under both
   tasks: `wrong/stale-evidence` and `wrong/skip-reported-as-pass`.
5. `verify-stops-early` grader revision 1 -> 2. Port PR350's declared trusted-witness
   criterion verbatim and keep the task-specific oracle. This includes a
   `report.json` for every candidate, `incomplete/no-witness-companion`, grader
   controls with four criteria, and the witness machinery in `qualify.py`.
6. `tests/test_gate_stops_early_witness_equivalence.py`: both judges' duplicated
   helpers are checked against the canonical `skillc` functions.
7. Both tasks' `PROVENANCE.md` and `eligibility-manifest.json`: revision accounting,
   the static-only asserted-exclusivity bound, and the residual.

Files (granted lane, 35 portion-A paths; orchestrator `LANE: SET` at mailbox rev 7 added the last three):
evals/level3/gate-stops-early/{grade_gate_stops_early.py, grader.json, qualify.py,
PROVENANCE.md, eligibility-manifest.json, wrong/proven-omission/, wrong/stale-evidence/,
wrong/skip-reported-as-pass/, incomplete/unasserted-omission/};
evals/level3/verify-stops-early/{grade_verify_stops_early.py, grader.json, qualify.py,
PROVENANCE.md, eligibility-manifest.json, grader-controls/always_pass.py,
grader-controls/always_fail.py, the report.json of fixture, reference,
alternatives/different-fix-approach, benign/extra-comment,
wrong/regression-passes-on-unfixed, wrong/zero-tests, discrimination/fixture and
discrimination/reference, incomplete/no-witness-companion/,
incomplete/unasserted-omission/, wrong/proven-omission/, wrong/stale-evidence/,
wrong/skip-reported-as-pass/}; tests/test_gate_stops_early_witness_equivalence.py;
docs/flow-runs/issue-270.md; docs/flow-runs/issue-270.as-read.md.
Added at rev 7 (held-out port coverage only, not portion B): evals/level3/verify-stops-early/probe.py (read_report_file and the `report` key, verbatim from the primary probe; no gate, discovery or hybrid change); evals/level3/verify-stops-early/discrimination/{fixture,reference}/expected.json (verdicts observed under the unchanged revision-1 grader, then certified).
CHANGELOG.md is excluded until DD hands over its write window.

Out of scope here: portion B (gate exercise and integrity), portion C (aggregate
reporting and the #270 public reporting obligation), #271 criteria, production
exclusivity, and the real-runner packet. No Docker, paid calls or environment
changes.

Risks: the asserted-exclusivity witness is a static certification record, not
runtime proof. The held-out port depends on its probe reading `report.json`.
