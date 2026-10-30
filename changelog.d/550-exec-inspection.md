- **Distinguish unknown attempt state from a confirmed stop** (#550, item 3).
  `exec_in_attempt()` now refuses with `attempt-not-running` only when a
  reachable Docker inspect confirms a stopped or absent container. An
  unreachable inspect returns `launch-failed` with an unknown-state error
  before any exec is attempted, so a daemon rejection cannot count as a
  completed gate run.
