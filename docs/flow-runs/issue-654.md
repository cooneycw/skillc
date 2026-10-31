# Flow run record - issue #654

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=7b5f0d7dd246474983553442203138fc -->
## Run 1

- Run-id:            7b5f0d7dd246474983553442203138fc
- Run-start:         c177eb5b1d9a1381125ac7b60d807164959fb0c4
- Issue:             #654
- Base SHA:          c177eb5b1d9a1381125ac7b60d807164959fb0c4
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          repository owner (interactive session reply "approved")
- Recorded at:       2026-10-31T12:47:00Z

### Section B evidence
- commits: none on origin/main since 2026-10-31T11:25Z touching ci/real-docker/ or ci/real_docker_optin.py
- PRs: #653 (merged before filing; exposed the defect); none since
- dup/super: #652 (closed, symptom); none duplicate
- leak introduced by 1e7ae69 (#578, 2026-10-25), also leaks into the opt-in lane

### Section C - the approved plan
1. `ci/real-docker/run-real-docker` - drop PYTHONPATH from the process-wide export; run uv sync/pytest under env -u PYTHONPATH; correct the R1 header comment
2. `ci/real_docker_optin.py` - drop PYTHONPATH from the pytest child env in execute()
3. `tests/test_run_real_docker_product_import.py` - hermetic end-to-end negative control: certifying pytest and opt-in pytest import skillc from WORK_CHECKOUT, red on the pre-fix code
4. `ci/real-docker/README.md` - document the product-import rule and the re-pin step

Scope: 4 files, ~150 lines. Risk: CI image tooling (flock/git); fix only takes effect after an operator re-pin.
