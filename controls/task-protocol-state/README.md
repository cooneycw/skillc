# Task-protocol state machine controls

`cases.json` holds a frozen plan (one offer per principal, a common deadline,
one retired offer id) and 22 hand-written request sequences. Every step carries
its expected decision, rejection reason, violation flag and journal kind,
written from the accepted design (`docs/specs/evaluation-facility/task-protocol-stream.md`,
sections 1 and 4, and decisions 3 and 6), not produced by running the machine.

They cover:

- healthy and alternative interleaved work orders;
- idempotent retries, including a retry whose keys are reordered;
- a distinct second completion, changed content under a used request number,
  and the original retried after such a conflict;
- an ack after completion, a complete before ack, and a duplicate ack before
  completion (retained, not a violation);
- a wrong offer attributed to the sender, a stale offer, and an unknown offer;
- refusals (retained, not terminal, not a failure);
- the deadline boundary at exactly the deadline and one nanosecond after;
- fenced requests and fenced retries;
- malformed payloads and payloads naming an identity or a controller field;
- independence of one principal's state from another's.

`tests/test_task_protocol_state.py` runs them and requires each blind machine to
disagree with them:

- no retry memory;
- a conflict that overwrites the original;
- a strict deadline;
- an ignored fence;
- a wrong offer blamed on the offer's owner;
- no violations ever;
- accept-all.
