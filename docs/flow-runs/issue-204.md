# Flow run record - issue #204

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=2372c9da146e46bd9d8d2972bd77abd6 -->
## Run 1

- Run-id:            2372c9da146e46bd9d8d2972bd77abd6
- Run-start:         0df479b0005527bbf0251b921a5c7f6a275e0c57
- Issue:             #204
- Base SHA:          0df479b
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          the owner (cooneycw), in-session reply "approved" to the Step-3 ELI5 report
- Recorded at:       2026-09-30T16:30:00Z

### Section B evidence
Commits since filing: 0df479b (PR #205, #202 transcript retention - a declared dependency, not superseding).
Merged PRs inspected: #205, #201, #200. Open PRs: none. Duplicates/superseding: none (#203 is gated on this issue).

### Section C - the approved plan
Scope: acceptance items 1 (symmetric eligibility, Option B) and 2 (pipeline-check validity), plus the item-3
predeclaration stamped approved:false. The live run, runner, report and go/redesign/stop are a follow-up (Refs #204).

1. `skillc/calibration.py` - primary_endpoint (task+pipeline criteria only), readiness_beside, declaration loader/validator
2. `tests/test_calibration.py` - baseline reaches primary PASS (red: its verified result_status is not PASS); declaration refusals
3. `evals/level3/slugkit-pipeline/goal.md` - L3 goal plus the keep-ci/verify.py-passing-and-honest requirement
4. `evals/level3/slugkit-pipeline/fixture` - slugkit-installed fixture plus ci/verify.py (test + package steps, stdlib)
5. `evals/level3/slugkit-pipeline/grader.json` - four criteria incl. pipeline-green, pipeline-honest
6. `evals/level3/slugkit-pipeline/probe.py` - runs candidate pipeline clean + on proven mutants; UNKNOWN on crash/malformed/missing tool
7. `evals/level3/slugkit-pipeline/mutations.json` - M1 behaviour/test mutant, M2 packaging entry-point mutant
8. `evals/level3/slugkit-pipeline/grade_slugkit_pipeline.py` - the judge
9. `evals/level3/slugkit-pipeline/reference` - reference candidate plus alternatives/, benign/ and wrong/ candidates
10. `evals/level3/slugkit-pipeline/grader-controls` - always-pass, always-fail, crash, no-output, omits-criterion
11. `evals/level3/slugkit-pipeline/qualify.py` - certification gate incl. step attribution of M1/M2 on the fixture pipeline
12. `evals/level3/slugkit-pipeline/README.md` - task documentation (plus PROVENANCE.md)
13. `tests/test_level3_slugkit_pipeline.py` - runs qualify in the suite
14. `evals/calibration-204/run-manifest.json` - predeclaration, approved:false (plus README.md)
15. `evals/README.md` - layout entry
16. `AGENTS.md` - layout entry

Risks: M2 substitution may not apply to a valid variant (UNKNOWN noise); grader runs the pipeline three times (timeout);
#203 must adopt the new primary endpoint or the trap returns.
