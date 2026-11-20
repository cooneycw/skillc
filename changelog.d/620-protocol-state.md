- Add the task-protocol decision state machine: one declared offer per
  principal, ack before complete, idempotent retries keyed on a normalized
  digest, narrow sender-attributed violations, integer-nanosecond deadlines and
  a two-phase propose/commit that never advances state ahead of the journal
  (Refs #620).
