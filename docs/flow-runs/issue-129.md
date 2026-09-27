# Flow run record - issue #129

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #129
- Base SHA:          16e58d5
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), interactive reply "approved"
- Recorded at:       2026-09-27T13:30:00Z

## Section B evidence
- commits: none touching skillc/judge_mcp_second_opinion.py since 3d00d85 (#96)
- PRs: #112, #126 merged meanwhile; neither touches the judge
- dup/super: none

## Section C - the approved plan
1. `skillc/judge_mcp_second_opinion.py` - _write uses a non-blocking fd for the write loop; BlockingIOError returns to select until the deadline; restore flags in finally
2. `tests/test_judge_mcp_second_opinion.py` - deterministic regression: pipe pre-filled to one free page, 64 KiB message, timeout 0.5, JudgeUnavailable within 5s, SIGALRM guard
3. `CHANGELOG.md` - Fixed entry

Scope: 3 files, ~50 lines. Risks: shared fd flags (restored in finally); SIGALRM POSIX/main-thread only.
