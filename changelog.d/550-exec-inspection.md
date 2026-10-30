- **Distinguish unknown attempt state from a confirmed stop** (#550, item 3).
  `exec_in_attempt()` now refuses with `attempt-not-running` only when a
  reachable Docker inspect confirms a stopped or absent container. An
  unreachable inspect falls through to the exec's own outcome, including
  `launch-failed` when the Docker executable is missing.
