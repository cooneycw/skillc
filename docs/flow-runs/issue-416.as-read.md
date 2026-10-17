<!-- flow-run n=1 id=05376e3ecac04f7e9a099aa4379199d3 -->
## Run 1 - issue #416 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #416
- Read at:      2026-10-17T14:01:52Z
- updatedAt:    2026-10-17T13:59:42Z   (context only - moves on comments and labels)
- Body digest:  cf9a1ed88e5bc79ec72edc718199abcb9314114afbf0ad96db5865c461e7e54e   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2415 of 2415 (cap 16384)

### Body as read
## Problem

`DockerBackend.prepare()` promises to raise `BackendUnavailable` when it cannot start a container. When `docker run -d` times out, the except path at `skillc/docker_backend.py:1014` runs a best-effort `docker rm -f <name>` with its own `timeout=self.daemon_timeout`. That call is **not guarded**: if the cleanup also times out, its `subprocess.TimeoutExpired` escapes `prepare()` raw, chained onto the original, and the `BackendUnavailable` is never raised. The non-zero-exit path at `:1024` has the same unguarded cleanup.

The comment says a hanging cleanup "must not turn a raising prepare() into a hanging one". The bound does that. But a cleanup that HITS the bound turns a `BackendUnavailable` into an uncaught `TimeoutExpired`, which any caller that handles `BackendUnavailable` will not catch. A daemon slow enough to time out `run` is the likeliest to be slow on `rm` as well, so this fires in exactly the case the cleanup exists for.

## Evidence

- **CI, main push pipeline 806 (`bb24739`):** `tests/test_live_docker_budget.py::test_a_start_slower_than_the_budget_is_still_refused[5.0-6.0]` failed with `subprocess.TimeoutExpired ... 'rm', '-f', 'skillc-a-live-budget-0000000000002']' timed out after 5.0 seconds`, raised at `skillc/docker_backend.py:1014` "During handling of" the `run` timeout at `:1001`. The test expects `BackendUnavailable(match="timed out")`. That red was being read as a timing flake (#412); it is this defect, surfaced by load.
- **Deterministic local repro** at `371d19c`, fake CLI, `daemon_timeout=1.0`, `.delay-run` = 2.0 s:
  - no `rm` delay: `BackendUnavailable` (the contract holds)
  - `.delay-rm` = 2.0 s: `ESCAPED TimeoutExpired: ... 'skillc-a-repro-rm-000000001']' timed out after 1.0 seconds`

## Outcome and acceptance

- [ ] A cleanup `docker rm -f` that fails or times out in either `prepare()` failure path still results in `BackendUnavailable`. The cleanup failure is reported in the message (or chained), not lost.
- [ ] A regression test using `.delay-run` + `.delay-rm` (no host load needed) FAILS on the current code and passes after the fix.
- [ ] Check other best-effort cleanup calls in `docker_backend.py` that run inside an `except` with a `timeout=` for the same shape, and either cover them or list them.

Found while measuring #412 (cpp-final-fix session). This is why `live_docker_budget[5.0-6.0]` is NOT only a headroom question there.

