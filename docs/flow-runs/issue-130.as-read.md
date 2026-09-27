# Issue #130 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #130
- Read at:      2026-09-27T17:31:56Z
- updatedAt:    2026-09-27T13:15:48Z   (context only - moves on comments and labels)
- Body digest:  3705437cda1a6a048cfa9617b42b7d8d4c69e5e7381d8047b39c30cefbcfc9d1   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2514 of 2514 (cap 16384)

## Body as read
Consolidated from the Nit Store (#20). **Severity: high.** This is a live correctness defect, so it is filed as its own issue rather than left as a nit.

## Defect

`skillc/records.py` `derive_status` returns a declared `run_state` (`UNAVAILABLE` / `NOT_RUN`) before it examines criteria. So a record with an established mandatory `VIOLATED` criterion can be relabelled `UNAVAILABLE` and pass `check-records` cleanly. `protocol.md` section 4 allows UNAVAILABLE only when no task failure has already been established. `records.md` Derivation gives the override first. The two documents disagree, and the code follows the weaker one.

## Reproduced on origin/main `16e58d5` (2026-09-27)

- `controls/derived-status/good/record.json` (status FAIL; criteria `[(mandatory, VIOLATED), (mandatory, UNKNOWN)]`), copied alone into a directory: exit 0.
- The same record with `"run_state":"UNAVAILABLE"`, `"reason":"provider unavailable"`, `"status":"UNAVAILABLE"`: **exit 0, 0 errors**. The VIOLATED criterion and its evidence are still in the record.
- Control: the same record with `"status":"PASS"` and no run_state gives exit 1 (`derived-status ... derive 'FAIL'`). The rule can go red. This path simply never reaches it.

## Related record-shape gaps (same reassessment, https://github.com/cooneycw/skillc/issues/20#issuecomment-5847815869)

Each was reproduced from a good v2 fixture with all rules enabled at `6afaca8`. Re-verify each at the fix's pin and commit it as a bad case:
- `result_evidence` / `derived_status`: `"run_state":"arbitrary"` on an unchanged good result exits 0. The records table allows only UNAVAILABLE or NOT_RUN.
- `criterion_vocabulary` / `result_evidence`: deleting the first criterion's `id` exits 0. (`records.py:905` now checks criterion ids in one path, so this one may already be fixed. Confirm it with the red case.)
- `artifact_digest`: `path`, `type` and `size` set to null, with a valid digest kept, exits 0.

## Acceptance

- [ ] Reconcile `records.md` Derivation with `protocol.md` section 4. Then either reject a declared run_state that contradicts an established mandatory VIOLATED, or keep FAIL.
- [ ] One committed bad case for each mutation above, each shown red on the unfixed code. Also good twins: a legitimate UNAVAILABLE and a legitimate NOT_RUN, and FAIL-with-UNKNOWN.
- [ ] `skillc selftest` and `ci/negative-control.sh` pick up the new cases.

Blocks trusting #12's result accounting. Sources: https://github.com/cooneycw/skillc/issues/20#issuecomment-5847815869.

