# Flow run record - issue #18

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #18
- Base SHA:          857781f92098517a5a04d00a8d6ca1e964b36e87
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (cooneycw), interactive "approved" in session
- Recorded at:       2026-09-25T13:16:50Z

## Section B evidence
- commits since 2026-09-25T13:13:36Z on origin/main: none (head 857781f)
- PRs merged since: none
- duplicate/superseding issues: none (search "CI woodpecker" returns only #18)
- Woodpecker: cooneycw/skillc registered (repo id 20, active, private, untrusted); no .woodpecker/ in repo

## Section C - the approved plan
1. `.woodpecker/ci.yml` - new; push on main + pull_request; pinned to host: kyleci; gate step (selftest, pytest, ruff, mypy via uv sync --frozen --extra dev) and negative-control step; private venv per step
2. `ci/negative-control.sh` - new; derive a rule id from skillc rules, remove its control dir in a scratch copy, require exit 1 AND "UNPROVEN <rule>"; baseline copy must pass first; SKILLC override for proving the step can fail
3. `AGENTS.md` - Verify section states what CI runs, including the negative control
4. `docs/flow-runs/issue-18.md` - this record

Scope: 4 files, ~90 lines. Risks: kyleci queue sharing; red is advisory until branch protection requires ci/woodpecker/pr/ci (owner's call, out of scope); negative control covers only the missing-control case until #2.
