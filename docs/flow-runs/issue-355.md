# Flow run record - issue #355

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=b03d3898757b43ea9029f3437dc5d60e -->
## Run 1

- Run-id:            b03d3898757b43ea9029f3437dc5d60e
- Run-start:         450445da5eb83719aa68f0f448f29bda56358ec9
- Issue:             #355
- Base SHA:          450445d
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          the session user (cooneycw), replying "approved" to the Step-3 ELI5 report
- Recorded at:       2026-10-12T14:05:00Z

### Section B evidence
none touching tests/ or skillc/docker_backend.py since 2026-10-12T13:53Z; merged PRs: none; open PRs: none;
duplicate/superseding issues: none (#118, #122 closed, unrelated); sibling worktrees: none with unpushed commits on these paths.
Reproduced defects 1-3 on Docker 29.8.2; defect 3 caused by execute()'s one-shot stop; new defect 4: /work root-owned on python:3.12-slim.
Sibling test_gate_witness_live.py fails on the default image for defect 4's cause and passes on skillc-trial:latest.

### Section C - the approved plan
1. `tests/test_gate_overlay_live.py` - root-exec setup (mkdir /home/candidate, chown it and /work to the candidate), everything after prepare() inside try/finally, per-run attempt-id suffix, driver via exec_in_attempt() instead of execute(), docstring corrections
2. `tests/test_gate_witness_live.py` - same root-exec /work setup, post-prepare setup inside try, per-run attempt-id suffixes
3. `tests/test_decide_reply_channel_live.py` - post-prepare asserts inside try, per-run attempt-id suffix

Scope: 3 test files, ~60-90 lines, no production code.
Risks: root setup must stay a pre-install fixture step; exec_in_attempt omits the skillc-wrap prefix (driver plays the agent, not the forwarding claim); leak-on-setup-failure shown by a manual forced failure, not a committed test.
