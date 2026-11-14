# Lanes

Reviewed: 2026-11-14

| Lane | Values | How it is exercised |
|---|---|---|
| Checkout | main checkout / linked worktree | `tests/test_source_digest.py` covers root resolution in both layouts; the full gate is not shown in both |
| Run placement | Woodpecker CI (python:3.12-slim, kyleci agent) / host `make verify` / real-Docker runner VM (installed runner pin vs requested commit) | CI on every PR and on push to main; `make verify` locally; the VM certifies only the `real_docker` files declared in `ci/check_real_docker_ran.py` |
| Execution backend | DockerBackend / ManagedBackend | DockerBackend: fake `docker` CLI in CI, real daemon on the runner VM and in operator live runs; ManagedBackend: test stub only, no platform exists to run it against |
| Agent client | Claude Code / Codex (versions in `docker/trial/pinned-versions.json`) | fake clients in CI; real binaries version-checked on the runner VM; real model turns only in operator live runs |
| Client invocation | single attempt / declared resume turns / Codex app-server goals | scripted-peer and fake-client tests in CI; live only by operator run |
| Static-check target | portable / claude-code | `skillc selftest` runs each target's controls under `controls/<rule>/targets/<target>/` |
| Subject collection | CPP at pinned SHAs / mattpocock-skills / synthetic | frozen fixtures under `tests/fixtures` and `evals/subjects`; `make cpp-pin-watch` reports pinned-vs-main drift, not behavioural compatibility |
| Subject installation | skill surface / profile dependency closure; disposable host home / cold container; cached / uncached dependencies | `tests/test_profile_install_cold_container_live.py` on the runner VM |
| skillc distribution | source checkout (`uv sync`, editable) / built wheel in a clean venv | `make clean-install` and the CI `clean-install` step, each with sabotage controls |
| Python version | `>=3.11` declared / 3.12 tested | CI runs 3.12 only; 3.11 and newer versions are not covered |
