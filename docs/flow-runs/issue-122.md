# Flow run record - issue #122

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #122
- Base SHA:          16e58d5
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          the owner (interactive session, "approved")
- Recorded at:       2026-09-27T00:00:00Z

## Section B evidence
Commits since filing: none touching skillc/demo.py, skillc/cli.py or tests/test_demo.py
(HEAD 16e58d5, #112 release docs). Merged PRs inspected: #126, #125, #123, #121, #120,
#119, #117, #116, #115, #113, #112 - none adds a timeout or cancellation seed. Open PR
#128 edits lifecycle.run_through_backend, not the fields the seeds read.
Duplicate/superseding issues: #79, #81, #10 (all closed, none supersedes).

## Section C - the approved plan
1. `skillc/demo.py` - timeout seed, cancel-target child, cancellation seed (real SIGINT to the child's process group, foreign container untouched), run_control returns a ControlResult with a leak-checked per-seed block
2. `skillc/cli.py` - hidden --cancel-target flag routed inside cmd_demo's try; --control prints the block via print_paste_back
3. `tests/test_demo.py` - green and red cases for both seeds (timeout enforcement disabled, interrupt scoping disabled, child never ready); existing run_control tests updated
4. `tests/fixtures/demo-control/unscoped_interrupt_child.py` - red-case child that sweeps every owned container
5. `docs/specs/evaluation-facility/operator-demo.md` - the --control section: six seeds and the block
6. `CHANGELOG.md` - Unreleased entry (Refs #122)
7. `docs/flow-runs/issue-122.md` - this record (and its as-read snapshot)

Scope: 7 files, ~450-550 lines. Risks: the cancelled attempt reads already-absent
(the driver's finally tears down first), accepted with an independent post-check -
owner approved; SIGINT timing rests on a 1s settle after the exec marker; fake exec
leaves a short sleeper; CHANGELOG conflict with #128; live run still owed (Refs, not Closes).

## Revision 1 - owner-approved scope addition (after PR #138 opened)

The issue body gained five items folded in from the Nit Store (#20) after this
plan was approved (ISSUE_DRIFT at Step 6). The owner chose to add all five to
this PR. The plan above is unchanged; these are additions:

8. `skillc/demo.py` - reply-only control requires a real exit-0 execution and the missing-canary reason; the fleet item is always emitted (incomparable = NOT EXERCISED); fleet changes not attributable to this run's attempt ids become observations, not failures; the grading probe's attempt id is recorded and swept
9. `skillc/verify.py` - `grade_files` takes an optional `recorded_attempt_ids` list and appends the probe's attempt id before `prepare()`
10. `skillc/cli.py` - the interrupt sweep is shielded from a second SIGINT
11. `tests/test_demo.py` - a red case for each of the five
12. `tests/fixtures/demo-control/never_live_child.py` - added by the counter-model review (a red case for the live-exec proof), not in the original plan
