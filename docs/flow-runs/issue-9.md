# Flow run record - issue #9

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #9
- Base SHA:          6afaca8122e7c8cc1a19970da9ff4d93612e6a3c
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (cooneycw), in the interactive /flow:auto session
- Recorded at:       2026-09-26T16:08:12Z

## Section B evidence

Commits since filing (2026-09-20T16:27:42Z): 2f74b83, 04de452, 857781f, c352bbe,
1c8a762, 36bc172, e02a217, b8809e0, 95fead8, c37c991, b1a1fdf, f2d1a5c, 3c243a1,
a9b2d7b, 85f7363, 5247660, 149dea8, bd324f2, e26acd5, 6afaca8. 149dea8 (#8) built
the frozen_artifacts/add_result gate and leaves the result to #9; b1a1fdf (#5)
defers result-channel isolation to #9. No commit adds a verifier.
Merged PRs: #16, #17, #21, #24, #25, #29, #30, #31, #32, #33, #34, #35, #36, #41,
#42, #44, #45, #46, #48. Duplicate/superseding issues: none (#6 closed and
transferred scope into #9; #10 depends on #9).

Approved design points: three stages (untrusted probe under a subreaper
supervisor with inputs only; trusted judge after a confirmed sweep; in-process
assembly); readiness not SATISFIED -> verifier-owned `installation-ready`
criterion UNKNOWN; grader `digest` pin carried in the ledger and required.

## Section C - the approved plan

1. `skillc/verify.py` - GraderDef loader, supervised probe stage, judge stage, assembler, grade/regrade/grade_directory
2. `skillc/trial.py` - ledger grader identity accepts an optional digest pin
3. `evals/level1/slug-small-fix/grader.json` - grader definition, revision 2
4. `evals/level1/slug-small-fix/probe.py` - candidate-running harness, inputs only
5. `evals/level1/slug-small-fix/inputs.json` - held-out inputs without answers
6. `evals/level1/slug-small-fix/grade_slug.py` - becomes the judge; grade() composes probe and judge
7. `evals/level1/slug-small-fix/qualify.py` - certifies through verify.grade_directory
8. `evals/level1/slug-small-fix/README.md` - stages, certification, result-channel section
9. `tests/test_verify.py` - adversarial red/green controls end to end through trial.py
10. `tests/fixtures/trial-subject/fake_subject.py` - slug-candidate modes
11. `tests/test_level1_slug.py` - adapted to the split grader; inputs.json guard
12. `docs/specs/evaluation-facility/verification.md` - design note, trust assumptions, unobserved properties, credits
13. `docs/specs/evaluation-facility/records.md` - readiness boundary resolved; pointer
14. `docs/specs/evaluation-facility/capture.md` - pointer to the verifier
15. `PLAN.md` - #9 status
16. `AGENTS.md` - layout entry
17. `docs/flow-runs/issue-9.md` - this record
18. `docs/flow-runs/issue-9.as-read.md` - issue body as read

Scope: ~18 files, ~2,200-3,000 lines.
Risks: same-uid limits (store writes detected not prevented; answer key file readable on disk); Linux-only subreaper containment fails closed elsewhere; escape test timing; CI runs as root so no claim rests on permission denial; #5's certified grader changes shape (revision 2); readiness -> UNKNOWN is a semantic choice with per-case setup-as-goal left for later.
