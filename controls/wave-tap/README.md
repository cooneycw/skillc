# Controller tap controls

`refusals.json` drives requests through an actual owned socket. Its healthy ack
executes the pinned real mailbox helper. Forged result/event/success fields,
wrong role/attempt/session/revision/nonce, stale turns and arbitrary argv/env
refuse before helper execution. Caller identity comes from the controller's
endpoint and kernel peer gate, not these assertions.

`install.json` checks the Docker adapter's handle, bootstrap, immutable actor
launch, source digest, permission, liveness and deadline prerequisites against a
model. These are adapter wiring tests, not physical container authentication.

Additional consuming tests execute real helper operations and inspect their
effects; success-shaped stdout with no effect remains unavailable. Dropped
connections, receipt nonce/pin mismatch, publication/custody loss, missing
channels and unconfirmed stop cannot complete coverage. Correct protocol plus
correct task evidence passes; wrong delivered output fails independently.

Refusals have separate retained custody. A positive refusal remains FAIL when
other coverage is UNKNOWN or either custody stream is lost, provided the other
authentic witness still retains it. Neither a refused request nor participant
logs become successful receipt/completion observations.

The channel's peer controls use real kernel credentials: a separate trusted
child connects successfully, while its parent forging the child's PID in JSON
is refused before the decision function. False/unknown/unavailable peer probes
drop and count against coverage. These controls establish the Linux socket
boundary, not the remote Docker namespace prerequisite.
