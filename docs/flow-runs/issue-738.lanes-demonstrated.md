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
