# Task-protocol ingress controls

The receiver's controls run over real Unix sockets in
`tests/test_task_protocol_receiver.py`, with a fake peer verifier standing in
for B5b's Docker verifier. The physical peer and mount facts are qualified
separately, by the B0 probe on the runner VM.

What each scenario requires:

- **Healthy path.** Offer, ack and complete for two sandboxes reach the journal
  in order. Retries return the original receipt and are journaled as retries.
  The seal is `CLOSED`.
- **Unauthenticated ingress.** Each of these is journaled as
  `unauthenticated-peer` against NO principal, gets no decision, can make no
  role fail, and leaves the endpoint's coverage `unknown`:
  - a peer in another sandbox (cross-access);
  - a peer probe that fails or answers nothing;
  - a revoked lease;
  - a request before the startup barrier.
- **A lying payload.** A payload naming a role is rejected
  `identity-field-supplied`, and its text reaches neither the reply nor the
  journal.
- **Oversize, late and fenced requests** get those reasons. Lateness is judged
  at the same elapsed reading that is recorded.
- **A full journal** replies `capacity`, records the capacity event and seals
  `UNKNOWN`.
- **No durable record, no receipt.** A failed fsync sends no receipt, the client
  exits 4, and every principal's coverage becomes `unknown`.
- **A silent connection** is dropped, and that endpoint's coverage becomes
  `unknown`.
- **Concurrent requests** from two sandboxes stay contiguous in one journal.

Three blind receivers must each disagree:

- one that skips the peer check;
- one that replies without custody;
- one that blames the endpoint's owner for unauthenticated ingress.

`tests/test_task_protocol_client.py` holds the client's own checks:

- it is standalone (stdlib only, no `skillc` import, no environment reads),
  with the import check's own red cases;
- its vocabulary, encoding and receipt reader agree with
  `task_protocol_schema` on every committed schema case;
- its argv grammar admits no role, endpoint or other field;
- its exit codes are 0 decided, 3 rejected, 4 no valid receipt and 2 usage.

`tests/test_decide_reply_channel.py` gains the carried `set_peer_authorizer`
controls from #626. Those tests must fail on the pre-change main, where the
method does not exist.
