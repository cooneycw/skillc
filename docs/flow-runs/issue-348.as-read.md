<!-- flow-run n=1 id=f7f10e687f504aa2b32b8e0fa1d7b0b9 -->
## Run 1 - issue #348 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #348
- Read at:      2026-10-12T17:09:38Z
- updatedAt:    2026-10-07T11:36:59Z   (context only - moves on comments and labels)
- Body digest:  1c87ec9036b3e5596e04c4552fe0fb90c2cbe621c32f5d74665d03c0c2a2152a   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2699 of 2699 (cap 16384)

### Body as read
**Type:** scope:task. **This blocks the #287 pilot.** Without it, the gate-witness criteria (#270 flow-check-honest, #271 gate-claim-honest) are UNKNOWN for every live attempt.
**Related:** #269 (GateWitness), #332 (forwarding shim and overlay), #334 (closure install, `gate_entrypoint`, overlay call), #270, #271.

## Finding

A worker found this while planning #270's criterion wiring, and it was confirmed on main.
- `GateWitness(` is constructed only in its own docstring example (`skillc/gate_witness.py`). No production code path creates one for a live attempt.
- `DockerBackend` already starts a controller-owned `DecideReplyChannel` when `self.trigger_decide` is set. That is the #183 mechanism, around `docker_backend.py:948`. Nothing sets it to a `GateWitness.decide` for an attempt.
- So the #332 shim, once #334 places it, sends `run_gate` requests that nothing serves. Every witnessed gate hits a channel failure (exit 125), and every gate reads UNKNOWN.
- Even with a record, nothing finalizes the `GateWitnessRecord` into the attempt's capture. The controller-exclusive channel for this already exists: the `trusted_observation` parameter of `grade_files` / `grade_directory` (#14). Nothing feeds it.

## Outcome

For an attempt whose profile declares `gate_entrypoint` (#334):
1. A `GateWitness` is constructed with the declared gates (the two prescribed `flow-finish-gate.sh` invocations, the real script at the harness root, workspace confinement and per-gate env), and set as the backend's `trigger_decide` before the agent starts.
2. After the attempt, the record is finalized and delivered to grading through `trusted_observation`, never through the subject-writable tree.
3. With no `gate_entrypoint`, there is no witness, exactly as now.

## Constraints

- `records.py` and `controls/` are unchanged (claude-power-pack#1369 pins them). If the record must reach the run record through a new field, stop and ask.
- A witness failure, such as the channel failing to start, refuses the attempt before spend. It never proceeds unwitnessed.
- Never trust the subject: the record comes only from the controller side.

## Acceptance

- [ ] A deterministic subject, following `reference.md`, in a profile-opted attempt produces a `GateWitnessRecord` with coverage `complete`, and grading receives it through `trusted_observation`.
- [ ] Red cases, mutation-checked:
  - a channel that is not started is refused;
  - a record supplied through the subject tree is ignored;
  - an attempt with no `gate_entrypoint` has no witness.
- [ ] Real-Docker evidence goes through the #315 runner (extend #334's live test, or add a floor file).

No live model trials are authorized by this issue.


<!-- flow-run n=2 id=6203df67f54548f3b070ff98d1893b06 -->
## Run 2 - issue #348 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #348
- Read at:      2026-10-12T19:40:58Z
- updatedAt:    2026-10-07T11:36:59Z   (context only - moves on comments and labels)
- Body digest:  1c87ec9036b3e5596e04c4552fe0fb90c2cbe621c32f5d74665d03c0c2a2152a   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2699 of 2699 (cap 16384)

### Body as read
**Type:** scope:task. **This blocks the #287 pilot.** Without it, the gate-witness criteria (#270 flow-check-honest, #271 gate-claim-honest) are UNKNOWN for every live attempt.
**Related:** #269 (GateWitness), #332 (forwarding shim and overlay), #334 (closure install, `gate_entrypoint`, overlay call), #270, #271.

## Finding

A worker found this while planning #270's criterion wiring, and it was confirmed on main.
- `GateWitness(` is constructed only in its own docstring example (`skillc/gate_witness.py`). No production code path creates one for a live attempt.
- `DockerBackend` already starts a controller-owned `DecideReplyChannel` when `self.trigger_decide` is set. That is the #183 mechanism, around `docker_backend.py:948`. Nothing sets it to a `GateWitness.decide` for an attempt.
- So the #332 shim, once #334 places it, sends `run_gate` requests that nothing serves. Every witnessed gate hits a channel failure (exit 125), and every gate reads UNKNOWN.
- Even with a record, nothing finalizes the `GateWitnessRecord` into the attempt's capture. The controller-exclusive channel for this already exists: the `trusted_observation` parameter of `grade_files` / `grade_directory` (#14). Nothing feeds it.

## Outcome

For an attempt whose profile declares `gate_entrypoint` (#334):
1. A `GateWitness` is constructed with the declared gates (the two prescribed `flow-finish-gate.sh` invocations, the real script at the harness root, workspace confinement and per-gate env), and set as the backend's `trigger_decide` before the agent starts.
2. After the attempt, the record is finalized and delivered to grading through `trusted_observation`, never through the subject-writable tree.
3. With no `gate_entrypoint`, there is no witness, exactly as now.

## Constraints

- `records.py` and `controls/` are unchanged (claude-power-pack#1369 pins them). If the record must reach the run record through a new field, stop and ask.
- A witness failure, such as the channel failing to start, refuses the attempt before spend. It never proceeds unwitnessed.
- Never trust the subject: the record comes only from the controller side.

## Acceptance

- [ ] A deterministic subject, following `reference.md`, in a profile-opted attempt produces a `GateWitnessRecord` with coverage `complete`, and grading receives it through `trusted_observation`.
- [ ] Red cases, mutation-checked:
  - a channel that is not started is refused;
  - a record supplied through the subject tree is ignored;
  - an attempt with no `gate_entrypoint` has no witness.
- [ ] Real-Docker evidence goes through the #315 runner (extend #334's live test, or add a floor file).

No live model trials are authorized by this issue.

