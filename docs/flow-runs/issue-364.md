# Flow run record - issue #364

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=002cba7806264694b4074dfa9136919b -->
## Run 1

- Run-id:            002cba7806264694b4074dfa9136919b
- Run-start:         76a68a6cd9c9eeb52f09d5d8d7063866e22d447e
- Issue: #364
- Base SHA: 76a68a6
- Necessity verdict: Still needed
- Approval: granted
- Approver: user ("approved")
- Recorded at: 2026-10-12

### Section B evidence
No commits or PRs landed after filing at 2026-10-12T17:41:59Z. Inspected earlier PRs #361, #359, #358 and #357; base 76a68a6. Related issues #307, #219 and #356 concern git availability, isolation and Docker failures. No duplicate/superseding issue or unpushed sibling change touching inspected paths.

### Section C - the approved plan
1. `pyproject.toml` - add pytest-xdist.
2. `uv.lock` - lock its dependencies.
3. `Makefile` - run parallel tests and validate their population.
4. `.woodpecker/ci.yml` - matching parallel options and population control.
5. `ci/check_pytest_population.py` - compare collection with XML results; support serial/parallel outcome comparison.
6. `ci/pytest-population-control.sh` - exercise passing and failing fixtures.
7. `controls/pytest-population/collected.txt` - expected population.
8. `controls/pytest-population/good.xml` - complete report.
9. `controls/pytest-population/short.xml` - report missing a test.
10. `tests/test_pytest_population.py` - missing, malformed, empty and mismatched inputs.
11. `tests/test_ci_local_gate_coverage.py` - local/CI wiring and invocation parity.
12. `tests/test_makefile_pipefail_control.py` - isolate nested reports.
13. `AGENTS.md` - verification instructions.
14. `README.md` - parallel verification.

Scope: approximately 14 files, 350-550 lines. Risks: timing-sensitive tests and shared resources; necessary serialization preserves coverage. Validation: same-commit serial/parallel outcome comparison, population and git-test red controls, slowest-test report, same-CI-VM before/after gate timings. Further optimizations depend on measurements.
