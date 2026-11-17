# Lanes demonstrated - issue #537

<!-- lanes-demonstrated run=62fe4f68d7ba4097b83d65558c2acb32 plan=892dc1c2c0f10515e756771c437c3b2e5ee4170df16036b9018cc768748ff713 -->

Lanes are from `.claude/lanes.md` as proposed in PR #728 (not yet on main).

| Lane | Result | Evidence |
|---|---|---|
| Run placement | not run - host `make verify` failed on 5 host-only clutter tests that fail identically on clean origin/main (nit store #20 comment 6886612084); Woodpecker CI on the PR is the gate | host: 14617 passed / 5 failed (those 5); selftest, lint, typecheck, negative-control, typecheck-control, leak-check, changelog-check, readme-drift, secret-scan, clean-install passed |
| Agent client | passed - Codex only | `tests/test_flow_auto_necessity_task.py::test_revision_6_reads_every_retained_live_report_as_revision_5_did` ran all 30 retained Codex live reports on the owner's host (not skipped); Claude Code not covered (no retained report) |
| Python version | not run | CI runs 3.12; local venv ran the suite under the project's uv Python |
| Reader: skillc.verify / qualify.py | passed | `qualify.py`: QUALIFY: ok - grader certified on 109 candidates; 5 broken graders refused; 5 blinding controls flipped their reds |
| Reader: fixture_live.require_approved | passed | `tests/test_fixture_live.py::test_the_spent_revision_5_campaign_declaration_is_refused_since_grader_revision_6` and its control `test_the_revision_5_approval_authorizes_its_own_identities` |
| Reader: test_fixture_campaign (freeze.py) | passed | `tests/test_fixture_campaign.py` against the regenerated `evals/level3/campaign-434/manifest.json` |
| Reader: calibration and judge tests (found by the gate, not planned) | passed | `tests/test_calibration_run.py`, `tests/test_calibration_discrimination_run.py`, `tests/test_judge_anthropic.py` (169 passed) |
