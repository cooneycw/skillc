# Flow run record - issue #460

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=d0f7717e52fb4e35be75b07d7d66d516 -->
## Run 1

- Run-id:            d0f7717e52fb4e35be75b07d7d66d516
- Run-start:         52976e7574506df87781c63bcb5361e7866aefdb
- Issue:             #460
- Base SHA:          52976e7
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated), "approved #460" with three conditions plus a boundary
- Recorded at:       2026-10-18T06:20:00Z

### Section B evidence
none - skillc/egress.py and tests/test_agent_egress_live.py are byte-identical between 41407f9 (#442) and 52976e7; no later commit adds a readiness wait.

### Conditions (orchestrator)
- EXPECT_TOTAL for the post-merge evals26 campaign is computed from the driver's LIVE value, plus the last skillc/real-docker "N executed", plus 1. The run expects exactly that or stops. Re-pin order is coordinated with worker-B (#281) and worker-C (#456).
- Loopback exemption is exactly 127.0.0.0/8. Red: a non-loopback peer outside the attempt subnet is still logged peer-rejected. The spec states that only processes inside the proxy container can be loopback peers.
- The sleep-before-bind live red runs on kyle19's daemon against BOTH the pre-fix and the fixed code, and both outcomes are cited in the PR.
- Boundary: eg.allowlist_digest() (ALLOWED_HOSTS via allowlist_document), CODEX_SERVER_SIDE_OFF and AGENT_NETWORK_POLICY are unchanged. A test asserts allowlist_digest() == sha256:d03bacbf… at the head.

### Section C - the approved plan
1. `skillc/egress.py` - start line written only after the bind; loopback peers (127.0.0.0/8) closed unlogged; READY_SOURCE plus proxy_ready_argv
2. `skillc/docker_backend.py` - _start_egress polls proxy readiness with a bounded deadline (egress_ready_seconds), BackendUnavailable on expiry; egress_proxy_source seam
3. `tests/fixtures/docker-backend/fake_docker.py` - ready exec supported; .proxy-never-ready sentinel
4. `tests/test_egress.py` - ready-poll, never-ready cleanup, start-after-bind, loopback-unlogged, non-loopback peer-rejected, formatter, and allowlist-digest pin tests
5. `tests/test_agent_egress_live.py` - _observed() diagnostics read before every _require; sleep-before-bind live red
6. `changelog.d/460.md` - one bullet
7. `docs/specs/evaluation-facility/trial-bootstrap.md` - readiness and loopback-exemption paragraph
8. `docs/flow-runs/issue-460.md` - this record

Scope: about 8 files, 1 PR. Risks: the loopback policy change (safe: only in-container processes are loopback peers), about 0.2-1 s more per prepare(), and the live file going from 4 to 5 tests.

<!-- flow-run n=2 id=a6db5a6c9d69429189cbfc0954ff2fa3 -->
## Run 2

- Run-id:            a6db5a6c9d69429189cbfc0954ff2fa3
- Run-start:         bdc94434d1062a438aa31b143d5f06cf3592cdf1
- Issue:             #460 (follow-up; Refs #460 #462)
- Base SHA:          bdc9443
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated), "APPROVED", 2026-10-18
- Recorded at:       2026-10-18T09:10:00Z

### Section B evidence
#434 rev 2's gate, at load ~18: tests/test_egress.py::test_red_case_the_start_line_is_written_only_once_the_proxy_listens raised IndexError (empty log read right after a successful connect); it passed 3 of 3 alone. Nothing on main fixes it.

### Section C - the approved plan
1. `tests/test_egress.py` - event-based `_wait_for_start_line`; the start-line test asserts the real invariant (a start line implies listening); the loopback-probe test waits for the start line before probing; reds (a) delay between bind and write, (b) pre-#460 start-before-bind still fails
2. `docs/flow-runs/issue-460.md` - this run's record

Scope: tests only, about 2 files. Risk: none to product code.
