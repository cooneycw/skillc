# Task-protocol journal custody controls

`healthy.jsonl` is a complete sealed journal, and `inputs.json` holds the
context, clock and appends it records. Both were produced by a standalone
generator from the format in `skillc/task_protocol_journal.py`'s docstrings,
WITHOUT running that module. `tests/test_task_protocol_journal.py` requires the
real writer, fed `inputs.json`, to produce exactly these bytes. A drift in
either the format or the writer therefore fails.

`cases.json` names mutations applied to the healthy journal in two classes.

- **The held reference is kept.** The flip-byte, truncate and drop-record
  mutations keep the caller's independently held `Reference`. Its hash alone
  must refuse them.
- **The journal is re-chained.** The `-rehashed` and `-rechained` mutations
  recompute sequence numbers, previous-record hashes and seal totals, and hand
  the verifier a matching new reference. They model an internally
  inconsistent journal that a hash cannot catch. Each must still be refused by
  the structural checks: canonical form, closed fields, fence before seal, no
  decision after the fence, monotonic time, a retry matching its original,
  planned principals only, and a seal outcome consistent with coverage and
  capacity.

One re-chained case, `unknown-coverage-sealed-unknown-rechained`, is a
legitimate journal. Its coverage is honestly `unknown` and its seal says
`UNKNOWN`, so it must verify. It shows that the checks do not refuse everything
that was re-chained.

The test also requires blind verifiers to disagree with these cases:

- always-`CAPTURED`;
- always-`UNKNOWN`;
- a verifier that only compares the held reference hash.

The hash-only verifier accepts every re-chained case, which is why those cases
exist.
