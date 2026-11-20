- Add task-protocol endpoint leases and the startup barrier: a frozen prelaunch
  inventory with its one clock origin, one fresh lease per planned sandbox,
  bindings to the actual runtime instance and trusted startup session, one
  barrier that resolves every slot (nonstarts kept), one-way revocation by
  close, and digest-only journal records (Refs #620).
