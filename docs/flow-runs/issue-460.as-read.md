<!-- flow-run n=1 id=d0f7717e52fb4e35be75b07d7d66d516 -->
## Run 1 - issue #460 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #460
- Read at:      2026-10-18T06:02:20Z
- updatedAt:    2026-10-18T06:01:44Z   (context only - moves on comments and labels)
- Body digest:  4ffef08642b0d92461817a40f0599d5b14b59cdde27b1a356bd14330b439864d   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2413 of 2413 (cap 16384)

### Body as read
## Problem

The evals26 certifying run at 52976e7 (runner 52976e7) failed `tests/test_agent_egress_live.py::test_the_proxy_denies_github` with `_DenialFailed: the proxy must refuse github.com and raw.githubusercontent.com with 403`. The same sha passed seven minutes earlier under runner 746dd72. `skillc/egress.py` and the test file are byte-identical between 41407f9 and 52976e7.

Two defects (analysis by skillc-worker-A, read-only at 52976e7):

1. **The proxy has no readiness wait (product defect).** `_start_egress` (`skillc/docker_backend.py:1121`) returns after `docker run -d`, `network connect` and the IP read. Nothing confirms the proxy is listening. `PROXY_SOURCE` writes its "start" log line before `asyncio.start_server` binds, so that line does not prove listening either. With the proxy capped at `--cpus 0.5` on a busy host, an attempt's first CONNECTs can be refused (`Errno 111`) before it listens. In a live calibration attempt, that can turn into an unusable attempt that counts against the declared tolerance (#287: 1 per arm).
2. **The deny/isolation/resolution assertions discard the evidence (instrument defect).** The test reads `egress_log` only after `_require`, and `destroy()` removes the proxy and its log. A deny failure can be any of: a reached origin (the only leak path), a startup race, a client timeout, a closed connection, or a missing proxy env. Today these are indistinguishable after the fact.

## Acceptance

- [ ] `_DenialFailed`, `_IsolationFailed` and `_ResolutionFailed` report, per target, the probe result and the status or error class plus a truncated message, plus the proxy log summary (allowed/denied/peer_rejected/upstream_failed counts, unparsed lines, start line present), with IPv4 redacted per the file's leak-safety rule.
- [ ] `_start_egress` waits for the proxy to accept TCP connections (bounded deadline; `BackendUnavailable` on expiry), or the start line moves after the bind and the backend polls for it.
- [ ] Red: a `PROXY_SOURCE` variant that sleeps before binding makes the pre-fix code fail the provider/deny probe and the fixed code pass.
- [ ] Red: a forced deny failure's message names the observed result (no generic message).
- [ ] The evals26 certifying run is green at the fix's merge, and the 4 break modes still each fail exactly their own property.

Blocks #288 (live calibration reliability) and the #287 P5 containment evidence.

