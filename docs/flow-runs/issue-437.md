# Flow run record - issue #437

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=bb359f87b87c4093b5d73bdea4d67feb -->
## Run 1

- Run-id:            bb359f87b87c4093b5d73bdea4d67feb
- Run-start:         f0d9f4a502723ccce4c7f3a999fa0fe2a3e1bf6e
- Issue:             #437
- Base SHA:          f0d9f4a502723ccce4c7f3a999fa0fe2a3e1bf6e
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated; issue acceptance list is the approved plan)
- Recorded at:       2026-10-17T19:19:40Z

### Section B evidence
Filed 2026-10-17T19:18Z from #432's lock-1 gate red ([rerun] not-observed). run_case still has Limits(timeout=15) and sock.settimeout(15) on main. No superseding issue (#412 family, not in its member list).

### Section C - the approved plan
1. `tests/test_agent_trial_gate_witness.py` - run_case Limits(timeout=15) -> 60; actor sock.settimeout kept equal (one shared constant); comment updated.
2. `CHANGELOG.md` - entry.

Scope: test-only, a few lines. Risk: a genuinely hung attempt now takes up to 60s to fail instead of 15s. Red (not committed): a gate call delayed past 15s makes [rerun] read not-observed on main and pass after; #407's slow-second-call [stale] reproduction still passes; no other assertion changes.
