<!-- flow-run n=1 id=cb05c75825fe4a8b95c79a3a1d628285 -->
## Run 1 - issue #392 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #392
- Read at:      2026-10-16T21:27:10Z
- updatedAt:    2026-10-14T15:04:38Z   (context only - moves on comments and labels)
- Body digest:  8f7e3a175a6e87e87ab819c58ab863780d94a4247b1747d11bc6f9ac34f78e26   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3004 of 3004 (cap 16384)

### Body as read
## Problem

`ci/real-docker/poll-triggers`, the timer-driven entry point of #315's runner, passes each page of GitHub issue comments to `python3 -c` **as a command-line argument** (`"$ALL_COMMENTS_JSON" "$PAGE_JSON" "$PROCESSED_IDS_JSON"`, around line 76–83). Linux limits a single argv string to 128 KiB (`MAX_ARG_STRLEN` = 131072). In this repository the 100 newest issue comments alone carry **about 162 KB of body text** (measured 2026-10-14), before JSON metadata. So the first page already exceeds the limit, and every tick dies before any trigger decision:

```
/opt/skillc-real-docker-runner/ci/real-docker/poll-triggers: line 83: /usr/bin/python3: Argument list too long
skillc-real-docker.service: Main process exited, code=exited, status=126/n/a
```

This is persistent, not a first-run effect: seeding `processed_comment_ids` does not help, because page 1 is already too large. It was never seen because the timer had never been enabled. #315's two step-8 campaigns ran `run-real-docker` by hand, which does not go through `poll-triggers`.

## Why it matters

README step 9 (`systemctl enable --now skillc-real-docker.timer`) is the step that makes the runner certify each new `main` commit without anyone remembering to. With this defect, an enabled timer fails every 5 minutes and certifies nothing, while "the timer is enabled" reads as coverage. The timer was enabled once after campaign 2 was accepted (installed runner `3f87395`). Its first tick failed as above, and **it has been disabled again** so the host's state says what is true. The failed tick ran no tests, posted no status and left `state.json` unchanged.

## Outcome

`poll-triggers` works on a repository with large comment volume. A tick with nothing to do exits 0 without running anything; a new `main` commit or an owner `/run-real-docker <sha>` comment triggers exactly one run.

## Acceptance

- [ ] Comment pages, the accumulated set and processed ids reach Python through stdin or files, not argv. The same applies to any other argv-carried data in `poll-triggers` and `run-real-docker` whose size depends on GitHub content.
- [ ] Regression control without the network: a fixture page of 100 comments totalling more than 128 KiB **fails on today's script** with the argv error and succeeds after the fix. The existing trigger-selection semantics (owner-only exact command, newest-first pagination, stop at a known id, 20-page cap) still hold under their existing controls.
- [ ] The installed runner is re-pinned to the fixed sha. Seeding `state.json` with the already-certified main sha (as was done for the failed attempt) means the first tick runs nothing. Then: a tick with no trigger exits 0 and posts nothing, a later `main` commit triggers one certifying run, and the timer is enabled (README step 9).

## Related

#315 (runner provisioning; certification accepted, step 9 blocked by this), #390 (live-test budget), campaign 2 record: https://github.com/cooneycw/skillc/issues/315#issuecomment-6171417226

