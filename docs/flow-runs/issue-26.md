# Flow run record - issue #26

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #26
- Base SHA:          ab04c6c (origin/main), merged into PR #114's branch as 3f3ab26
- Necessity verdict: Needs reframing
- Approval:          granted
- Approver:          cooneycw (repository owner), interactive reply "approved"
- Recorded at:       2026-09-27T13:08:00Z

## Section B evidence
- commits: 15a7036 (#121, extra_home_files on main), b9d4b44 (#117), d8089ae (#113),
  795a3ff (#105), 39d6ae8 (#103), 662c628 (#86)
- PRs: #86, #103, #105, #107, #108, #113, #117, #121, #125, #126 merged; #114 open draft
- dup/super: #106 (open, live session on agent_trial.py); #39 closed by #86; #11 closed
  by #126; no duplicate of #26
- The picked-up branch issue-26-agent-trial-home-surface (9bcbfeb) is superseded by
  15a7036 and is not shipped by this run.

## Section C - the approved plan
Work continues on PR #114's branch (issue-26-selection-probe-driver), current main merged in.

1. `skillc/selection_probe.py` - real AttemptRunner adapter over agent_trial.run_one_attempt (skill_name=None; treatment arm gets the collection via extra_home_files, baseline gets none; record -> AttemptTranscript from skill_invocations + detection kind; non-captured -> unknown; launch failure -> None)
2. `tests/test_selection_probe.py` - adapter translation tests on the fake docker with red cases (baseline receives no skill files; unavailable -> unknown; recorded invocations -> selected), plus one SKILLC_ALLOW_REAL_AGENT-gated real-agent test
3. `CHANGELOG.md` - entry for the adapter
4. `docs/flow-runs/issue-26.md` - this plan record

Scope: 4 files, ~200-300 lines. PR stays "Refs #26"; live probes remain owed.
Risks: #106 live session may change run_one_attempt's record shape; detection kind may
not be on the record; claude vs codex skills paths - reuse main's collection_run layout.
