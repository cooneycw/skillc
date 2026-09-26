# Flow run record - issue #37

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #37
- Base SHA:          52476609b8ab0eb2d4a2bf044ca6ee2b1de59686
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (cooneycw), in the interactive session
- Recorded at:       2026-09-26T15:32:14Z

## Section B evidence
Commits since filing (2026-09-26T14:29Z): 5247660, 85f7363 - docs only, none
touching skillc/records.py or skillc/checks.py (`git diff 3c243a1 origin/main`
on both is empty). Merged PRs: #41, #42 (docs). #32/#33 match "mandatory" but
predate the issue. Duplicate/superseding issues: none (#4 closed origin; #9,
#13, #15 unrelated).

## Section C - the approved plan
1. `skillc/records.py` - criterion_vocabulary refuses a criterion whose `mandatory` is not a real bool (isinstance bool, not int); derive_status unchanged
2. `controls/criterion-vocabulary/bad/string-mandatory.json` - new known-bad control: the issue's reproduction
3. `controls/criterion-vocabulary/good/optional-criterion.json` - new known-good control with a real `false`
4. `tests/test_records.py` - regression tests: "true"/"false", 1/0, missing key refused; end-to-end check-records on the repro exits non-zero; red run on unfixed code
5. `docs/specs/evaluation-facility/records.md` - `mandatory` is a JSON boolean; add the case to the criterion-vocabulary row

Scope: small, ~60 lines, 5 files (+ this record).
Risk: a MISSING `mandatory` key is now refused too (was silently optional - the
same hole; records.md already lists the field as required). No committed JSON
record in the repo has a missing or non-bool `mandatory`.
