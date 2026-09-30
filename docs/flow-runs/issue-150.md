# Flow run record - issue #150

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=57d4b0767ce7481781b462d68b2eb0f0 -->
## Run 1

- Run-id:            57d4b0767ce7481781b462d68b2eb0f0
- Run-start:         6a278ceb8dc3ecf5c54aade7a87664bcf3c9a324
- Issue:             #150
- Base SHA:          6a278ce
- Necessity verdict: Partially addressed
- Approval:          granted (including the live run and a 1200s per-attempt agent cap)
- Approver:          cooneycw (repository owner, in-session)
- Recorded at:       2026-09-29T00:00:00Z

### Section B evidence
Items 1, 2, 4, 5 merged: PRs #153, #155, #157, #160, #162, #172 (owner comment 2026-09-28T19:06Z).
Merged since that comment: 7ea007f..6a278ce (PRs #173, #175-#197); none performs the live run; #195 and #197 touch its path.
Duplicate/superseding issues: none (#139 related, resolved by #172).
Remaining: acceptance item 3, the live discriminating run (docs/runbooks/150-discriminating-run.md).

### Section C - the approved plan
Live run per the runbook: declaration first; positive control; NORMAL then DEGRADED on finish-close-ref with a codex arm; degraded subject built from a scratchpad clone of CPP at 85e9b03; both exports checked with CPP's real check-behavioral-eval.py. No writes to CPP.

1. `evals/discriminating-run/README.md` - declaration, verdict, degraded failure reason
2. `evals/discriminating-run/run-manifest.json` - identities and caps
3. `evals/discriminating-run/normal-evidence` - NORMAL export (leak-checked, check-records clean)
4. `evals/discriminating-run/degraded-evidence` - DEGRADED control export (skillc only)

Scope: ~4 paths plus evidence files. Risks: (a) #195/#197 postdate the runbook, NORMAL could read INCONCLUSIVE; (b) codex OAuth in-container failure surfaces at the positive control; (c) degrade.toml hashes pinned to 85e9b03.
