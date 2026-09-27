# Flow run record - issue #139

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #139
- Base SHA:          a0fb533d002d4c1046fe1af1cbf6e9d57a93c36b
- Necessity verdict: Needs reframing
- Approval:          granted (decision 1: B1; decision 2: (b))
- Approver:          the repository owner, in the invoking session
- Recorded at:       2026-09-27T15:40:00Z

## Section B evidence

Commits since filing: a0fb533 (#142, agent-observation records; writes no result).
Merged PRs inspected: #142, #140, #138, #137, #136 - none store a verified-result
on the agent path. Open PRs: none. Duplicate/superseding issues: none (#12 is the
consumer, #106 closed).

Reframing: (1) a truthful installation receipt cannot be written on the agent
path (baseline installs nothing; codex discovery unestablished); (2) the #12
private run's ledger pins no grader digest and predates observation records, so
its bundle cannot be regenerated clean from it.

Decisions: B1 - the agent-observation record stands in for the receipt for
ACCOUNTING only; `installation-ready` is UNKNOWN on this path, so readiness still
gates PASS. (b) - the #12 tolerance is narrowed to that one pre-fix experiment
id; regeneration is owed to #12; the PR uses `Refs #139`.

## Section C - the approved plan

1. `skillc/verify.py` - agent-path grading entry that stores a verified-result with every existing check, the observation standing in for the receipt, `installation-ready` UNKNOWN, and `verification.readiness_source: agent-observation`
2. `skillc/agent_trial.py` - `run_one_attempt` grades through that entry instead of `grade_files`
3. `skillc/records.py` - `attempt_accounting` accepts a receiptless graded result only when it declares the stand-in, keeps readiness UNKNOWN, and the bundle holds that attempt's eligible agent-observation
4. `skillc/matched_pilot.py` - pin the grader digest in `plan_pilot`; export `observation-*.json`; narrow `KNOWN_GAP_*` to the pre-fix experiment id
5. `skillc/cli.py` - known-gap message follows the narrowed tolerance
6. `tests/test_agent_trial.py` - a graded attempt stores a bound result; red case: blocked grading still reports grading owed
7. `tests/test_records.py` - receiptless result without the stand-in still refused; stand-in without observation refused
8. `tests/test_matched_pilot.py` - allowances narrowed to the pre-fix experiment
9. `tests/test_verify.py` - the agent-path entry refuses an ineligible observation
10. `controls/attempt-accounting/good/agent-observation-stands-in/result.json` - committed good case (with its ledger, lifecycle, manifest, observation)
11. `controls/attempt-accounting/bad/stand-in-without-observation/result.json` - committed red case (with its ledger, lifecycle, manifest)
12. `docs/specs/evaluation-facility/verification.md` - the stand-in contract
13. `docs/specs/evaluation-facility/records.md` - the attempt-accounting stand-in clause
14. `CHANGELOG.md` - entry

Scope: medium. Risks: widening attempt-accounting could hide an unreceipted
grade (red case 11 and test 7 guard it); agent results now store INCONCLUSIVE
where the in-memory task grade said PASS.
