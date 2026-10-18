# Flow run record - issue #281

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=ff553e1a966e4e76be72dbe13dd74b05 -->
## Run 1

- Run-id:            ff553e1a966e4e76be72dbe13dd74b05
- Run-start:         5d0f5722217f7345bebf0f423741a7b4fb1e5fa2
- Issue:             #281
- Base SHA:          5d0f5722217f7345bebf0f423741a7b4fb1e5fa2
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-18T01:27:24Z

### Section B evidence
- #281 open; prerequisites #280 (merged 5d0f572) and #269 (closed); no commit addresses it; #282 (skillc-worker-C) builds on the same profile, not this task
- level choice D3: docs/specs/evaluation-facility/spec.md level table ("3 - Integration ... The installed consuming path works"); precedent evals/README.md:13 (level3/slugkit-pipeline)
- CPP defects found while grounding: claude-power-pack#1477 (nonexistent build backend), #1478 (dev tools in an extra that uv run never installs)

### Section C - the approved plan
1. `docker/cicd-project-trial/Dockerfile` - one metadata COPY plus one locked uv sync layer on a validated cicd-runtime receipt
2. `docker/cicd-project-trial/build.py` - binding checks (base layers + exactly the declared layers, inherited config, byte-identical descriptor, measured offline tool versions); cicd-project-runtime receipt binding the fixture lock digest; #414 cleanup rules
3. `docker/cicd-project-trial/README.md` - recipe, receipt, controls
4. `skillc/runtime_supply.py` - cicd-project-runtime receipt kind (closed schema, embedded cicd receipt, lock digest); require_kind; selected_runtime unchanged
5. `tests/test_runtime_supply.py` - the new kind's schema, kind cross-checks, mutations
6. `scripts/project_init_fixture.py` - replays CPP project:init Step 3 + Step 4a + pipeline --write at the pin; records digests; check mode
7. `evals/level3/cicd-pipeline/` - goal.md, grader.json (runtime cicd-project-runtime), inputs.json, probe.py (closed-table pipeline step executor), grade_cicd_pipeline.py, qualify.py (declared subset vs full, manifest count check), README.md, PROVENANCE.md, patches/ (cpp-1477, cpp-1478), fixture/, reference/, unpatched-real/, alternatives/, benign/, wrong/, grader-controls/
8. `evals/level3-heldout/cicd-pipeline/` - sealed held-out project and its reference, outside the task surface
9. `tests/test_level3_cicd_pipeline.py` - offline: judge on committed probe reports, patch-still-applies (deliberate-update message), held-out tool versions == dev, command-table closure, no held-out bytes on the task surface, manifest-count red
10. `tests/test_level3_cicd_pipeline_live.py` - real_docker: runtime chain + qualify through DockerBackend; declared subset unlocked, full matrix under run.lock
11. `ci/check_real_docker_ran.py` - floor entry for the live test
12. `tests/test_real_docker_verdict.py` - floor tests
13. `evals/README.md` - task row
14. `docs/specs/evaluation-facility/profiles.md` - pointer from the cicd profile section
15. `CHANGELOG.md` - entry

Conditions from the approver: D4 split with a committed subset constant (reference, unpatched-real, wrong/unconditional-success, wrong/disabled-stage, grader-controls/always_pass); the full run asserts it executed every manifest case (red: one filtered case fails); the subset reports "subset (N of M)" in its QUALIFY line; floor/EXPECT_TOTAL coordinated with skillc-worker-C (#282); PROVENANCE names CPP URL, pin, licence and each patch's CPP issue; the patch-still-applies failure says "CPP fixed #147x; drop the patch deliberately"; heldout sealing stated and tested; 2 review passes; pre-hold ruff, full mypy, leak-check.
Scope: large (~25 entries; fixture trees dominate). Risks: plant preconditions depend on pinned tool versions; generated YAML is CPP's at 86641e8; single interpreter makes other matrix rows UNKNOWN; full qualify cost handled by the D4 split.
