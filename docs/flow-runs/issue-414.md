# Flow run record - issue #414

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=cced860eb9fd431684169a26315465ec -->
## Run 1

- Run-id:            cced860eb9fd431684169a26315465ec
- Run-start:         c35034e161806bd96cb47be3cae8134102e12264
- Issue:             #414
- Base SHA:          c35034e161806bd96cb47be3cae8134102e12264
- Necessity verdict: Still needed
- Approval:          granted
- Approver:          skillc-400 (orchestrator, owner-delegated)
- Recorded at:       2026-10-17T18:04:23Z

### Section B evidence
Commits touching ci/real-docker, docker/profile-trial, ci/check_real_docker_ran.py, tests/test_profile_closure_preflight_live.py, tests/test_profile_trial_image.py since 2026-10-17T13:40:39Z: none.
Merged PRs since filing: #403, #405, #406, #407, #409, #411, #413, #415, #417, #420, #421, #422, #423, #425, #428, #429, #430 - none touch these. Open PRs: no overlap. Duplicates: none (search "image prune" -> #414 only; #375 is the affected campaign).

### Section C - the approved plan
1. `docker/profile-trial/build.py` - image_tag(receipt) = skillc-profile-runtime:<runtime_id>-<source_commit[:12]>[-<target>]; build_image tags before writing the receipt; failed tag = SupplyError, no receipt.
2. `ci/real-docker/cleanup-lib.sh` - new sourceable snapshot_runner_artifacts / remove_runner_artifacts: removes only dangling images labelled org.skillc.image and stopped containers labelled skillc.managed=true that were not in the pre-run snapshot; never a host-wide prune.
3. `ci/real-docker/run-real-docker` - snapshot before the tests; scoped removal replaces the two prune lines.
4. `tests/test_profile_trial_image.py` - build_image issues the deterministic tag (fake run); failed tag leaves no receipt.
5. `tests/test_real_docker_cleanup.py` - new, fake docker: no host-wide prune; runner-made labelled dangling image removed (control); pre-existing, unlabelled, and pre-existing-container cases not removed.
6. `tests/test_real_docker_cleanup_live.py` - new real_docker: build via build.py, run the cleanup, receipt image_id still resolves (red on main); control: runner-made labelled dangling image removed; removes only the tag it added.
7. `ci/check_real_docker_ran.py` - floor entry for item 6.
8. `tests/test_profile_closure_preflight_live.py` - teardown removes only a tag it added and an image ID that did not exist before the build, never with -f.
9. `ci/real-docker/README.md` - the cleanup contract.
10. `CHANGELOG.md` - Unreleased entry.

Scope: medium (~60 src, ~200 test lines). Risks: the live test adds a build.py build to every timer run; a host relying on the host-wide prune keeps untagged leftovers it did not create (intended); runner population 14 -> 16 tests ("N executed" readers update).
Approver rulings: D1 label AND created during this run (snapshot); D2 tag as written; D3 include the teardown guard; D4 live red on evals26 under run.lock, list dangling images first and stop if anything looks like campaign work, listing in the PR body. Addition: the live test removes only a tag it ADDED (never a pre-existing tag), with a test for that. Post-merge: stop timer, re-pin, re-enable, record on #414; bump /root/campaign-driver count to 16 and note it on #414.
