<!-- flow-run n=1 id=51425e41753f40b5acf66b1b877c2dee -->
## Run 1 - issue #382 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #382
- Read at:      2026-10-14T10:19:15Z
- updatedAt:    2026-10-14T10:16:06Z   (context only - moves on comments and labels)
- Body digest:  63452551f87e2993caa9f87eff47b521fcd4680257c04c82440251d154fa82a1   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 5335 of 5335 (cap 16384)

### Body as read
Aggregated from a scan of the Nit Store (#20) on 2026-10-14. Of 160 comments, 32 matched timing keywords. About 14 describe timing-sensitive tests, and most of those are already fixed (table below). **Three are still live.** All are in `tests/test_docker_backend.py`, all failed under CI load after #174 closed, and all share one shape: a deliberately tight bound against the fake docker CLI, where host scheduling can cross the bound on correct code.

A red on correct code teaches people to re-run reds. Two of these three guard capture honesty or signal delivery, which are exactly the messages that must not be re-run past.

## The three live tests

### 1. Drain-never-reaches-EOF absolute wall-clock bound
- **Test:** `tests/test_docker_backend.py::test_execute_reports_stdout_incomplete_when_the_drain_never_reaches_eof`, with `bound = 3.5` at ~line 1196.
- **Seen:** push pipeline 457 (`4a2528e`) failed with "execute() took 3.92s, expected under 3.50s". The same tree was green on PR pipeline 455. It also failed once in a local full `make verify` (Nit 5876447739).
- **Bound:** the 3.5s bound is mutation-tuned between ~2.46s (concurrent joins, fixed) and ~4.45s (sequential joins, regressed). Its margin under the regressed time is real; its margin over the fixed time is about 1s, which host contention can consume.
- **History:** #174 replaced the earlier `sleep 8` and closed on 2026-09-28. This failure is after that fix.
- **Nits:** 5876447739, 5919675154, 5920775840.

### 2. Forwarded-TERM within grace
- **Test:** `tests/test_docker_backend.py::test_execute_forwards_term_through_a_capable_image_and_reports_exited_within_grace` (~line 1473).
- **Seen:** push pipeline 457 failed with "the subject should have received a real, forwarded TERM".
- **Setup:** `Limits(timeout=0.3, grace=2.0)`, `daemon_timeout=1.0`. The subject is `python -c` and installs its SIGTERM handler as its first statement.
- **Hypothesis (unverified):** on a slow runner, Python startup plus handler installation can take longer than the 0.3s timeout. TERM would then arrive before the handler exists, the default action kills the subject, and the sentinel is never written. That is a startup race, not a forwarding defect.
- **Nits:** 5919675154, 5920775840.

### 3. `read_home_tree` shared-deadline bound
- **Test:** `tests/test_docker_backend.py::test_read_home_tree_joins_stdout_and_stderr_against_one_shared_deadline` (~line 870).
- **Seen:** failed once in a full-suite run with `subprocess.TimeoutExpired` on the fake `docker cp`, at `skillc/docker_backend.py:996` at the time. It passed three isolated re-runs (1.3-3.4s).
- **Bound:** `bound = daemon_timeout + 0.8` with `daemon_timeout = 1.0`, mutation-tuned between ~1.3s (shared deadline) and ~2.3s (sequential).
- **Nit:** 5932177923.

## Already resolved (for the record, not in scope)

| Nit | Test / defect | Resolved by |
|---|---|---|
| 5847657845, 5850673964 | `ci/typecheck-control.sh` tar race with the parallel gate | #116 |
| 5869442148, 5869497918 | degraded collection-run disposition; selection-probe quarantine under load | #174 |
| 5918905018 | one verifier quarantine leaking across the whole suite | #219 |
| 6127163852 | reply-channel over-capacity write/close race; timeout accepted as refusal | #369 (`test_capacity_refusal_can_close_before_the_client_sends`, `test_capacity_check_rejects_a_queued_connection`) |
| 6134188584 | shared tracked-snapshot mutation racing parallel readers | #374 |
| 5919675154, 5920775840, 6155962307 | `test_removing_a_container_without_a_preceding_kill_still_reaps_a_live_exec_session`: zombie read as alive | #381 (zombie-aware poll plus a deterministic stopped-parent case) |

**Related, not a flake:** `tests/test_level3_slugkit_pipeline.py::test_qualify_certifies_the_grader_and_every_control_holds` takes ~107s alone (Nit 5920775652). #214 gave it a 600s timeout, which makes it tolerant, not faster. It is a CI-runtime cost to weigh separately, not part of this issue's acceptance.

## Acceptance

- [ ] **Reproduce each of the three deterministically before changing it**, as #381 did by holding the fake `exec` parent with SIGSTOP. Load alone did not reproduce #381's race (20/20 passed under 48 CPU burners on 24 cores), so a load run that stays green is not evidence of a fix. A test that cannot be made to fail on purpose is reported as such, not "fixed".
- [ ] **Remove the timing dependency by construction where possible.** Use explicit synchronisation, or measure the property directly instead of inferring it from elapsed time. For item 2 that means waiting until the subject has installed its handler before the timeout can fire. For items 1 and 3 it means asserting join structure or a shared deadline without an absolute wall-clock ceiling. Widen a **test-only** bound only where that is impossible. Production bounds are unchanged.
- [ ] **Each test keeps its red-case property, re-proved after the change:**
  - item 1: fails with the drain joins reverted to sequential;
  - item 2: fails without a forwarding supervisor (pre-#158 behaviour);
  - item 3: fails with `read_home_tree`'s joins reverted to sequential.
- [ ] State each reproduction, red case and post-fix result in the PR. A green suite alone does not close this.

Found while fixing the #380 post-merge red (push pipeline 759, fixed by #381).

