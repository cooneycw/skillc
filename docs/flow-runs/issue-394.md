# Flow run record - issue #394

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=ca3db0a89f7144488a1f3d32936bceb8 -->
## Run 1

- Run-id:            ca3db0a89f7144488a1f3d32936bceb8
- Run-start:         3c33e8972c98a19d47e4a7698b275aeef53b348f
- Issue:             #394
- Base SHA:          3c33e89
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          the owner (cooneycw), interactive reply "approved" to the ELI5 gate
- Recorded at:       2026-10-15T00:00:00Z

### Section B evidence
Since 2026-10-14T17:06:30Z: c9cce59 (#395, campaign harness) and 3c33e89 (#396, #393 fix) on main; neither changes the trigger-socket lifetime. Merged PRs #395, #396 (and earlier same-day #391, #389, #388, #386, #381). Duplicates/superseding: none (#10 is closed and unrelated). Root cause reproduced on the runner: DecideReplyChannel.stop_and_finalize() unlinks the bind-mounted socket source before export(); docker cp on a stopped container with a missing bind source reports every path missing.

### Section C - the approved plan
1. `skillc/decide_reply_channel.py` - opt-in retain_socket_path; release_socket_path() unlinks only the inode this channel bound; close() releases.
2. `skillc/docker_backend.py` - backend channel retains the socket; destroy() runs docker rm -f before closing/releasing it.
3. `tests/test_decide_reply_channel.py` - retain, release, replaced-inode refusal, default unchanged.
4. `tests/test_docker_backend.py` - socket survives trigger_log(), gone after destroy().
5. `tests/test_decide_reply_channel_live.py` - real_docker production-order regression test with an in-test negative-control leg.
6. `CHANGELOG.md` - entry.
7. `docs/specs/evaluation-facility/decide-reply-channel.md` - socket lifetime equals container lifetime, and why.

Scope: 7 files, ~250 lines. Risks: orphan socket after a controller crash (handled by _clear_stale_path/reap); a Docker release that fixes the daemon behaviour turns the negative-control leg red, deliberately.
