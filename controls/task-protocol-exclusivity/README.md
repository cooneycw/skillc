# Task-protocol exclusivity audit controls

`cases.json` holds hand-written `docker inspect` records for
`skillc/task_protocol_docker.audit`, each with its expected verdict. They are
shaped like the evaluation daemon's output: Docker with the containerd image
store, so there is no `GraphDriver` block, and the audit reads only `Id`,
`State`, `Mounts` and `HostConfig`. They were written from the accepted design
and B0's F3 rules, not produced by running the audit.

Healthy, and must audit exclusive:

- two sandboxes, each with its own lease directory bound read-only at
  `/run/skillc-task-protocol`;
- the same pair with the #183 trigger socket and a #621 wave volume also
  mounted. Legitimate mounts elsewhere do not disturb the verdict.

Refused, each one:

- the deliberate mis-mount of A's lease directory into B;
- a shared parent of the lease directories;
- the sandbox's own lease aliased elsewhere;
- a read-write endpoint;
- a missing endpoint;
- a second mount under the endpoint, or a mount covering it;
- the trigger socket placed on the endpoint;
- the other sandbox's lease as the endpoint;
- a non-bind endpoint;
- the Docker socket;
- privileged mode;
- `PidMode` host, or `IpcMode` shared with the other sandbox;
- a container id that differs from the bound one;
- missing inspect output, or a missing `HostConfig` field;
- a population mismatch.

`tests/test_task_protocol_docker.py` runs them and requires two blind audits to
disagree with them: one that accepts everything, and one blind to other leases.
It also checks the peer verifier on both bases with a fake `/proc`, its refusals,
and its own blind variants:

- the pid race;
- disagreeing bases;
- cgroupfs, v1 and nested layouts;
- an init outside its own scope;
- uid-only identification;
- no start check;
- any-scope layouts.

The install verification and its blind variant are covered there too.

`tests/test_task_protocol_docker_live.py` meets a real daemon on the real-Docker
lane, as its non-root account. The audit refuses a real mis-mounted sandbox
before any offer, and that sandbox's request reaches A's endpoint and is
unauthenticated.
