<!-- flow-run n=1 id=bb359f87b87c4093b5d73bdea4d67feb -->
## Run 1 - issue #437 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #437
- Read at:      2026-10-17T19:19:05Z
- updatedAt:    2026-10-17T19:18:47Z   (context only - moves on comments and labels)
- Body digest:  84ffcf46db00a94f2672eb291e7262863171f59d64cb0926bfad3396619740f4   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1605 of 1605 (cap 16384)

### Body as read
## What is wrong

`tests/test_agent_trial_gate_witness.py::run_case` bounds the WHOLE attempt with `Limits(timeout=15)` (line ~181), and since #407 the scripted actor's socket wait equals it (`sock.settimeout(15)`, line ~146). Under the suite's own parallel load (`make verify`, `-n auto`, ~24 workers; load about 19) a slow attempt can still reach the 15s attempt limit before its later gate calls are recorded.

Observed 2026-10-17 in #432's lock-1 finish gate: `test_actual_gate_history_binds_each_call_to_its_own_snapshot[rerun]` failed with `coverage 'not-observed' != 'complete'`: the second summary run was never witnessed. Re-run alone it passed 3/3 (10-30s each). It's the same family as #412, but not in #412's measured member list.

## Why it's safe to widen

The tests built on `run_case` assert witness history binding (each gate call bound to its own snapshot; stale vs fresh digests), not timing. No timing bound in `run_case` is the property under test.

## Fix

Raise `run_case`'s attempt limit (e.g. `Limits(timeout=60)`) and keep the actor's socket wait equal to it, with the comment updated.

## Acceptance

- [ ] Red: with a gate call delayed past 15s (fake_docker sentinel or a slow-second-call script, as in #407's reproduction), `[rerun]` fails on main with `not-observed` and passes after.
- [ ] #407's slow-second-call `[stale]` reproduction still passes.
- [ ] No other assertion changes. The witness tests pass, and `[stale]` still reads stale.

Found by skillc-worker-A in #432's gate; diagnosed by orchestrator session skillc-400 (which introduced the 15s pairing in #407).

