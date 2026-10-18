<!-- flow-run n=1 id=a59f084a56ef45eda338a39de9f19185 -->
## Run 1 - issue #462 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #462
- Read at:      2026-10-18T07:31:14Z
- updatedAt:    2026-10-18T07:29:41Z   (context only - moves on comments and labels)
- Body digest:  c148d4de1b2443d5d450d5783a57c46e55bf98324da4cdf02ae2cae631ae6442   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2450 of 2450 (cap 16384)

### Body as read
## Problem

Wall-clock-bounded tests fail the full gate under host or CI load, then pass alone. In the last ~24 h this family has failed at least six lock-1 holds or PR CI runs on unrelated PRs, each costing a 25–40 min serial hold. The individual cases sit in the nit store and keep recurring, so this issue aggregates them into one job.

Known members (nit store #20, each with test id, line and load):
- `tests/test_gate_witness.py::test_exec_in_attempt_never_stops_the_container_on_its_own_timeout` (grace=0.3; PR CI 891, kyleci load 16/8 cores): https://github.com/cooneycw/skillc/issues/20#issuecomment-6244857355
- `tests/test_trial_image_tools_live.py::test_python3_satisfies_the_profiles_version_floor` (`docker run --rm` exit past 30 s at load ~20): https://github.com/cooneycw/skillc/issues/20#issuecomment-6245302927
- `tests/test_lifecycle.py` operator cancellation (0.15 s head start): https://github.com/cooneycw/skillc/issues/20#issuecomment-6245913935
- `tests/test_docker_backend.py::test_prepare_raises_within_the_bound_when_docker_run_stalls`: https://github.com/cooneycw/skillc/issues/20#issuecomment-6246655967
- `tests/test_demo.py` cancellation-seed teardown race: https://github.com/cooneycw/skillc/issues/20#issuecomment-6246912611
- `tests/test_collection_evidence_export.py::test_cli_publishes_a_degraded_arm_export_with_evidence_role_control` (5 s whole-attempt limit under 8 xdist workers; #460 hold 1, 2026-10-18)
- Earlier, fixed one at a time: #410, #412, #437, plus `demo.py:1252-1268` (https://github.com/cooneycw/skillc/issues/20#issuecomment-6235718316).

Contributing cause outside skillc: kyle container test suites run on kyle19 without taking lock 1 (containers have their own /tmp). Raised with the owner; not in skillc's scope.

## Why an issue now

Each red costs a full serial hold, and they train sessions to read red as noise. The nit store is an inbox, and this family now blocks merges repeatedly.

## Acceptance

- [ ] Each member either drops its wall-clock dependence (an event or condition wait instead of a sleep/grace race) or derives its bound from a measured scale, with the reasoning in the test.
- [ ] A load harness (for example, `stress-ng` or N busy workers) reproduces each member's pre-fix red at load ≥ 2× nproc, and the fixed test passes under the same load. Commit the harness invocation as the evidence.
- [ ] No member is fixed by raising a timeout without that measurement.

