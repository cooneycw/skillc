# Task-protocol no-leak controls

These are design section 6's controls, run by
`tests/test_task_protocol_noleak.py`.

## What gets planted

Each canary is generated at runtime (`CANARY` plus a random hex string), so no
secret-shaped literal is committed and leak-check stays clean. Each one is
asserted to have reached the component's actual input before any output is
called clean.

Participant canaries go into:

- unknown-field values and JSON keys;
- identity-field values;
- bad offer ids;
- free-text reasons;
- oversize bodies;
- non-UTF-8 bodies.

Private sentinels are:

- endpoint ids, runtime instance ids and lease directory paths, the values
  the controller's lease table holds;
- a peer probe that raises an error carrying one of them.

## Surfaces scanned

None of these may contain any canary or sentinel:

- every receipt;
- the sealed journal object;
- the adapter's projections and diagnostic;
- the receiver's coverage map;
- the version-2 assembly report;
- exception text on every refusal path, including `traceback.format_exception`
  output and every `__cause__` and `__context__` link;
- the client's stdout and stderr on every exit path;
- exclusivity-audit reasons.

## Showing the scanner can fail

The scanner has its own red: a known needle in bytes, in text, after a latin-1
round trip, and inside a chained exception, plus a plant check that refuses an
unplanted canary. These deliberately leaking twins must each be caught:

- a receiver that echoes the request;
- an adapter that dumps its lease state;
- a chained refusal (`raise ... from exc`);
- a client using argparse's own echoing error;
- an audit reason that echoes the daemon's value.

## Fixes this slice made

- `task_protocol_adapter.parse_inventory` raised `from exc`, which carried a
  `TypeError` naming the participant's key. It now raises outside the handler,
  so no `__cause__` or `__context__` is attached. `task_protocol_docker.lease_dir`
  gets the same treatment.
- The audit echoed daemon-supplied `PidMode`/`IpcMode` values, which can name
  another container. It now names the field only.
- The client's argparse errors echoed the offending argument. It now prints one
  fixed usage line, and the exit code stays 2.
