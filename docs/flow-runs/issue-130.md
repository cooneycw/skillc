# Flow run record - issue #130

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #130
- Base SHA:          a0fb533
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          owner (cooneycw), interactive reply "approved"
- Recorded at:       2026-09-27T17:36:32Z

## Section B evidence
Commits since issue creation: a0fb533 (#142), c07960e (#138), 30c593b (#128),
972236c (#137) - none touch derive_status / result_evidence /
criterion_vocabulary / artifact_digest. Merged PRs: #142, #140, #138, #137, #136,
#135, #128. Duplicate/superseding issues: none (#20 is the source nit store).
All four mutations reproduced exit 0 on a0fb533.

## Section C - the approved plan
1. `skillc/records.py` - VIOLATED beats a declared run state in derive_status; derived_status refuses a run state its criteria contradict; result_evidence refuses an undeclarable run_state; criterion_vocabulary refuses a missing/malformed id; artifact_digest types path/type/size
2. `docs/specs/evaluation-facility/records.md` - Derivation reordered per protocol.md section 4; rule table updated
3. `controls/derived-status/bad/unavailable-masks-violation.json` - the issue's mutation
4. `controls/derived-status/bad/not-run-masks-violation.json` - same with NOT_RUN
5. `controls/derived-status/good/unavailable.json` - legitimate UNAVAILABLE twin
6. `controls/derived-status/good/not-run.json` - legitimate NOT_RUN twin
7. `controls/result-evidence/bad/arbitrary-run-state.json` - run_state "arbitrary"
8. `controls/criterion-vocabulary/bad/missing-criterion-id.json` - criterion without id
9. `controls/artifact-digest/bad/null-path-type-size.json` - nulls with a valid digest
10. `tests/test_records.py` - precedence and FAIL-plus-run-state unit tests
11. `CHANGELOG.md` - Fixed entry

Scope: 4 modified, 7 new control files, ~60 code lines.
Risks: an out-of-tree producer declaring UNAVAILABLE over a VIOLATED criterion is
now refused (none committed); trial.add_result still stores such a result (Nit Store).
