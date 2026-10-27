<!-- flow-run n=1 id=d22dbdce1d9e466fa85f04a8d17ce9c7 -->
## Run 1 - issue #585 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #585
- Read at:      2026-10-27T16:23:13Z
- updatedAt:    2026-10-27T16:21:48Z   (context only - moves on comments and labels)
- Body digest:  8a23642c72bc415664b10fb56534e08a93410596ff61b654ca65840d22d92d5e   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2810 of 2810 (cap 16384)

### Body as read
Required blocker discovered while completing #547 in wave `skillc-update`; owner policy puts new required issues ahead of the existing queue.

The normal `make verify` sequence runs tests and then `uv run --no-sync ruff check .` (Makefile:49,108). In the #547 checkout, the first canonical run passed all 7,899 collected test IDs (7,893 passed, six skipped), then reached lint and later failed on an unrelated changelog-format error. After the formatting-only correction, the second canonical run failed six outer tests in `tests/test_profile_flow_auto_87ecb097.py`: the exact pinned fixture now contained extra `.ruff_cache/CACHEDIR.TAG` and versioned cache files. The first run's lint is the suspected producer; establish the exact command/config causally before fixing. Expected nested negative-control failures are separate from these six actual outer failures.

The immutable fixture is `tests/fixtures/profile-cpp-codex-flow-auto-87ecb097`, shipped by PR #582. `check_source()` intentionally requires exact file membership and bytes. Repeated quality verification must not write generated caches into that source snapshot or make the next verification fail.

Acceptance:

- Reproduce the actual cache producer on a disposable copy with a healthy initial membership check, and preserve the real pre-fix failure. Do not weaken the manifest, add ignored-file exceptions to its reader, change frozen vendor bytes/pins, or relabel extra files as valid source.
- Keep Ruff's normal lint coverage while directing generated caches outside immutable fixture trees (or use a justified equivalent). Commit a meaningful bad/good control proving both that generated cache pollution is caught and that the corrected normal lint invocation leaves the fixture unchanged. Exercise the actual command/config, not only a mirrored constant or missing-new-API failure.
- Preserve the two #547 full-run failures and all raw evidence. Any cleanup is limited to the owning session's proven generated cache after it is archived; do not sweep shared/unknown resources.
- Verify repeated relevant checks on the same source and complete the required quality gates without exclusions or hidden retries. Record first-red/final-green and cache/fixture before-after evidence.

#547 product code and review receipt remain frozen. This is a separate required tooling/verification blocker, ahead of #547's next full run and #544's waiting full run. No model/client study, host install, or deployment is required.

Evidence: `/tmp/skillc-update-worker01-547-workflow/canonical-full/` and `canonical-full-rerun/`; first failing changelog repair commit `90d9951941122dec87bd3dd715c7113c4070d486` changes only the release-note placement. The second run's exact outer JUnit population and cache metadata are being preserved before any repair.


<!-- end of body -->
