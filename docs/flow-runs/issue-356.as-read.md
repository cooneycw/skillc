<!-- flow-run n=1 id=8ed3689975004c7895260eec660adeb2 -->
## Run 1 - issue #356 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #356
- Read at:      2026-10-12T14:50:30Z
- updatedAt:    2026-10-12T14:50:02Z   (context only - moves on comments and labels)
- Body digest:  9c48db93ea3778657935845204161b0fc8906ba786e37c7fe0e488a461e2f4a4   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3352 of 3352 (cap 16384)

### Body as read
## Problem

`docker/trial/Dockerfile:210` does not build on this host's Docker engine (29.8.2, BuildKit):

```
COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION} /uv /uvx /usr/local/bin/
ERROR: failed to build: failed to solve: variable expansion is not supported for --from, define a new stage with FROM using ARG from global scope as a workaround
```

The line came in with #343 (PR #347, e43445a). Every test that builds the trial image therefore errors at setup on a real daemon, with no assertion ever reached:

- `tests/test_trial_image_build_live.py::test_skillc_disrupt_tool_is_installed_executable_and_runs`
- `tests/test_trial_image_tools_live.py` (5 tests: uv pin, python floor, make/bash/git)
- `tests/test_profile_closure_preflight_live.py::test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner`

CI has no daemon and skips all of these, so `make verify` is red only on a host that has a daemon. A fresh trial image cannot be built here, and that blocks the real-daemon campaign (#315).

Reproduced on clean `origin/main` 450445d: `uv run pytest -q tests/test_trial_image_tools_live.py`.

## Likely fix

Do what the error message suggests: declare `ARG UV_VERSION` in the global scope (before the first `FROM`), add a named stage `FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-bin`, and use `COPY --from=uv-bin ...`. Keep the pin.

## Also in scope (added at the owner's request): the cold-container import failure

`tests/test_profile_install_cold_container_live.py::test_profile_runs_cold_with_no_operator_mounts` is the eighth real-daemon failure from the same `make verify` run. It has a different cause: the in-container import check fails with

```
File "/disposable-home/Projects/claude-power-pack/lib/security/orchestrator.py", line 13
  from .modules import debug_flags, env_files, gitignore, gitleaks, npm_audit, permissions, pip_audit, secrets
ImportError: cannot import name 'secrets' from 'lib.security.modules'
```

On the host, `~/Projects/claude-power-pack/lib/security/modules/secrets.py` exists (CPP HEAD 1dc4aaf1), so the module is lost when CPP is copied into `/disposable-home`. Suspected but not verified: the copy or materialize step filters out paths named like secrets, which is a reasonable leak guard but here removes a real module. Find the actual cause before fixing. If it is a deliberate name filter, narrow it (for example to secret-bearing files rather than any `secrets.py`) so the guard still catches what it was meant to catch, and show that it still does.

Same on clean `origin/main` 450445d. Originally recorded in the nit store: https://github.com/cooneycw/skillc/issues/20#issuecomment-6126392291

Repro: `uv run pytest -q tests/test_profile_install_cold_container_live.py`

## Acceptance

- `docker build docker/trial` succeeds on Docker 29.x.
- The 7 tests above pass against a real daemon.
- `test_profile_runs_cold_with_no_operator_mounts` passes against a real daemon, and any secrets-name filter that was narrowed still rejects a real secret-bearing file (its negative control).
- `make verify` on a daemon host has no real-Docker failures from either cause.
- `test_uv_is_present_at_the_pinned_version` still fails if the pin is changed. That is its negative control: show it once.

Found while running the #355 finish gate (PR to follow); unrelated to that change.


