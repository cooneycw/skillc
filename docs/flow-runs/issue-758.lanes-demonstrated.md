# Lanes demonstrated: #758

<!-- lanes-demonstrated run=b2371ebd7ca34f44b5adf5ec9139b0d7 plan=9a2076fa2936594e4d2e33ff28451661e69070b0f0530e7ce2a13a4839994981 -->

| Lane | Result | Evidence |
|---|---|---|
| Run placement | not run | host make verify targeted set passed (lint, typecheck, leak-check, timing-check, selftest 48/48, changelog-check, 472 targeted tests on bf67810); woodpecker ci NOT RUN until this PR's pipeline; host load runs (ci/load-repro.sh) NOT RUN, deferred by the orchestrator (Kyle prod / series 25) |
| Execution backend | passed | DockerBackend via the fake docker CLI: `tests/test_docker_backend.py::test_a_stalled_events_client_cannot_outlive_the_daemon_deadline` and the reviewed-oracle tests in `tests/test_inventory_runtime.py` |
| skillc distribution | passed | source checkout (the targeted set); ci/ and tests/ do not ship in the wheel |
| Python version | passed | 3.12 tested: the targeted set |
