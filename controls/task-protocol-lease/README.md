# Task-protocol lease and barrier controls

`cases.json` holds a three-slot prelaunch inventory and 17 hand-written
operation scripts over `skillc/task_protocol_lease.py`. Each operation carries
its expected outcome, written from the accepted design
(`docs/specs/evaluation-facility/task-protocol-stream.md`, section 2 and
decision 4), not produced by running the module.

They cover:

- a healthy barrier with a nonstart;
- a barrier refused while any slot is unresolved;
- a missing startup session;
- a conflicting second binding;
- a runtime instance or session presented by two slots of one attempt, which
  leaves BOTH slots unavailable because nothing shows which binding is wrong;
- a runtime instance held by an earlier attempt, which marks only the newcomer;
- an endpoint id from an earlier attempt;
- the freeze after the barrier;
- one-way revocation;
- no lookups before the barrier;
- lookups that need the observed runtime instance to match;
- a bound slot that can never be unbound;
- unplanned principals.

`tests/test_task_protocol_lease.py` runs them and requires each blind lease
table to disagree with them:

- keeps the first holder of a colliding identity bound;
- rebinds;
- ignores revocation;
- ignores the runtime instance;
- guesses nonstarts;
- forgets earlier attempts;
- never freezes.

It also checks the records against B2's journal field sets. The test compares
against a mirror until `skillc.task_protocol_journal` is on main, and against
the actual sets after that. It never skips.
