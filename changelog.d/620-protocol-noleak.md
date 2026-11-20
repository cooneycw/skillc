- Add no-leak controls for the task-protocol stream and close three leaks they
  found: a chained inventory refusal that carried a participant-chosen key,
  audit reasons that echoed another container's id, and client usage errors
  that echoed the offending argument (Refs #620).
