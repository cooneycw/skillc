<!-- flow-run n=1 id=ff3d58f7e61748219920b24c5f38ac51 -->
## Run 1 - issue #761 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #761
- Read at:      2026-11-15T16:41:41Z
- updatedAt:    2026-11-15T14:19:11Z   (context only - moves on comments and labels)
- Body digest:  e9a998d58fecb3fa75c3b993b82374668cf98d683b0f8cc2a36451980d824983   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3409 of 3409 (cap 16384)

### Body as read
## What is wrong

`skillc/authority_interceptor.py` can report the backend's OWN `observations` write-back as an out-of-scope violation by the subject, whenever a poll lands while that write-back is half-written.

`stop_and_finalize()` drops only the ambiguous transitions whose value equals the SETTLED final value (lines ~453-460). It assumes the write-back appears as one transition into that value. It does not: `DockerBackend.execute()` writes `observations` with `docker cp -` (`skillc/docker_backend.py:2699-2703`). The test fake extracts it with `tarfile.extractall` (`tests/fixtures/docker-backend/fake_docker.py:900-901`), which truncates the existing file and THEN writes. A poll in between sees an intermediate state (an empty file) that equals neither the subject's content nor the settled one, so it is kept as a violation.

## Evidence (deterministic, no load)

I held the fake's write-back window open: truncate, then 0.6 s, then write, behind a temporary flag file, since reverted. With it held open:
- `test_a_clean_run_never_flags_the_backends_own_observations_write` FAILS: `entries == [{'action': 'create', 'path': 'observations', ...}]` on a subject that never touched `observations`. A clean run is flagged.
- `test_a_subject_created_observations_that_differs_from_the_backends_is_still_caught` FAILS with an extra `{'action': 'modify', 'path': 'observations', ...}`. That is exactly the signature of PR #748's pipeline 1469 failure (load1 13.8, psi_io10 21.2), recorded at https://github.com/cooneycw/skillc/issues/20#issuecomment-6894863339.
- With the window closed, both pass (2/2).

So that CI red was not a test flake. It was this race surfacing under load.

## Why it matters

The interceptor is an integrity instrument: its entries are read as evidence that a subject acted outside its allowed scope. Under host load, a clean subject can be recorded as having created or modified an out-of-scope path. That is a false accusation in the evidence, not just a red test.

## Not established

Whether REAL `docker cp` exposes an intermediate state. I have not verified Docker's extraction behaviour. If it removes the existing file before creating it, a poll could see `observations` ABSENT. A delete is an unambiguous transition, so `_poll_once` would record it immediately (issue #186's rule), which is worse. This needs checking against a real daemon on the runner VM.

## Fix direction (not decided)

- Make the write-back atomic from the poller's point of view: write to a temp name and rename into place, in the backend and in the fake.
- Or suppress every transition at `observations` that falls inside the write-back's own time window (the backend knows when it starts and ends `cp`).
- Or treat any intermediate value seen between the subject's exit and the settled value as the backend's.

Each needs a red case: a held-open write-back must not be flagged, and a subject's own different content must still be caught.

## Acceptance

- [ ] Both tests above pass with the write-back window held open (a committed control, not a sleep).
- [ ] A subject that writes its own `observations` is still caught.
- [ ] Real-`docker cp` behaviour is measured on the runner VM, or stated as unmeasured.

Found while investigating #758 item 9 (the load-flake batch under #462), per the orchestrator's condition to stop if the extra `modify` was a real race. Refs #758, #462, #14, #186.


<!-- end of body -->
