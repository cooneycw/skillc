<!-- flow-run n=1 id=b8e6365c22a34ed0909f411c194e8f10 -->
## Run 1 - issue #387 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #387
- Read at:      2026-10-15T13:01:24Z
- updatedAt:    2026-10-14T12:54:38Z   (context only - moves on comments and labels)
- Body digest:  8d09c56b7a833550208a295c6bb3f1a3b37c63849a611a535f5ef7220cd2286e   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2765 of 2765 (cap 16384)

### Body as read
Found while gating #382 (branch `issue-382-…`, post-merge tree `5f84019`). The full finish gate failed only here: **1 failed, 3943 passed, 3 skipped**, in 8m41s against a usual ~6m45s, with other sessions' suites loading the host.

`tests/test_gate_witness.py::test_real_gates_run_with_real_exit_codes_while_the_primary_subject_keeps_running`, at `assert _ok_result(typecheck_reply)["exit_code"] == 0` (line ~874): **`assert 1 == 0`**. The `typecheck` gate is `python3 -c "raise SystemExit(0)"`.

## Mechanism

The test needs a **primary** subject to stay alive while two gates and a rerun execute against the same container. The primary is `python3 -c "import time; time.sleep(1.5)"`, the gates start after `time.sleep(0.3)`, and when the primary exits normally `DockerBackend.execute()` kills the container (`_kill_container(handle, "KILL")`). On a slow host the gates outlast the primary's 1.5s:

- If the container is already stopped when the gate is requested, `exec_in_attempt()`'s guard answers `reason="attempt-not-running"`, `exit_code=None`.
- If it stops in the gap between that guard's `inspect` and the fake `docker exec`'s own status check, the fake prints `Error: Container ... is not running` and exits **1** (`tests/fixtures/docker-backend/fake_docker.py`, `cmd_exec`). That is the observed failure.

**Deterministic reproduction of the first landing point:** inserting `time.sleep(1.5)` between the lint and typecheck gates fails with `{'accepted': True, 'exit_code': None, 'reason': 'attempt-not-running', ...}` (`assert None == 0`). The exit-1 landing point needs the stop inside a sub-millisecond window, so it is reached by load rather than on demand.

**Not caused by #382.** It reproduced 0/24 times with #382's fake and 0/24 with `main`'s, under the same 8-way parallel load. The mechanism involves no state-file locking, and #382's `fake_docker.py` change only adds a lock around `rm -f` plus a no-resurrect check.

## Acceptance

- [ ] **Hold the primary until the test releases it**, for example blocking on a FIFO or a file the test writes after the rerun, instead of a fixed `sleep(1.5)`. Its lifetime then no longer races the gates. Keep the property under test: no gate exec stops or kills the primary, and the primary still exits `"exited"` on its own after release.
- [ ] **Reproduce first:** commit the slow-gate variant (a delay between gates) as a case that fails on the current test and passes after the change.
- [ ] **Keep the red case:** a gate exec that stops the container must still fail the test.

Related: #382 (three load-sensitive docker-backend tests, plus a fake `rm -f` resurrection race) and #385 (the 5s fake-CLI setup budget). This is a third shape: a fixed subject lifetime racing the work it must outlive.

