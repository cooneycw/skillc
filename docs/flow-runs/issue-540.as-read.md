<!-- flow-run n=1 id=1abb7c593acf4539810ce1350e69b644 -->
## Run 1 - issue #540 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #540
- Read at:      2026-10-28T11:01:00Z
- updatedAt:    2026-10-24T10:42:37Z   (context only - moves on comments and labels)
- Body digest:  4e454a38fc8236da081e7dff572b1aa6447f0eabc9dd124d1407d7bbf00547db   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1911 of 1911 (cap 16384)

### Body as read
**Severity: LOW.** The container is harmless, but it is residue that leak-check scans would misread.

## Problem
kyle19 still holds `skillc-a-live-conformance-fbba8d601e10`:
- labels `skillc.managed=true` and `skillc.attempt-id=a-live-conformance-fbba8d601e10`;
- image `python:3.12-slim`;
- created 2026-10-14 07:08 -04:00, state `created`, never started.

It was re-confirmed present on 2026-10-24. #414's run-scoped cleanup applies only on the evals26 runner under `SKILLC_REAL_DOCKER_RUN_LOCK_HELD`, so nothing reclaims this one.

## Acceptance
- [ ] Identify which code path creates a `live-conformance` container and can abandon it before start.
- [ ] Fix it to remove its own never-started container on every exit path, with a test that fails on the pre-fix code.
- [ ] Then remove the residue container (keep it until the path is found, as evidence).

## Source nits (moved from the Nit Store, #20)
Full text of each source comment, so this issue stands on its own.

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6339769635 (2026-10-22)</summary>

**Nit (found in wave skillc-finish while working #279, 2026-10-22). Severity: low.** kyle19 still has a skillc-managed container, `skillc-a-live-conformance-fbba8d601e10` (labels `skillc.managed=true`, `skillc.attempt-id=a-live-conformance-fbba8d601e10`, image python:3.12-slim). It was created on 2026-10-14 and never started (state=created). Whatever created it left no cleanup. The #414 run-scoped cleanup applies only on the evals26 runner under `SKILLC_REAL_DOCKER_RUN_LOCK_HELD`. Worth finding which path creates a conformance container and can abandon it before start. It's harmless, but it is exactly the residue that leak-check-style scans would misread.

</details>

Filed from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6382622225 at the owner's request (2026-10-24).

<!-- end of body -->
