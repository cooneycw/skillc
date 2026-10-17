# Flow run record - issue #317

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=a69e83d53ad742ce8d485ccb8002981b -->
## Run 1

- Run-id:            a69e83d53ad742ce8d485ccb8002981b
- Run-start:         a2eb2c8db28050510688856dbdf328bf8f1ce89a
- Issue:             #317
- Base SHA:          a2eb2c8db28050510688856dbdf328bf8f1ce89a
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T16:36:14Z

### Section B evidence
- commits on skillc/docker_backend.py since filing (2026-10-06): 9c79510, 10ff168, 0518cc0, 76a68a6, f22d6c8, 3c33e89, d41001c, f511779, 8466aa5 - none touches the execute() race; its docstring still reads "KNOWN, DOCUMENTED, NOT CLOSED"
- dup/super: none (searched check-then-act / toctou)

### Section C - the approved plan
1. `skillc/docker_backend.py` - execute() wraps argv in a silent marker prelude ({ echo $$ > MARKER; } 2>/dev/null; exec "$@") with the marker at CONTAINER_HOME/.skillc-exec-pid-<uuid>; after a nonzero exit and before its own kill, reclassify to attempt-not-running only when a fresh inspect confirms not running AND a docker cp of the marker reports it absent; anything else keeps the real result; docstring rewritten
2. `tests/fixtures/docker-backend/fake_docker.py` - .stop-before-exec-NAME and .stop-after-exec-NAME sentinels; exec recognises the prelude so the forwarding wrap keeps working
3. `tests/test_docker_backend.py` - red race case, rejection-wording negative control, unwritable-marker byte-identity control, deleted-marker-while-running control, marker-read-failure control, running controls; mutation-checked
4. `CHANGELOG.md` - entry

Conditions from the approver: prelude stderr ordering fixed and tested (marker unwritable -> subject bytes exact, stays exited); PR states which trees are exported/captured and that the marker is in none; real-daemon proof filed as a follow-up issue linked in the PR, with the #315 timer's none run as the interim happy-path check; RED on main and mutation checks shown in the PR body.
Scope: ~4 files, ~150 lines. Risk: subject-deleted marker plus an EXTERNAL container stop could still read as not-running (documented boundary); sh required in every execute() image.
