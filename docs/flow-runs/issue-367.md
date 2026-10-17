# Flow run record - issue #367

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=950eb5d9d04e4b61bc350b1a101a9c94 -->
## Run 1

- Run-id:            950eb5d9d04e4b61bc350b1a101a9c94
- Run-start:         bb247399219ca2bfcc775d6fd8808081c06d734b
- Issue:             #367
- Base SHA:          bb247399219ca2bfcc775d6fd8808081c06d734b
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T13:13:32Z

### Section B evidence
Commits touching skillc/decide_reply_channel.py / tests since filing: d41001c (#397, retain_socket_path, does not touch the _finalized/drain logic), f22d6c8 (#369, predates the issue's main SHA). Merged PRs #359-#409 inspected; only #397 touches the module. Duplicate/superseding issues: none (search "finalize drain channel" -> #367, #20 only).

### Section C - the approved plan
1. `skillc/decide_reply_channel.py` - split shutdown-attempted from finalized-successfully; a failed drain re-raises (as RuntimeError) on every later log_or_finalize()/trusted_log()/stop_and_finalize(), permanently; a successful finalize returns a copy of a frozen snapshot; close() after a failed drain releases the socket without raising.
2. `tests/test_decide_reply_channel.py` - Event-synchronised red regression (failed drain, then reads before and after handler release must raise RuntimeError), healthy stable repeated-read control incl. mutation of a returned list, close() after failed drain, stop_and_finalize after failed drain.
3. `skillc/agent_trial.py` - update the #367 comment at the finish() call site; no behaviour change.

Scope: small, ~40 src lines, ~90 test lines. Risk: DockerBackend.trigger_log() now raises after a failed drain (callers catch RuntimeError/Exception); timing test must use Events to avoid the #410 flake family.
Approval conditions (skillc-400): re-raise stays a RuntimeError with an isinstance assertion; mutation-of-returned-list test; red output of test (a) on main quoted in the PR body with the failing assertion named.
