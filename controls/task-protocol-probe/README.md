# Task-protocol socket probe controls

`cases.json` holds committed readings for `scripts/probe_task_protocol_socket.py`,
each with the outcome its classifier must give. They exist so the no-Docker
`selftest` and `tests/test_probe_task_protocol_socket.py` can show what the
probe CAN say. They are not physical readings: a real run against a daemon
produces its own receipt, and these files neither replace nor predict it.

Every gated fact has all three outcomes here:

- `holds`: the built-in control disagreed as required and the fact is true;
- `fails`: the control disagreed and the fact is false. Examples: a replace
  succeeds under a read-only mount, connect is refused with the mount present, a
  same-uid sibling shares the owned PID namespace, an audited sandbox is
  privileged or carries the Docker socket;
- `not-covered`: the control did not disagree or a reading was unreadable.
  Examples: an absent endpoint that still answers, a writable control that cannot
  be replaced, a host peer that identifies as the sandbox, an audit that accepts
  the deliberate mis-mount, a scan that misses it.

The recreate characterization has `reaches-new`, `dead-end` and `not-covered`
cases. The environment record has `holds` and `not-covered`, because an
unreadable record cannot be a fact failure.

The tests also compile deliberately blind variants and require each one to
disagree with these cases:

- constant classifiers (always `holds`, always `fails`, always `not-covered`);
- an identifier that trusts the uid alone, on either F2 basis (the F2 red case);
- a cgroup basis that trusts any docker scope, ignores the start-time check
  (the PID-reuse race), or accepts a cgroupfs layout;
- an audit that accepts everything (the F3 red case);
- a reader that never sees a replacement (the F1 red case);
- a recreate reader that always reaches the new listener.
