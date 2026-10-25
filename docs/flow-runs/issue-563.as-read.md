<!-- flow-run n=1 id=7c7180522f804e0e850981cbc96f3019 -->
## Run 1 - issue #563 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #563
- Read at:      2026-10-24T23:06:43Z
- updatedAt:    2026-10-24T23:03:43Z   (context only - moves on comments and labels)
- Body digest:  56627000ea137c56927d1527710a8cc49d33466a10d6f878eb0972372d8f8551   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2342 of 2342 (cap 16384)

### Body as read
Observed live correctness failure in PR #562's exact-head CI pipeline 1083 at `ffc90c38b4c14f064b25fbbc6154f44d8dd5f7d7`: the outer pytest summary is **1 failed, 6875 passed, 106 skipped**. The actual failure is `tests/test_agent_trial.py::test_red_case_gate_entrypoint_declared_but_not_delivered_is_refused`, raising `FileExistsError: [Errno 17] File exists: '/tmp/skillc-trigger'` from `pathlib.mkdir` during backend setup. [Pipeline 1083](https://woodpecker.essent-ai.com/repos/20/pipeline/1083).

`skillc/docker_backend.py:356-359`, `_ensure_private_trigger_dir`, checks `if not path.exists()` and then calls `path.mkdir(parents=True, mode=0o700)` without handling a competing creator. Multiple xdist workers use the same `DEFAULT_TRIGGER_SOCKET_DIR`. On a fresh CI container, two can both observe absence; one creates the directory and the other raises before the attempt gets to its intended refusal. This code is unchanged by #536 / PR #562 and is present on main `a3e9ba8`.

Deterministic offline reproduction uses only an isolated `TemporaryDirectory` child: two calls to the real `_ensure_private_trigger_dir`, a barrier forcing both initial exists checks to see absence, then normal mkdir. Result: one success and one `FileExistsError`. No shared host path was deleted or mutated. Existing #550's TOCTOU item concerns cwd/confine_root and does not cover this mkdir race.

Required repair:

- Accept a correctly owned mode-0700 real directory created concurrently, after applying the same validation as an existing directory.
- Preserve wrong-owner and wrong-mode refusal. Do not use blanket `exist_ok=True` followed by chmod of a directory another caller created.
- Refuse competing non-directory or symlink paths without following/chmodding them; do not weaken the socket directory boundary while making startup tolerant.
- Commit deterministic concurrent-creator and unsafe-winner controls; prove the safe race regression red before the fix, then green, with existing refusal controls still red on bad inputs.
- Isolated scratch paths only; no host `/tmp` cleanup, real agent run, or paid evaluation is needed.

Filed separately while investigating PR #562's failed required CI during skillc-complete. #489's full suite is running unchanged; this repair must be a separate bounded prerequisite rather than mixed into #536/#489.

