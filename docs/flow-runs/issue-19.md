# Flow run record - issue #19

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #19
- Base SHA:          c352bbeaa91157014ed9169e3320c07baba8d7ef
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (cooneycw), interactive "approved" in the /flow:auto session
- Recorded at:       2026-09-25T14:07:13Z

## Section B evidence
- commits since filing: c352bbe (PR #21, Woodpecker CI gate; does not touch
  tests/test_records.py; wires CI to `mypy skillc`, reproducing the blind spot)
- merged PRs since filing: #21
- duplicate/superseding issues: none (#18 closed, the originating issue)
- reproduced on c352bbe: `mypy .` 10 errors at the named lines; `mypy skillc` clean

## Section C - the approved plan
1. `tests/test_records.py` - annotate `rule` as `checks.Rule | checks.RecordRule`; split the two discovery branches into separately typed variables
2. `.woodpecker/ci.yml` - gate step runs `mypy .` instead of `mypy skillc`; negative-control step syncs `--extra dev`
3. `AGENTS.md` - verify line says `uv run mypy .`, matching CI
4. `ci/negative-control.sh` - second case: a scratch copy with one ill-typed line under tests/ must make `mypy .` fail naming that file

Scope: 4 files, ~25 lines.
Risks: isinstance narrowing relies on Rule/RecordRule being plain classes (confirmed);
widening to `mypy .` also typechecks future Python outside skillc/ and tests/.
