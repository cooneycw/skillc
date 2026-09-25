# Flow run record - issue #2

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #2
- Base SHA:          e02a217ad0426b027d3df53afcb07e5354db6896
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (cooneycw), interactive "approved #2 as-is." in the /flow:auto session
- Recorded at:       2026-09-25T16:34:56Z

## Section B evidence
- commits since filing touching skillc/ ci/ tests/ controls/: 36bc172 (#19, mypy
  scope), c352bbe (#18, CI negative control covering only the missing-control case;
  its header defers empty populations, unparseable bad case and unknown --rule to #2),
  857781f (record rules)
- merged PRs since filing: #29, #25, #24, #21, #17 - none address the three defects
- duplicate/superseding issues: none (#27 depends on #2)
- reproduced on e02a217: empty name-spec/good -> selftest exit 0 "11/11"; blinded
  name-spec + unparseable bad -> "ok name-spec", exit 0; `check --rule typo` and
  `check-records --rule typo` -> exit 0

## Section C - the approved plan
1. `skillc/checks.py` - register the frontmatter parser as rule `frontmatter`; `parser` flag on rules (frontmatter, record-envelope); run/run_record raise ValueError on an unknown selector; keep run's early return
2. `skillc/cli.py` - check/check-records reject unknown --rule before scanning (exit 2, valid ids listed); selftest reports EMPTY and UNPARSED and counts only findings attributed to the rule under test
3. `controls/frontmatter/bad/no-frontmatter/SKILL.md` - parser control bad case
4. `controls/frontmatter/good/no-frontmatter/SKILL.md` - parser control good case
5. `controls/record-envelope/bad/unreadable.json` - malformed-JSON bad case for the record parser path
6. `tests/test_checks.py` - committed red cases: empty good, empty bad, malformed bad + blinded rule, unparsed good, parser rule without an unparseable bad, unknown selector on both commands, ValueError from run/run_record, healthy selftest still passes
7. `tests/test_records.py` - exempt parser rules from the no-frontmatter-in-own-bad assertion; refresh the docstring count and attribution note
8. `ci/negative-control.sh` - add empty-good-population (EMPTY, exit 1) and unknown-selector (exit 2) refusals
9. `tests/test_negative_control.py` - stub red cases for each new script branch
10. `README.md` - EMPTY/UNPARSED verdicts, parser controls, rule count
11. `docs/decisions/0001-every-check-ships-a-redcase.md` - EMPTY/UNPARSED, attribution, parser controls
12. `docs/specs/evaluation-facility/records.md` - record-envelope row notes its unreadable control
13. `docs/flow-runs/issue-2.md` - this record

Scope: ~13 files, ~350 lines, mostly tests.
Risks: registering `frontmatter` changes `skillc rules` output and the selftest total
(11 -> 12); a library caller relying on an unknown `only` being a silent no-op now
gets ValueError (intended).
