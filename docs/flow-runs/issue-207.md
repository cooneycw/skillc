# Flow run record - issue #207

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=055e5b06922a432d98b8c5159cdaf70f -->
## Run 1

- Run-id:            055e5b06922a432d98b8c5159cdaf70f
- Run-start:         90e59fc512784c2981b45f8e4eb7e38a39480797
- Issue:             #207
- Base SHA:          90e59fc
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          cooneycw (owner, interactive "approved" on the ELI5 gate, plan as written: private evidence, no bundle export)
- Recorded at:       2026-09-30T19:40:00Z

### Section B evidence
Commits since filing on origin/main: none (tip 90e59fc, PR #206, predates filing). Merged PRs 2026-09-30: #206, #205, #201, #200 - none a runner. Open PR #208 records the approval + digest (dependency, not duplicate). Duplicates/superseding: none (#204, #203, #14, #1, #40 considered). Sibling worktree issue-204-record-calibration-approval: 0 unpushed commits.

### Section C - the approved plan
1. `skillc/calibration_run.py` - new runner: require_approved first, plan in arm_order.sequence via trial.plan, one attempt path (cc.run_level1_agent_attempt with task_root; treatment extra_home_files + InstallationReceiptContext, baseline {}), mp.run_schedule caps, ledger reconcile, per-attempt primary_endpoint/readiness_beside/model eligibility report, private outcomes.json
2. `skillc/matched_pilot.py` - extract pin_model_argv from launch_argv; reconcile gains optional schedule= (no behaviour change)
3. `skillc/collection_conformance.py` - add task_surface(fixture_dir): whole fixture minus expected.json; used by calibration only
4. `skillc/cli.py` - calibration-run DECLARATION subcommand with pre-run refusals, private run dir, leak-checked paste-back, exit 1 on ineligible
5. `tests/test_calibration_run.py` - acceptance tests against fake docker + fake client, no live model
6. `AGENTS.md` - layout line for the new module
7. `README.md` - command list entry
8. `evals/calibration-204/README.md` - owed-runner line points at calibration-run
9. `CHANGELOG.md` - entry

Scope: 2 new files, ~7 edited, ~800 lines. Risks: #208 ordering (tests synthesize approval); first non-src fixture delivered to /work; real-image behaviour unproven until the live run.
