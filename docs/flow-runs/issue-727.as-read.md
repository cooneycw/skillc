<!-- flow-run n=1 id=3f96b8d8eec0430c9f3c9ef82858e005 -->
## Run 1 - issue #727 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #727
- Read at:      2026-11-15T11:54:05Z
- updatedAt:    2026-11-15T11:53:49Z   (context only - moves on comments and labels)
- Body digest:  4f14b5302abda2ab465409f1ddf1be01afe47fcb73e79df6b0e6d89df93f24a8   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2315 of 2315 (cap 16384)

### Body as read
## What is wrong

The clutter census compares a delivered file's mode against two sources that never agree under a group-writable umask:
- `skillc/clutter_delivery.py:90` takes the expected mode from the git tree: `stat.S_IMODE(int(mode, 8))`, so a regular blob (`100644`) is expected at `0o644`;
- `skillc/clutter_capture.py:164` records the workspace file's *actual* mode, `stat.S_IMODE(mode)`.

Git records only the executable bit. Under umask `0002`, a file the agent wrote and delivered is `0o664` on disk, so it never matches its own delivered blob and is classified as **clutter**.

## Why it matters

- **False `NOT_CLEAN` verdicts.** Any real trial whose agent writes files under a umask other than `022` reports clutter for files it delivered correctly.
- **The local gate cannot pass on a umask-`0002` host.** On this host, `make verify` fails 5 tests on unmodified `origin/main` (`26e686a`), even though Woodpecker CI for that commit is green:
  - `tests/test_clutter_delivery_cache.py::test_delivered_tree_and_cache_controls[delivered]`
  - `tests/test_clutter_delivery_cache.py::test_session_persists_raw_objects_and_recovery_ignores_cached_verdict`
  - `tests/test_clutter_delivery_cache.py::test_semantic_delivered_project_verdict[delivered-tree]`
  - `tests/test_clutter_handoff.py::test_frozen_census_and_final_delivery_handoff[healthy]`
  - `tests/test_clutter_handoff.py::test_frozen_census_and_final_delivery_handoff[pre-stop-survivor]`

  With `umask 022` set, all 56 tests in those two files pass. Environment variables and the global and system git config were ruled out first.

## Fix (a design call for the clutter owner)

Compare the workspace file the way git sees it: same bytes, and the same executable bit (`100755` vs `100644`). Do not require identical permission bits. If stricter mode checking is wanted deliberately, it should be a declared policy and not a side effect of the host umask.

Either way, a test should run the delivered cases under **both** `umask 022` and `umask 002`, so this can't again pass on CI and fail on an operator's host. Show that test failing on the pre-fix code.

Found while running the #719 finish gate (branch `issue-719-skill-usage-records-and-a-hook-that-writes-them-sk`); #719 does not touch the clutter code. Introduced with #674 (`5e28a5e`).


<!-- end of body -->
