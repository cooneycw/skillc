# Flow run record - issue #399

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=99f9e5a6e7ea48b889cef4567c63e084 -->
## Run 1

- Run-id:            99f9e5a6e7ea48b889cef4567c63e084
- Run-start:         a100da5cfc77331892c7c6c71e35056c8b08afff
- Issue:             #399
- Base SHA:          a100da5cfc77331892c7c6c71e35056c8b08afff
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          cooneycw (session user, "Approved")
- Recorded at:       2026-10-15T17:05:00Z

### Section B evidence
Commits on origin/main since 2026-10-15T16:13:40Z: none. Merged PRs referencing #399: none.
Duplicate/superseding issues: none (search "test_calibration_run timeout" returns only #399).
Related family, not duplicates: #382, #385, #387. speckit-context: absent.

### Section C - the approved plan
1. `tests/test_calibration_run.py` - the two three-arm tests drop from 3 to 2 attempts per arm via one module constant; every count assertion (len(seen), per-arm opened/observed/named_opened, paste-back k/n, scheduled) derives from it; per-call assertions unchanged. Decision rule: if the slowest run under 8-way parallel load exceeds 60s, drop to 1 attempt per arm.

Scope: 1 file, ~15 lines. Risk: fewer repeats means a defect that only appears on repeat 3 is missed; neither assertion depends on it. Load margin may still be thin; measured, not assumed.
