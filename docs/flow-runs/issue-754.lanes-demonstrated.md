# Lanes demonstrated - issue #754

<!-- lanes-demonstrated run=b8674953e1664a24833579561107aeb2 plan=907cc5d5bd70dab0a42639aaaf451c624b04867d28ad3ab7dfdafd37a8244f1c -->

| Lane | Result | Evidence |
|---|---|---|
| Checkout | passed | `tests/test_gauntlet.py::test_the_draft_location_is_the_main_checkout_from_a_linked_worktree` (main checkout and linked worktree both resolve the draft and record to the main checkout's .skillc) |
| Run placement | not run | host targeted set passed (181 on main 8e0e02e: test_gauntlet, test_readme_drift, test_charter, test_charter_confirm, test_contracts); Woodpecker CI on the PR is the full-suite gate (owner rule: no local full runs), result in the PR |
| Agent client | passed | Claude Code: real headless session 22cf2a66 ran /skill-gauntlet on CPP .claude/commands/flow/eli5.md and relayed ROUND 0 UNKNOWN, ROUND 1 STOP draft ready, and the single NEXT line verbatim, answering no clause (quoted in the PR); Codex: not tested |
| Static-check target | passed | `tests/test_gauntlet.py::test_the_skill_passes_skillc_check_for_the_claude_code_target` (claude-code); portable: not tested |
| Subject collection | passed | synthetic `evals/subjects/gauntlet` (every test) and CPP at pinned SHA d5ef0a66: `tests/test_gauntlet.py::test_on_cpp_flow_wave_at_d5ef0a66_round_2_surfaces_the_closed_rules_as_d` (host, ran, not skipped); mattpocock-skills: not tested |
| skillc distribution | passed | source checkout (`uv sync`, editable): every test; built wheel in a clean venv: not tested |
| Python version | not run | 3.12 locally; CI 3.12 on the PR is the evidence; >=3.11 declared, 3.11 not tested |
| Reader: usage report text (round 0) | passed | `test_a_charted_skill_runs_rounds_0_to_2_and_stops_at_round_3_not_built` (OBSERVED from the real command) and `test_no_usage_log_reads_unknown_and_the_run_continues` |
| Reader: contracts CONTRACT and finding lines (round 1) | passed | `test_an_unapproved_charter_stops_round_1_and_an_approved_one_passes`, `test_a_bad_contract_fails_round_1_with_exit_1`, `test_an_unapproved_charter_under_a_spaced_directory_still_stops`, `test_a_neighbours_broken_contract_makes_round_1_unknown_not_pass` |
| Reader: charter draft / overlap exits (round 1) | passed | charter draft (#755 on main): `test_no_charter_stops_at_round_1_with_a_draft_ready_and_writes_nothing_beside_the_skill`; overlap: not built yet (#726 part B), NOT BUILT path in `test_a_charted_skill_runs_rounds_0_to_2_and_stops_at_round_3_not_built` |
| Reader: inspect --json report (round 2) | passed | fixture runs plus the CPP d5ef0a66 purpose control; errors[] and rule_lines[] both read (`test_an_error_finding_on_the_skill_fails_round_2`, `test_round_2_keeps_the_skills_classified_rule_statements`) |
| Reader: GAUNTLET.json (the engine on resume) | passed | `test_an_unchanged_rerun_runs_nothing_and_leaves_the_record_byte_identical`, `test_a_tampered_input_digest_reruns_that_round`; #736/#737: not tested (not built) |
| Reader: test_readme_drift command set | passed | `tests/test_readme_drift.py` (gauntlet and charter entries) |
