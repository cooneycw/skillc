# Flow run record - issue #387

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=b8e6365c22a34ed0909f411c194e8f10 -->
## Run 1

- Run-id:            b8e6365c22a34ed0909f411c194e8f10
- Run-start:         d41001ca27b1387f8a96c54019a5410132f2391d
- Issue:             #387
- Base SHA:          d41001ca27b1387f8a96c54019a5410132f2391d
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          cooneycw (owner, in-session "Approved")
- Recorded at:       2026-10-15T00:00:00Z

### Section B evidence
Commits since filing touching the test/backend/fake CLI: d94beb9 (#382), 6844ec5 (#385),
3c33e89 (#393), d41001c (#394) - none changes the fixed 1.5s primary lifetime.
Merged PRs inspected: #381, #386, #388, #389, #391, #395, #396, #397.
Duplicate/superseding issues: none (search "test_gate_witness primary" returns only #387).

### Section C - the approved plan
1. `tests/test_gate_witness.py` - hold the primary on a /work/release file (20s safety deadline, exit 3 on expiry) released via exec_in_attempt after the relint; split the scenario into an observation helper plus a violations checker; parametrize an inter-gate delay (0s, 2s) as the reproduce-first slow-gate case; add a red case that stops the container after lint and asserts the checker reports it.

Scope: 1 file, ~60-90 lines. Risks: release relies on fake_docker's /work/ substring remap (already relied on by /work/fixed); +~2s suite time; a failed release costs a 20s wait before failing.
