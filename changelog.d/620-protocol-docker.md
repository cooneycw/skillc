- Add Docker placement for the task-protocol stream: a read-only per-lease
  endpoint directory mount at a fixed target (argv unchanged when unused), an
  exclusivity audit over the daemon's own inspect records, a peer verifier on
  the PID-namespace and cgroup v2 bases that never identifies on uid alone, and
  a verified root-owned install of the standalone client (Refs #620).
