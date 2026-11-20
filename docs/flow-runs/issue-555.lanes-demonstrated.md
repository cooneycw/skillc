<!-- lanes-demonstrated run=69e4fce986894ebb9e8c79d605242211 plan=1f32473b82fe5743d10f1dad83d96b109e66579ec904714cd082f55ce484f0da -->
| Lane | Result | Test or observation |
|---|---|---|
| Run placement | passed | host: ruff, mypy, leak-check, changelog-check, readme-drift, `skillc selftest` 48/48, targeted pytest over 9 files 510 passed; Woodpecker CI is the full-suite gate on PR #793 |
| Execution backend | passed | DockerBackend via the fake docker CLI: `tests/test_uptake_study.py::test_the_arms_differ_only_in_the_install_and_selection_is_counted_and_tested` (unified surface delivered); ManagedBackend not covered (item 9 transferred to #64) |
| Subject collection | passed | synthetic fixtures: `tests/test_degrade.py::test_a_removal_of_a_manifest_listed_file_is_refused_at_degrade_time`, `::test_a_removal_the_manifest_does_not_list_or_the_operator_owns_is_accepted` |
| Python version | passed | 3.12 (host run above); `>=3.11` declared, not covered |
