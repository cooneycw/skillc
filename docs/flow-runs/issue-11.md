# Flow run record - issue #11

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #11
- Base SHA:          15a7036 (plan formed at 8e06030; revised after #121 merged)
- Necessity verdict: Partially addressed
- Approval:          granted
- Approver:          cooneycw (owner), in the /flow:auto session: "approved, run both codex agents, file the claude issue"
- Recorded at:       2026-09-27T11:45:00Z

## Section B evidence
Commits e021fe8 (#71), 41e56bd (#94), 8196bd1 (#99), af5b02f (#111),
f1b9b3a (#115), b9d4b44 (#117), and after approval 15a7036 (#121, which built
`skillc collection-run`). #10's operator live run (issue comment 2026-09-27T11:20Z)
recorded `demo --subject` 10/10 MET for both collections. No duplicate issues.
Claude Code arm split out to #124 on the owner's instruction.

## Section C - the approved plan
Approved plan items 1-4 (agent_trial home-file delivery, the demo agent leg, the
CLI flag, its fake-docker tests) were delivered by #121 between approval and the
first edit; they are not rebuilt here (revision within the agreed outcome, #859
ending 1). Support-matrix edits are dropped: PR #123 is open on that file.

1. `evals/second-collection-conformance/evidence/README.md` - the leak-checked live `collection-run` blocks for both collections and the missing-credential control, plus #10's `demo --subject` results
2. `evals/second-collection-conformance/run-manifest.json` - `execution` and per-bullet `acceptance_status` restated against what ran; stale "not yet built" text removed
3. `evals/second-collection-conformance/README.md` - status restated against the executed evidence
4. `tests/test_second_collection_conformance.py` - replace "not yet executed" assertions with evidence-must-exist assertions
5. `docs/specs/evaluation-facility/operator-demo.md` - record that the per-collection run was executed and where its evidence is
6. `CHANGELOG.md` - entry
7. `docs/flow-runs/issue-11.md` - this record

Scope: ~7 files, ~200-350 lines. Risks: a real Codex run in the container fails
(login, network, transcript drift) -> evidence records NOT MET/UNKNOWN and #11
stays open; conformance means a graded verdict for both collections, not a PASS
and not a comparison (#12).
