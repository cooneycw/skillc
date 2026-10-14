# Flow run record - issue #385

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=b2a56d3b6f0040399c6879e47642fdc4 -->
## Run 1

- Run-id:            b2a56d3b6f0040399c6879e47642fdc4
- Run-start:         552eaa6e3b375d0e258bfe2db6857b9dd02880cf
- Issue:             #385
- Base SHA:          552eaa6e3b375d0e258bfe2db6857b9dd02880cf
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          cooneycw (interactive "approved" in the /flow:auto session; recommendations taken: proceed now despite #382 overlap, keep calibration's 120s as a documented exception)
- Recorded at:       2026-10-14T00:00:00Z

### Section B evidence
commits: none on origin/main touching tests/ or skillc/docker_backend.py since 2026-10-14T10:53Z (main = 552eaa6, #381).
PRs: #381 (the base). Issues considered: #382 (open, owns 3 other tests; live locked worktree ffc1435 with 4 unpushed commits on tests/test_docker_backend.py), #221, #133 (closed predecessors).

### Section C - the approved plan
1. `tests/fixtures/docker-backend/fake_docker.py` - `.delay-SUBCOMMAND` sentinel (seconds) sleeping before the named fake subcommand runs, for a deterministic >5s setup call.
2. `tests/test_docker_backend.py` - `_backend()` defaults to FAKE_DOCKER_DAEMON_TIMEOUT; direct constructions adopt it; timeout-firing tests pass an explicit small daemon_timeout; regression test with a 6s `.delay-run`.
3. `tests/test_agent_trial.py` - adopt the constant in 5 constructions.
4. `tests/test_agent_trial_gate_witness.py` - adopt the constant.
5. `tests/test_behavioral_eval_consumer_contract.py` - adopt the constant.
6. `tests/test_collection_conformance.py` - adopt the constant in the direct construction.
7. `tests/test_collection_evidence_export.py` - adopt the constant.
8. `tests/test_configuration_compare_real_producer.py` - adopt the constant.
9. `tests/test_docker_conformance.py` - adopt the constant.
10. `tests/test_gate_overlay.py` - adopt the constant.
11. `tests/test_gate_witness.py` - adopt the constant in 5 constructions.
12. `tests/test_matched_pilot_run.py` - adopt the constant at line 393.
13. `tests/test_selection_probe.py` - adopt the constant at line 753.
14. `tests/test_reap.py` - pass timeout=FAKE_DOCKER_DAEMON_TIMEOUT to reap.snapshot/reap.reap.
15. `tests/test_calibration_run.py` - keep 120s, documented as a justified exception citing conftest.

Scope: ~15 files, ~80-150 lines. Risks: merge collision with in-flight #382 in tests/test_docker_backend.py; a missed timeout-firing test would wait 30s (caught by before/after durations). Explicit timeout=5 sites deferred to the nit store.
