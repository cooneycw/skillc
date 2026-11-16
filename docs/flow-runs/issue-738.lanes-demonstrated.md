# Lanes demonstrated - issue #738 (the tracked-files checklist item)

<!-- lanes-demonstrated run=e1084a90a414491a9b87060c64e21760 plan=78594c5299be1ff29f98394b2bd2ef367dc7dc10d87bd21b3ba85f60ff150c21 -->

| Lane | Result | Evidence |
|---|---|---|
| Checkout | passed - main checkout | every installer test builds a fresh git checkout; linked worktree: not tested |
| Run placement | passed - host targeted set; Woodpecker CI on the PR is the gate | tests/test_install_skill.py |
| Subject installation | passed - skill surface, disposable host home (tmp HOME and XDG_CACHE_HOME, synthetic checkouts incl. a `git archive` export); profile dependency closure, cold container, cached, uncached dependencies: not tested | the installer and the installed copy's launcher, run as subprocesses |
| skillc distribution | passed - source checkout; the archive-style checkout stands in for Kyle's `git archive` staging | test_an_archive_checkout_is_compared_in_full |
| Python version | passed - 3.12; 3.11 not tested | |
| Reader: Kyle's staging of the copy | not tested | Kyle #2535 reads the installed copy; only its archive shape is simulated here |

## Run 2 - .kyle-exclude on every install (owner ruling 2026-11-16)

<!-- lanes-demonstrated run=ebc2bdc443b34b95a472f2830eb607a4 plan=59146523ecea72e7d661c67c907ba938362e77808adac68634b2c3e97f8b45c3 -->

| Lane | Result | Evidence |
|---|---|---|
| Checkout | passed - main checkout | every installer test builds a fresh git checkout; linked worktree: not tested |
| Run placement | passed - host targeted set; Woodpecker CI on the PR is the gate | tests/test_install_skill.py (98 passed) |
| Subject installation | passed - skill surface, disposable host home (tmp skills dir, HOME and XDG_CACHE_HOME); profile dependency closure, cold container, cached, uncached dependencies: not tested | test_a_fresh_install_writes_an_empty_kyle_exclude, test_a_refresh_keeps_kyle_exclude, test_a_current_marked_copy_is_refreshed_only_when_kyle_exclude_is_not_a_file, test_an_unmarked_copy_with_a_hand_made_kyle_exclude_is_adopted, test_uninstall_removes_kyle_exclude_with_the_copy |
| skillc distribution | passed - source checkout | the installed copy's launcher run as a subprocess (test_the_drift_check_ignores_kyle_exclude_but_not_a_top_level_file) |
| Python version | passed - 3.12; 3.11 not tested | |
| Reader: Kyle's staging of the copy | not tested | Kyle's #2518 `.kyle-exclude` reader is not run here; the file's presence and shape are asserted |
