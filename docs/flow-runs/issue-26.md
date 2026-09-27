# Flow run record - issue #26

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #26
- Base SHA:          a0fb533 (origin/main)
- Necessity verdict: Partially addressed (driver merged in #114; first live run done 2026-09-27; detection control, operator command and evidence owed)
- Approval:          granted
- Approver:          cooneycw (repository owner), reply "1.yes. 2. yes. 3. delete" to the follow-up proposed after the first live run
- Recorded at:       2026-09-27T15:20:00Z

## Section B evidence
- merged: #114 (3fed8cc, the driver and real runner), #142 (a0fb533, per-attempt agent-observation records)
- first live run: 2026-09-27 14:26Z, six attempts, all captured, none selected, all PASS
  (https://github.com/cooneycw/skillc/issues/26#issuecomment-5856746724)
- defects found in #114 during that run: the SKILLC_ALLOW_REAL_AGENT pytest harness cannot reach a real
  credential (tests/conftest.py) and passes on all-unavailable; transcript_from_record drops the record's reason
- dup/super: none

## Section C - the approved plan
1. `skillc/selection_probe.py` - keep the record's `reason` for a non-captured attempt; a named-skill runner mode used ONLY for a detection control, refused for a selection run (and vice versa); `experiment_name` on planning; the predeclared control's loader and case subset; one exit rule per run kind
2. `skillc/cli.py` - `skillc selection-probe [--detection-control]`: the operator command, exits 1 unless every attempt is captured (probe) or the control detects in treatment and not in baseline (control)
3. `evals/selection-probe/detection-control.json` - the predeclared control, committed and pushed BEFORE it runs: intended-use case, prompt names `qa-test`; what it proves and does not
4. `tests/test_selection_probe.py` - remove the blind real-agent pytest test; tests and red cases for the exit rules, the mode guards, the reason, the control subset
5. `tests/test_cli.py` - `selection-probe` wiring: all-unavailable exits 1, all-captured exits 0
6. `evals/selection-probe/evidence/README.md` - the first live run and the control run, verbatim
7. `README.md` - the new command in the command block
8. `CHANGELOG.md` - entries
9. `docs/flow-runs/issue-26.md` - this plan record

Scope: ~9 files, ~500 lines; one live control run (2 real codex attempts, subscription login).
Risks: main moves fast (several sessions merging); the named-skill canary on the baseline arm cannot be
satisfied (no skill installed) and so reads unknown/inconclusive by design; a CLI test must not reach a real
credential or agent.
