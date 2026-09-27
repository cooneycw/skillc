# Flow run record - issue #12

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
below. It is not a description of the shipped system, it is not a second
statement of the issue contract or of a Tier 3 spec, and it does not graduate.

- Issue:             #12
- Base SHA:          ab04c6c536de8c8ce8df2de261f85ebbb8f93d89
- Necessity verdict: Partially addressed
- Approval:          granted
- Approver:          cooneycw (owner), in the /flow:auto session
- Recorded at:       2026-09-27T13:05:48Z

## Section B evidence
Already merged: #89 (6c67dfe) manifest + pilot-report schema; #103 (39d6ae8)
subscription-login ruling; #113/#117 (d8089ae, b9d4b44) single-attempt driver;
#121/#126 (15a7036, ab04c6c) live collection run, both PASS. Related open: #106
(live verification effectively delivered by #11's run), #114 (selection-probe
driver PR, not depended on), #26 (sibling experiment). No duplicate issue.

## Section C - the approved plan
1. `skillc/matched_pilot.py` - new: plan the 6 interleaved trials from the manifest, run each through agent_trial (treatment = cpp-codex, baseline = none), enforce 900s/5400s caps (cut attempts reported not-run), time split from the journal, assemble pilot-report + summary with UNKNOWN for anything unmeasured
2. `skillc/collection_conformance.py` - allow an attempt with no collection (baseline) through the same path
3. `skillc/cli.py` - `skillc pilot-run` subcommand, behind SKILLC_ALLOW_REAL_AGENT=1
4. `tests/test_matched_pilot_run.py` - new: fake-docker end-to-end, red cases (total cap -> not-run reported; omitted attempt refused by ledger_binding; no real agent without the flag; UNKNOWN never fabricated)
5. `evals/matched-pilot/run-manifest.json` - real image digest, observed model/client, retention decision, execution status after the run
6. `evals/matched-pilot/evidence/README.md` - new: leak-checked pilot-report, ledger and results README with an explicit no-broad-claim line
7. `evals/matched-pilot/README.md` - update what is now delivered
8. `README.md` - list the new subcommand (drift check)
9. `CHANGELOG.md` - entry
10. `docs/flow-runs/issue-12.md` - this record

Live run approved: 6 codex attempts, subscription login, $0 metered. Raw
artifacts retained privately outside the repo at
~/.local/share/skillc/pilot-runs/<run-id>/; only leak-checked reports committed.

Scope: ~9 files, ~600-900 lines. Risks: claim accuracy may be only partly
measurable; subscription cost is UNKNOWN in dollars; 3 per arm is noise-level;
live infra failures reported as unavailable/inconclusive, never as skill results.
