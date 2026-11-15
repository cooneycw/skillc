# Lanes demonstrated - issue #763

<!-- lanes-demonstrated run=eaea2f51bf7644ebb886bdd084758afc plan=d109b4c4aaf146eebe2aaf18c9ef1c2af2a7073617a6146e55fab1d61e13f297 -->

| Lane | Result | Evidence |
|---|---|---|
| Checkout | passed | `tests/test_install_skill.py::test_install_from_a_linked_worktree_links_the_main_checkout` (linked worktree) and `test_install_links_the_skill_and_a_second_install_changes_nothing` (main checkout) |
| Run placement | not run | host targeted set passed (99 on main 0d97bb8: test_install_skill, test_gauntlet, test_readme_drift); Woodpecker CI on the PR is the full-suite gate, result in the PR |
| Agent client | not run | Claude Code: the real session opened in CPP runs after this PR merges, from the updated main checkout (orchestrator ruling a, mailbox rev 18), and is quoted on the PR and #763; Codex: not tested |
| Static-check target | passed | `tests/test_gauntlet.py::test_the_skill_passes_skillc_check_for_the_claude_code_target` (claude-code, the skill with its scripts/); portable: not tested |
| Subject collection | passed | synthetic `evals/subjects/gauntlet` through the launcher (`test_the_launcher_runs_the_engine_from_an_unrelated_directory`); CPP at its current checkout: with the post-merge session |
| Subject installation | passed | skill surface into a disposable host home: every installer test uses a tmp SKILLC_SKILLS_DIR; the real ~/.claude/skills: once, post-merge (ruling a) |
| skillc distribution | refused as expected | built wheel in a clean venv: `test_install_refuses_outside_a_git_checkout` (scripts/ and .claude/ are not in the wheel); source checkout (`uv sync`, editable): every test |
| Python version | not run | 3.12 locally; CI 3.12 on the PR is the evidence; >=3.11 declared, 3.11 not tested |
| Reader: Claude Code's user-skill loader (through the link) | not run | the post-merge real session |
| Reader: SKILL.md reading the launcher's output | passed | launcher tests (engine lines, and the cannot-find line with no ROUND line); the real session post-merge |
| Reader: the owner reading install-skill / uninstall-skill messages | passed | installer tests assert each message, and the make targets carry its exit (`test_the_make_targets_run_the_installer_and_carry_its_exit`) |
