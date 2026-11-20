- Add the task-protocol wave lifecycle: inventory, leases and read-only
  endpoint mounts through an additive DockerWave hook, the exclusivity audit,
  client install, bootstrap binding and barrier before the plan freeze, served
  offers, then fence, live census, confirmed stops, receiver drain and seal,
  and a census finalized on the confirmed stops; every failed step is UNKNOWN
  and cleanup always runs (Refs #620, #619).
