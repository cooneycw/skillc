<!-- flow-run n=1 id=9ee7cc9b0f6047d0b9de76b2709d477e -->
## Run 1 - issue #549 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #549
- Read at:      2026-10-27T19:19:21Z
- updatedAt:    2026-10-25T12:36:28Z   (context only - moves on comments and labels)
- Body digest:  80378f439d48216b94b0f4a5e63e7c8f1a829480676b49667edc64cdcc5f469e   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 6849 of 6849 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G8).

## Problem
Docker residue. reap.py never sweeps the per-attempt egress networks #442 creates. Unlocked live tests keep their tagged images, with no sweeper. An interrupted live test leaks its attempt container. Related: #540.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **MEDIUM**: skillc/reap.py sweeps containers by label but never sweeps the per-attempt egress networks #442 creates, so a controller killed mid-attempt leaves orphaned docker networks forever.
  - Still present: skillc/reap.py has no network-handling code at all (grep for 'network' returns nothing); only skillc/docker_backend.py creates/destroys the <container>-egress network on the normal teardown path, with no sweeper for the crash case.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6241342419
- [ ] **MEDIUM**: tests/test_cicd_profile_live.py and tests/test_profile_closure_preflight_live.py keep their tagged docker images on every unlocked run, with no sweeper, causing silent unbounded disk growth on kyle19.
  - Still present: tests/test_cicd_profile_live.py:307-315 `_release_images(..., lock_held: bool, ...)` still returns without removing when lock_held is False; no provenance-scoped sweeper or per-session tag namespace was added.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6244197333
- [ ] **LOW**: An interrupted real-Docker live test (TaskStop/kill mid-run) leaks its attempt container, which keeps running and pins its image until removed by hand.
  - Still present: No dead-pid-labeled reaper or lock-1 sweeper for orphaned skillc-a-* containers was found in skillc/reap.py or ci/; teardown still relies solely on each live test's own `finally` block.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6244197506

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6241342419 (2026-10-17)</summary>

**Severity: MEDIUM** - found while building #442 (provider-only egress), raised by the counter-model review (codex/gpt-6-astra).

`skillc/reap.py` sweeps containers by the `skillc.managed`/`skillc.attempt-id` labels, but not networks. #442 gives every live attempt its own `docker network create --internal` network (`<container>-egress`, carrying the same two labels). `DockerBackend.destroy()` removes it and `confirm_absent()` now refuses to confirm teardown while it remains. But a controller that dies mid-attempt (SIGKILL, host reboot) leaves the network behind, and nothing ever removes it. The proxy container is swept, since it carries the labels.

Why it matters: abandoned networks accumulate on the runner and on any host running live attempts. Docker's default address pools are finite (on the order of 31 /16 bridge pools by default), so enough leftovers eventually make `network create` fail and refuse every later live attempt. Fix shape: have the reaper also list `docker network ls --filter label=skillc.managed=true` and remove networks whose attempt is not live, with a red case of an orphaned labelled network.

</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6244197333 (2026-10-18)</summary>

**Severity: medium (silent, unbounded growth).**

**What:** `tests/test_cicd_profile_live.py` keeps its images on every run that does not hold run-real-docker's run.lock. Since #280 merged (5d0f572), that means every lock-1 `make verify` on kyle19. Each run leaves two tagged images, `skillc-cicd-base:<id>` (the profile-runtime base) and `skillc-cicd-runtime:<id>`, and nothing ever removes them. `tests/test_profile_closure_preflight_live.py` does the same with `skillc-profile-runtime:<runtime>-<sha>` since #414.

**Where:** `tests/test_cicd_profile_live.py` (`_release_images`, `lock_held=False` returns without removing); `docker/profile-trial/build.py` `release_build` gating in the closure test.

**Why it matters:** both are correct by #414's rule (unlocked, "absent from my snapshot" is not "mine"). But kyle19 accumulates a base plus a layer for every gate run of every session, with no owner. On 2026-10-17 I found 20+ such images after one afternoon: mine from #280's runs, and others' tagged with their commit shas. Disk use grows silently until something fails for space. "Nobody reported it" is the expected state for this kind of harm.

**Possible fix (not done):** a provenance-scoped sweeper run under lock 1 between holds. It would remove `skillc-cicd-*` and `skillc-profile-runtime:*-<sha>` images whose sha is no longer any open branch's head and which no container uses. Alternatively, give each run a per-session tag namespace that its owner reclaims.

**Found while:** closing #280 (PR #451), auditing kyle19 images after the merge. I removed only my own 12 images, by tag provenance, and left #439's in-flight two alone.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6244197506 (2026-10-18)</summary>

**Severity: low (resource leak, visible in `docker ps`).**

**What:** an interrupted real-Docker live test leaks its attempt container, which keeps running. On 2026-10-17, `skillc-a-280-cicd-194bc422…` ran for about 4 h after I stopped a lock-1 `make verify` mid-run with TaskStop. The kill reached pytest before `tests/test_cicd_profile_live.py`'s `finally` (`backend.destroy` + `confirm_absent`) could run. The container also pinned its image, so the image could not be removed until the container was.

**Where:** every live test that relies on `finally` for teardown. Containers are named `skillc-a-<attempt>`, and there is no reaper for orphaned attempt containers on kyle19.

**Why it matters:** a killed gate (a stood-down hold, a timeout, a session crash) leaves a running container and a pinned image that nothing reclaims. The next owner's cleanup also cannot remove that image.

**Possible fix (not done):** a lock-1 sweeper that removes `skillc-a-*` containers older than the longest test timeout whose creating pytest pid is gone. Or put a label carrying the pytest pid on every attempt container, and reap by dead-pid label.

**Found while:** closing #280 (PR #451). I removed the leaked container by hand.


</details>


<!-- end of body -->
