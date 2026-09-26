# Flow run record - issue #8

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #8
- Base SHA:          52476609b8ab0eb2d4a2bf044ca6ee2b1de59686
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (cooneycw), in the interactive /flow:auto session
- Recorded at:       2026-09-26T15:01:53Z

## Section B evidence

Commits since filing (2026-09-20T16:27:41Z): 2f74b83, 04de452, 857781f, c352bbe,
1c8a762, 36bc172, e02a217, b8809e0, 95fead8, c37c991, b1a1fdf, f2d1a5c, 3c243a1,
a9b2d7b, 85f7363, 5247660. c37c991 (#4) delivered record forms and validators;
a9b2d7b (#7) the receipt producer. None writes a ledger, lifecycle or manifest.
Merged PRs: #16, #17, #21, #24, #25, #29, #30, #31, #32, #33, #34, #35, #36, #41,
#42. Duplicate/superseding issues: none (#1 roadmap only; #9, #10 depend on #8).

Owner decision at approval: lifecycle lives in a new v2-ADDITIVE record kind
`attempt-lifecycle` (producer controller, one per attempt); no version bump.
attempt-accounting becomes: every planned attempt has a lifecycle, every
captured attempt has a result, lifecycle and result agree.

## Section C - the approved plan

1. `skillc/trial.py` - stdlib controller: plan with controller IDs and stored resolved config, ledger written once (O_EXCL|O_NOFOLLOW), append-only retries, run_attempt with process group + confirmed stop + controller-captured raw streams, bounded capture after confirmed stop refusing traversal/symlink/secret, import_record refusing stale/digest-missing, frozen_artifacts re-hash gate, finalize, add_result without overwrite, idempotent owned cleanup, store location refusals
2. `skillc/records.py` - attempt-lifecycle kind and rule; attempt-accounting and unique-ids extended
3. `skillc/checks.py` - register attempt-lifecycle
4. `controls/attempt-lifecycle/` - new bad/good control
5. `controls/attempt-accounting/` - new bad cases for missing lifecycle, captured without result, disagreement
6. `controls/` - lifecycle.json added to every existing bundle case (mechanical)
7. `tests/test_trial.py` - red/green for every controller refusal, including #6 transfers
8. `tests/fixtures/trial-subject/fake_subject.py` - scriptable deterministic subject
9. `tests/test_records.py` - lifecycle and accounting cases
10. `docs/specs/evaluation-facility/capture.md` - controller contract, Q5 storage/retention policy, limits, Coder Eval credit
11. `docs/specs/evaluation-facility/records.md` - lifecycle kind, accounting change, retention pointer
12. `docs/specs/evaluation-facility/review.md` - Q5 resolved
13. `PLAN.md` - #8 status
14. `AGENTS.md` - layout entries
15. `docs/flow-runs/issue-8.md` - this record
16. `docs/flow-runs/issue-8.as-read.md` - issue body as read

Scope: ~16 files plus ~25 control fixtures, ~2,000-2,800 lines. No CLI subcommand, no Docker (#10), no grading (#9).
Risks: contract change inside v2; confirmed stop covers the process group only (containment is #10); secret filter is a heuristic, not a census; ledger immutability binds the subject, not the operator; POSIX only.
