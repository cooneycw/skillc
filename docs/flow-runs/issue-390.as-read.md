<!-- flow-run n=1 id=9bb7201954d54453ad855fac322eaa8e -->
## Run 1 - issue #390 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #390
- Read at:      2026-10-14T12:45:04Z
- updatedAt:    2026-10-14T12:44:54Z   (context only - moves on comments and labels)
- Body digest:  825184fb86b00215c611de30136597d865b69ca0c654d75338c8b0a6d60078ba   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 4230 of 4230 (cap 16384)

### Body as read
## Problem

The real-Docker live tests build `DockerBackend(...)` without a `daemon_timeout`, so every daemon call, including **container start** (`docker run -d`), runs on the module default `DAEMON_TIMEOUT = 5.0` (`skillc/docker_backend.py:151`). On #315's dedicated runner, a real container start occasionally stalls for longer than that. The test then fails in **setup**, before reaching the property it exists to check.

This cost #315's step-8 campaign 1 two of its 22 negative controls. In `closure:tampered-closure` and `closure:runtime-cache-permissions`, `tests/test_profile_closure_preflight_live.py::test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner` raised `BackendUnavailable: docker run failed to start a container for 'a-360-generic-…': … timed out after 5.0 seconds` (`skillc/docker_backend.py:990`), during setup of its generic-image container. Both runs read FAILURE instead of the targeted xfail and do not count as proven controls (https://github.com/cooneycw/skillc/issues/315#issuecomment-6167254777). The certifying campaign 2 is blocked on this.

## Measurement (2026-10-14, the dedicated runner, idle, Docker 29.8.2 / overlayfs, 2 vCPU)

27 `docker run -d` starts with the closure live test's exact arguments (`--init --network none --user 10001:10001`, memory/pid/cpu/shm limits, `sleep infinity`):

- **26 took 0.13–0.62 s. One took 7.61 s.** All exited 0.
- The slow start came **immediately after a fresh-tag image build that was itself slow** (2.22 s against the usual ~0.4 s). That is the closure test's pattern: build a new tag, then start a container from it.
- Warm starts with no preceding build: 15/15 between 0.13 and 0.18 s.

So the typical start has about 30x headroom under 5 s. The failure is an occasional multi-second daemon stall around builds, not a generally slow host. With n=27 and one outlier, this shows the stall exists and exceeds 5 s; it does **not** characterise the stall's upper tail.

## Scope

**Production is not affected.** Every CLI path passes its own `daemon_timeout` (`collection-run --timeout` defaults to 30; others to 30 or 120), and `reap`/`demo` defaults are separate call sites. The exposure is the live tests that construct the backend with no value:

- `tests/test_profile_closure_preflight_live.py:437`
- `tests/test_decide_reply_channel_live.py:257`
- `tests/test_gate_witness_live.py:495`
- `tests/test_gate_overlay_live.py:470`
- `tests/test_cwd_confinement_live.py:166`

Three of these then **derive their own waits** from `backend.daemon_timeout` (for example `primary.join(timeout=backend.daemon_timeout + GATE_GRACE)` in `test_gate_witness_live.py:262`). Widening the budget widens those bounds, and each one needs checking for a hang or deadline property that depends on the value being small.

## Outcome

A real container start that stalls for a few seconds does not fail a live test in setup. A start that truly hangs is still refused, at a bounded time, and the live tests still check what they check.

## Acceptance

- [ ] The five live tests run the real backend on an explicit live-test daemon budget (proposed: 30 s, the value #385/#388 gives fake-Docker tests via `conftest.FAKE_DOCKER_DAEMON_TIMEOUT`), not on the 5 s module default. Production's `DAEMON_TIMEOUT` stays unchanged.
- [ ] Each bound a live test derives from `daemon_timeout` is reviewed. Any whose property needs a short value keeps a short, explicit value of its own, with the reason stated.
- [ ] Committed regression control without Docker. A backend on the live-test budget tolerates a deliberately slowed container start of ~6 s (this **fails on today's code** with `BackendUnavailable`), and a start that never returns is still refused at the budget.
- [ ] The real-Docker floor and the runner are unchanged unless this needs them, and the PR says so.
- [ ] Verified on #315's runner: campaign 2 at the post-merge tip, with every break mode's targeted xfail checked from JUnit, not exit code.

## Related

#315 (campaign 1 record; certification is blocked on this), #382/#389 (unit-test wall-clock bounds, done), #385/#388 (fake-Docker setup budget, open; it may own `conftest.py`), #376 (repin; campaign 2 certifies its image).

