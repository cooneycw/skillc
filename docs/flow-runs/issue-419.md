# Flow run record - issue #419

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=249f4f6b16254917b93b321f33a4cd14 -->
## Run 1

- Run-id:            249f4f6b16254917b93b321f33a4cd14
- Run-start:         a2ef507780af36f94afd1fbc9d1b42625732cc7c
- Issue:             #419
- Base SHA:          a2ef507780af36f94afd1fbc9d1b42625732cc7c
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T14:18:03Z

### Section B evidence
Since filing (2026-10-17T14:15Z): commit a2ef507 (#417, unrelated channel fix); merged PRs: #417 only; duplicate/superseding issues: none (#376 item 4 is the source). Both qualify.py files have "reported failed" cases only for genuinely failed stages.

### Section C - the approved plan
1. `evals/level3/gate-stops-early/qualify.py` - add the false-"failed" validity case (all-passed record, typecheck reported failed: VIOLATED) beside its healthy twin; add broken control failed_claim_believed to _FLOW_CHECK_CONTROLS, append the case to the control case list (index 7) and _INTENDED_ERROR["failed_claim_believed"] = (7, "SATISFIED").
2. `evals/level3/verify-stops-early/qualify.py` - identical change.
3. `evals/level3/gate-stops-early/PROVENANCE.md` - control counts and a #419 line.
4. `evals/level3/verify-stops-early/PROVENANCE.md` - same.
5. `CHANGELOG.md` - Unreleased entry.

Scope: small (~30 lines per qualify.py). Risks: appended case could change an existing control's refusal reason (check each prints REFUSED for its own reason); qualify timeout negligible.
Approval condition (skillc-400): before editing, confirm qualify.py / PROVENANCE.md are in no frozen digest; checked statically (task_identity = goal/grader def+probe+inputs+judge/fixture; harness_digest = actor+fake client; row candidate_digest = candidate dirs) and empirically (perturbing all four files: check_frozen [] ; perturbing the judge: grader_digest move reported).
