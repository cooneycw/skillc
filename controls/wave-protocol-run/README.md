# Task-protocol lifecycle controls (#620 PR-B, B8b)

`tests/test_wave_protocol_run.py` drives `skillc/wave_protocol_run.py` without
Docker. It uses the lifecycle model from `tests/test_docker_wave.py`, and its
resume turns call the REAL client against the REAL receiver over Unix sockets.

## Required order

The healthy run must produce exactly this event order:

1. leased
2. prepared
3. census-setup
4. audited
5. bootstrapped
6. barrier
7. frozen
8. serving
9. turns-done
10. fenced
11. census-after
12. closed
13. sealed
14. census-final

Its journal must also project an ack and a completion for every role through
the B6 adapter.

## Failure cases

Each failure leaves its evidence UNKNOWN and never stops cleanup:

- a refused audit offers nothing;
- a missing startup header leaves only that slot unavailable;
- an unconfirmed stop reaches the census as unknown;
- a seal failure leaves no `protocol_v2` binding;
- a failed preparation still closes, seals and finalizes the census as UNKNOWN.

## Blind variants

Each must disagree with the real run:

- freezing the plan before the barrier;
- offering without the audit;
- finalizing the census before the confirmed stop.

## The hook

`tests/test_docker_wave_protocol_hook.py` imports only parent-era names. With
the protocol unused, every backend gets exactly the parent's constructor
keywords (committed goldens). With lease directories set, only role backends
gain the one task-protocol keyword, which fails on the parent.
