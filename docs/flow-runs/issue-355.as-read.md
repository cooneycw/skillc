<!-- flow-run n=1 id=b03d3898757b43ea9029f3437dc5d60e -->
## Run 1 - issue #355 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #355
- Read at:      2026-10-12T13:55:52Z
- updatedAt:    2026-10-12T13:53:25Z   (context only - moves on comments and labels)
- Body digest:  8c0823f942dc53e4306b3694eff826d9549c5f607d31e6ec5ca92e94f0145f2b   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3113 of 3113 (cap 16384)

### Body as read
## Problem

`tests/test_gate_overlay_live.py` (the real-daemon conformance test for #332's flow-check gate-witness shim) cannot pass on a host with a real Docker daemon. CI skips it (no daemon), and PR #342 records that it "has never run against a real daemon". Reproduced on main 450445d: `uv run pytest -rA tests/test_gate_overlay_live.py`.

Until it runs green on a real daemon, #332's forwarding mechanism has no real-daemon evidence.

## Defects

1. **Setup cannot create the candidate home (lines 399-403).** It runs `docker exec -- <container> mkdir -p /home/candidate`. `docker exec` inherits the container's `--user`, which `DockerBackend` always sets to the fixed unprivileged `CANDIDATE_UID:CANDIDATE_GID` (`skillc/docker_backend.py`, `_container_user`). On the default `SKILLC_LIVE_TEST_IMAGE=python:3.12-slim`, `/home` is root-owned, so it fails every time:
   `mkdir: cannot create directory '/home/candidate': Permission denied`.
   Likely fix: mirror production's `write_root_owned_file_in_attempt()` - `exec -u 0 mkdir -p`, then `chown CANDIDATE_UID:CANDIDATE_GID`.

2. **A setup failure leaks the container (lines 390-422).** `backend.prepare("a-go-live-conformance-000000001")` and the asserts after it (391, 392, 403) sit before the `try:` at line 422, so the `finally: backend.destroy(handle)` never runs. The container survives under a fixed name until something else kills it (observed 20s and 139s later), and any rerun in that window fails with `Conflict. The container name "/skillc-a-go-live-conformance-000000001" is already in use`, hiding the real failure. Two concurrent runs on one host collide the same way. Fix: move everything after `prepare()` inside the `try`; consider a per-run suffix on the attempt id.

3. **Undiagnosed: the container stops before the result is read.** With defect 1 side-stepped (`SKILLC_LIVE_TEST_IMAGE=skillc-trial:latest`, which already has `/home/candidate`), the test gets further and fails with `could not read the driver's own result marker: ... container ... is not running` while reading `/work/result-plan.json`. Cause unknown: the test's driver, the keepalive under that image's entrypoint, or the shim itself.

## Acceptance

- The test passes on a real daemon with its default image, and with `skillc-trial:latest`.
- Every `SKILLC_GATE_SHIM_LIVE_BREAK` mode still XFAILs on `_PropertyHeld` (strict) against a real daemon - the break modes are this test's negative controls, and none has ever run live.
- A setup failure destroys its container (show it: force a setup failure, then `docker ps -a --filter name=go-live` is empty).
- Check the sibling real-daemon tests (`tests/*_live.py` with `real_docker`) for the same exec-as-candidate setup and fixed-name/outside-`try` pattern.

## Context

Found while running `make verify` for #354 (unrelated change; identical failure on main). The three findings are also in the nit store: https://github.com/cooneycw/skillc/issues/20#issuecomment-6125677200, https://github.com/cooneycw/skillc/issues/20#issuecomment-6125677517, https://github.com/cooneycw/skillc/issues/20#issuecomment-6125677938

