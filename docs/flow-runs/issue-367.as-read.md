<!-- flow-run n=1 id=950eb5d9d04e4b61bc350b1a101a9c94 -->
## Run 1 - issue #367 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #367
- Read at:      2026-10-17T13:11:42Z
- updatedAt:    2026-10-12T19:38:28Z   (context only - moves on comments and labels)
- Body digest:  300d995c77fcf7043da07f2cec79df8b419d36d54be9bcaf3d32f84c66f56910   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2517 of 2517 (cap 16384)

### Body as read
Found while preparing #348 production witness integration, on main `1c9954ad3aacf230596e4bf5cbf21b00ff5cde4d`.

`skillc/decide_reply_channel.py:421` sets `_finalized = True` before waiting for active handlers to drain. If the bounded wait times out, `stop_and_finalize()` raises as intended. However, `log_or_finalize()` at lines 452-454 subsequently sees `_finalized` and returns `_log` without checking whether finalization succeeded. `trusted_log()` uses that result. The returned log can still grow after it was presented as finalized, contrary to the method's documented idempotent snapshot contract.

Confirmed with the actual channel over a local Unix socket, no Docker/model calls or repository edits:

1. Healthy control: handler completes; first finalize returns one entry, repeat returns one entry, and the snapshot remains stable.
2. Known-bad input: handler signals it entered `decide()`, then waits on an event; `handler_drain_timeout=0.05`.
3. First `stop_and_finalize()` raises `RuntimeError` naming the active handler.
4. Before releasing the handler, `log_or_finalize()` nevertheless returns an empty list and `trusted_log().status` is `no-controller-witness`.
5. Release and join the handler. The same `log_or_finalize()` now returns one entry. The supposedly finalized result changed.

Impact: a retry/teardown/read path can convert a failed drain into trusted-looking absence or a partial decision log. An earlier first-call refusal does not protect a later consumer. Existing `test_stop_and_finalize_raises_if_a_handler_outlives_the_drain_timeout` tests only the initial exception, not subsequent reads.

Acceptance:

- Distinguish shutdown attempted from successful log finalization; a drain failure must remain explicit on every evidence-reading API, even if the handler later completes, unless a separately specified recovery contract is deliberately implemented and proven.
- Commit the blocked-handler/retry negative control using synchronization events, plus the healthy stable repeated-read case. Run the regression red on current code.
- Cover `log_or_finalize()` and `trusted_log()` after failed drain, bounded cleanup, and safe repeated successful reads. No partial/growing snapshot may be returned as finalized evidence.

Scope: channel lifecycle repair and its tests. #348 will independently retain its first finalization failure and refuse to retry into trust; its current lane does not modify this channel module. Keep this defect visible rather than burying it in the Nit Store.

