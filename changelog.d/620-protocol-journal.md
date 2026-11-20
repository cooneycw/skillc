- Add controller-held task-protocol journal custody: one serialized sequence
  and integer elapsed clock, fsync before any receipt, poisoning on a failed or
  short write, declared capacity with a closure reserve, a sealed read-only
  content-addressed object and a verifier that reports UNKNOWN for anything
  unprovable (Refs #620).
