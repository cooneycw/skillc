<!-- flow-run n=1 id=423c29eb9c874daf967414e9e8d72475 -->
## Run 1 - issue #338 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #338
- Read at:      2026-10-12T14:14:10Z
- updatedAt:    2026-10-07T11:37:20Z   (context only - moves on comments and labels)
- Body digest:  ed712376a2c068b41cd3a90c7cfaf8d049fff7adc7bebd96e4023513eb800268   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 4324 of 4324 (cap 16384)

### Body as read
**Type:** scope:task (security-relevant correctness gap). **Related:** #269, #332, #183.

## Finding

Found by counter-model review (Codex) on #332's branch diff, against code introduced there: `GateWitness._confine_requested_cwd` (`skillc/gate_witness.py`).

`_confine_requested_cwd` resolves a subject-forwarded `cwd` via a REAL in-container `realpath` (`backend.resolve_realpath_in_attempt`), checks the resolved path is the attempt's declared `workspace_root` or beneath it, and returns that resolved path string. `_decide_run_gate` then uses it later as `exec_in_attempt(..., cwd=gate_cwd, ...)`, which ultimately runs `docker exec -w <gate_cwd> ...`.

Between the `realpath` confirmation and the actual `docker exec -w` call, there is a real time gap: the gate name is validated, `_in_flight`/`_Run` claims are taken under a lock, `tree_digest_fn()` runs, and `_exec_lock` is acquired before the exec itself happens. The attempt's own primary subject process is still live and running inside the SAME container for the whole of a gate's execution (that concurrency is `exec_in_attempt`'s own documented, intentional property — see #269). A subject with ordinary write access to its own workspace can, in that gap, rename a directory component inside the already-resolved path and replace it with a symlink pointing outside `workspace_root`. `docker exec -w` resolves the path at the time it runs, inside the container's live filesystem — it does not re-verify against the earlier confinement check, and does not bind to an already-opened directory descriptor.

So a successful confinement check at request time does not guarantee the exec that eventually runs stays confined. This is a classic TOCTOU: the check and the use are separated by real wall-clock time and by code that can block (a slow `tree_digest_fn`, lock contention from a concurrent gate).

No test in this codebase exercises this race today — `tests/test_gate_witness.py`'s cwd-confinement cases check only that a *given* resolved path is accepted or refused at confinement time, never that the resolved path still means the same thing when `exec_in_attempt` actually uses it.

## Consequence

If exploitable, a subject under evaluation could get the controller to run a declared gate's real argv with a working directory outside the attempt's own workspace root, inside the same container — undermining the one guarantee `workspace_root` confinement exists to provide for #269/#332's gate-witness mechanism. The severity depends on what else is reachable from that container (the project's own stated posture is that containers are placement hygiene, not a hard trust boundary — see `docs/adr/0007-vm-trust-boundary.md` — but the gate-witness mechanism's own documented purpose is still to produce a trustworthy *within-container* confinement guarantee, and this gap undermines that specific guarantee on its own terms).

## Outcome

Either:
- close the TOCTOU window (e.g. resolve and open the target directory, then exec bound to that open directory rather than to a path string Docker re-resolves later — if Docker's own interface allows it), or
- independently re-verify the resolved path's identity immediately before or as part of the exec (e.g. a post-exec check that the process's actual cwd, read from `/proc/<pid>/cwd` inside the container, still resolves to the same real path), or
- establish and document why the subject cannot mutate the relevant part of the directory hierarchy during gate execution in this codebase's actual deployment shape, if that is in fact already true.

## Constraints

- Scope this to `GateWitness`/`DockerBackend.exec_in_attempt`'s cwd-confinement path specifically; do not widen into a general filesystem-isolation redesign.
- Add a committed race-case test: resolve a cwd, then replace the resolved directory (or an ancestor) with a symlink pointing outside `workspace_root` before the exec actually runs, and confirm the real exec is refused or does not escape.

## Acceptance

- [ ] A design is proposed and reviewed before any code lands (same process every #269/#332/#183 change has followed).
- [ ] A committed, mutation-checked test demonstrates the race is closed (red before the fix, green after).
- [ ] No change to the confinement behavior for any currently-tested, non-racing case.
