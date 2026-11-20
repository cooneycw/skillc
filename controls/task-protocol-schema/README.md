# Task-protocol schema controls

`cases.json` holds raw requests and receipts for `skillc/task_protocol_schema.py`,
each with its declared outcome. The expectations were written by hand from the
accepted design (`docs/specs/evaluation-facility/task-protocol-stream.md`,
section 1), not produced by running the parser, so they can disagree with it.

The request cases reach every schema rejection, and they show:

- boundary sizes (exactly 4096 bytes is accepted; 4097 is `oversize`);
- that a payload naming a role, session, attempt, nonce or other identity is
  rejected, never stripped (`identity-field-supplied`);
- that a payload naming a sequence, time or outcome is rejected
  (`controller-field-supplied`);
- that planted `CANARY` text never survives into a rejection.

The receipt cases reach every decision and refuse non-canonical, extended,
unframed or inconsistent receipts.

`tests/test_task_protocol_schema.py` runs them and requires each blind parser to
disagree with them:

- accept-all;
- reject-all;
- accept-any-object;
- identity-stripping;
- controller-field-stripping;
- size-blind;
- last-duplicate-wins;
- a lenient receipt reader.

Deep nesting is tested separately, because whether CPython raises
`RecursionError` at a given depth depends on its version.
