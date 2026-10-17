<!-- flow-run n=1 id=b2a56d3b6f0040399c6879e47642fdc4 -->
## Run 1 - issue #385 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #385
- Read at:      2026-10-14T10:54:06Z
- updatedAt:    2026-10-14T10:53:42Z   (context only - moves on comments and labels)
- Body digest:  80031aca308039bfe6c053c24340a3572e01210d0a073aad9a23e2b3113960cc   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 5498 of 5498 (cap 16384)

### Body as read
Split out of #382 by owner decision (2026-10-14). #382 fixes three tests whose own assertions were wall-clock bounds. This issue is the remaining, broader exposure, which #382's plan named as out of scope: **every fake-Docker setup call runs on the production default `DAEMON_TIMEOUT` (5.0s)**.

## The failure that prompted it

`tests/test_docker_backend.py::test_remove_file_in_attempt_on_a_path_that_never_existed_is_still_true` failed in a full `make verify` on the #376 branch. It was the only failure (1 failed, 3925 passed, 15 skipped), and the branch has an empty diff against `552eaa6` for `skillc/docker_backend.py`, `tests/test_docker_backend.py` and `tests/fixtures/docker-backend/`. The failure was in **setup**: the fake `docker run -d ... sleep infinity` raised `subprocess.TimeoutExpired ... after 5.0 seconds`, surfacing as `BackendUnavailable: docker run failed to start a container for 'a-rm-0000000000002'`. Another session's full kyle suite was loading the host at the time. It passed 8 of 8 runs in isolation (0.33-0.68s). Details: https://github.com/cooneycw/skillc/issues/382#issuecomment-6166672878

The test asserts nothing about timing. A 5-second budget for a local Python process to start is simply crossable on a contended host. Pipeline 454 hit the same class: one fake `inspect` over 5s quarantined the verifier for 153 tests (Nit 5918905018, contained by #219).

## Reach

- `tests/test_docker_backend.py`: 70 tests construct their backend with `_backend(base, docker_state)`, which passes no `daemon_timeout` and therefore inherits `DAEMON_TIMEOUT` (`skillc/docker_backend.py:830`).
- 18 other test files drive the fake CLI. They include `conftest.py`, `test_agent_trial.py`, `test_calibration_run.py`, `test_collection_conformance.py`, `test_collection_evidence_export.py`, `test_demo.py`, `test_disruption_trigger.py`, `test_docker_conformance.py`, `test_gate_overlay.py`, `test_gate_witness.py`, `test_matched_pilot_run.py`, `test_reap.py` and `test_selection_probe.py` (full list from `grep -rl 'fake_docker\|FAKE_DOCKER\|fixtures/docker-backend' tests/`).
- **The test-only budget already exists.** `tests/conftest.py` defines `FAKE_DOCKER_DAEMON_TIMEOUT = 30.0` (#174), with exactly this rationale: production's 5s bounds a real daemon, while the fake's process-spawn overhead needs a test-only margin. It is used by `test_authority_interceptor.py`, `test_docker_backend.py`, `test_matched_pilot_run.py`, `test_selection_probe.py`, `test_disruption_channel_bypass_red_case.py`, `test_disruption_trigger.py`, `test_degrade_collection_run.py`. `tests/test_calibration_run.py` keeps its own `_FAKE_DAEMON_TIMEOUT = 120.0` (#209). **`tests/test_docker_backend.py`'s `_backend()` does not use it**, and neither do the remaining fake-CLI files that pass no `daemon_timeout`.

## Why this is not a blind constant change

The natural fix is a generous **test-only** budget for fake-Docker backends: the fake is a local Python process, and a larger upper bound never slows a passing test. But some tests need the timeout to **fire**, through the `.hang-`, `.stuck-` and `.inspect-delay-` sentinels, or by asserting `TimeoutExpired`/`BackendUnavailable`. Under a larger default those would wait the full bound, or stop proving what they claim. A keyword scan of `_backend()` users flags 12 candidates to check one by one. Some are refusals rather than timeouts.

`test_prepare_raises_when_daemon_unreachable`, `test_prepare_raises_when_docker_run_itself_fails`, `test_prepare_refuses_a_missing_image_without_attempting_run`, `test_install_raises_when_the_container_is_already_gone`, `test_a_delivered_home_file_is_gone_after_destroy`, `test_read_home_file_fails_on_a_dead_container`, `test_read_home_tree_on_a_dead_container_is_empty_not_an_error`, `test_confirm_absent_is_not_confirmed_when_rm_lies`, `test_prepare_cleans_up_a_container_that_was_created_but_failed_to_start`, `test_execute_stop_escalation_falls_back_to_killing_the_local_client`, `test_home_delivery_creates_parents_as_candidate_before_owned_leaf_copy`, `test_home_delivery_refuses_invalid_path_before_any_mutation`.

## Acceptance

- [ ] **Reproduce first, deterministically.** Make a setup call exceed 5s on demand: #382 adds `_slowed_docker_bin()`, which delays named fake subcommands. Show at least `test_remove_file_in_attempt_on_a_path_that_never_existed_is_still_true` failing in setup on current code. A green run under load is not evidence; #381 and #382 both found load does not reproduce these races.
- [ ] Adopt the **existing** `conftest.FAKE_DOCKER_DAEMON_TIMEOUT` in `test_docker_backend.py`'s `_backend()` and in every other fake-CLI construction that passes no `daemon_timeout`. Do not add a second constant. Reconcile or justify `test_calibration_run.py`'s separate 120s. The production `DAEMON_TIMEOUT` is unchanged.
- [ ] **Audit every test that needs a timeout to fire** (the 12 candidates above, plus any found in the other files). Each keeps an explicit small `daemon_timeout`, so its own claim and runtime are unchanged. List them in the PR with their disposition.
- [ ] **Negative control.** The slowed reproduction passes after the change, and a timeout-firing test given the large budget by mistake is caught. Say how, for example a sentinel test that would then exceed its own expected runtime or assertion.
- [ ] No suite runtime regression beyond noise. State before/after `make test` durations.

Out of scope: the three tests #382 owns, and production timeout values.

