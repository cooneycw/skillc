# Task-protocol projection controls

These controls cover `skillc/task_protocol_adapter.py` and assembly contract
version 2 in `skillc/live_wave_assembly.py`.

There is no committed `cases.json` here, a deliberate departure from the B6
plan. Every scenario's journal is built by `tests/task_protocol_fixture.py`
through the merged writer, state machine and lease modules (B2, B3, B4), so the
adapter reads exactly what the controller writes. A hand-authored journal would
check the adapter against bytes no controller produces. Journal bytes are
already pinned to an independently generated file by B2's own control
(`controls/task-protocol-custody/healthy.jsonl`).

`tests/test_task_protocol_adapter.py` covers:

- the exact PR-A projection: identity from the plan, and only the first ack
  and first completion;
- retries that never become a second completion;
- sender-attributed violations, kept in the diagnostic only;
- counts of refusals, late requests and offers;
- the integer deadline boundary at -1, 0 and +1 ns;
- a REAL float/integer cutoff flip, asserted inside the test, refused as
  UNKNOWN and never rounded;
- a deadline that does not match the plan;
- unbound and capacity-hit roles, which get no projection;
- unauthenticated ingress, counted against nobody;
- a journal bound to another population, attempt, slot or role order;
- every clock-join mismatch;
- an unverifiable journal;
- an accounting map that covers every journal kind.

Blind variants, each of which must disagree:

- a float-only cutoff;
- an adapter that drops a known kind silently;
- an adapter that ignores coverage.

`tests/test_live_wave_assembly_v2.py` imports only names the parent commit
has, so on the parent it collects and `freeze()` refuses version 2: a real red.
It covers:

- a real journal reaching PASS;
- a B3 violation that keeps the primary verdict (decision 5 and the #626
  ruling);
- unknown coverage, which never reaches PASS;
- a journal outside the wave's capture roots;
- version 2 carrying authored protocol bytes, which is refused;
- the version-1 control, unchanged.
