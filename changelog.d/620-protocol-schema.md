- Add the closed task-protocol request and receipt schema: no identity or clock
  field is accepted, invalid bytes are kept only as a reason, length and digest,
  and idempotent retries compare a normalized digest (Refs #620).
