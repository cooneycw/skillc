# Flow run record - issue #106

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #106 (second run: the item folded in 2026-09-27T13:16Z)
- Base SHA:          0b91e82f3d57a75daa3c4b1a522da73d3f2d1bff
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          the owner (cooneycw), in the invoking session
- Recorded at:       2026-09-27T14:24:06Z

## Section B evidence
The folded-in item ("the agent run's observation is never persisted", Nit Store
#20 comment 5856161163). Inspected since: #136 (605d521, collection-run envelope
only), #137 (972236c, Claude arm, adds skills_listed), #128 (30c593b, lifecycle
cleans before finalize), #114 (3fed8cc, selection probe), #140 (0b91e82, pilot).
None persists the observation. Duplicate/superseding issues: none.

## Section C - the approved plan
1. `skillc/records.py` - new attempt-bound kind `agent-observation` (v2, producer controller) in KINDS/ATTEMPT_BOUND; rule: closed schema, types, status observed/unknown/not-observed with reason, grading_eligible == prompt_delivered AND canary_satisfied, grade xor blocked reason, graded_status must equal derive_status of its criteria.
2. `skillc/checks.py` - register RecordRule `agent-observation`.
3. `skillc/agent_trial.py` - run_one_attempt writes `observation-<attempt>.json` beside `lifecycle-<attempt>.json` on every path, leak-scanned; returned record gains `observation_record`.
4. `skillc/collection_conformance.py` - paste-back prints `observation_record=`.
5. `controls/agent-observation/good/` - observed and not-observed bundles.
6. `controls/agent-observation/bad/` - unknown key, eligibility mismatch, graded status vs criteria, both grade and blocked reason, unknown status without a reason.
7. `tests/test_agent_trial.py` - every path writes the record and check-records accepts the store; leak refusal; a red run with the record removed.
8. `tests/test_records.py` - the controls discriminate (selftest coverage).
9. `docs/specs/evaluation-facility/records.md` - agent-observation section and rules-table row.
10. `CHANGELOG.md` - entry; `docs/flow-runs/issue-106.md` - this record.

Scope: ~10 files + controls, ~400-600 lines, hermetic only. Risks: every agent
store gains a new required-shape file (existing check-records tests see it);
the closed schema must be updated when an observation field is added (loud
failure naming the field); graded_status must not read as a verdict (derive
check + records.md wording).
