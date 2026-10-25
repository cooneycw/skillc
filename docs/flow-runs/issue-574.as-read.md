<!-- flow-run n=1 id=27d775819fd74b31801515c96b915523 -->
## Run 1 - issue #574 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #574
- Read at:      2026-10-25T11:13:53Z
- updatedAt:    2026-10-25T10:58:32Z   (context only - moves on comments and labels)
- Body digest:  34b6694842f8e6cf4b7a8033367bf51f090fca6d2bc0f1a484e8897bdd3a5205   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2576 of 2576 (cap 16384)

### Body as read
Main push pipeline1111 failed at merged commit357095af692b72565e4273a14d0aab6a3c8fae04 after required PR pipeline1110 passed. Preserve the original run: https://woodpecker.essent-ai.com/repos/20/pipeline/1111/1. Related preparation parents #568 and #569.

The outer suite reported2failed,7212passed,106skipped,3errors in482.89s. This is a current-wave delivery repair, not a new study or a flake exemption.

- `tests/test_coordination_wave.py::test_final_decision_emission_is_outside_completion_boundary` requires the healthy real three-process/capture wave to finish within0.6s before a0.7s final-write sleep. CI observed deadline/incomplete-wave before the intended boundary. Replace the machine-speed assumption with controlled policy time at the exact final-publication boundary, retaining real process/capture execution and a before-boundary late FAIL twin. Label injected-clock evidence as policy-only, never latency.
- `tests/test_change_with_regression_568.py::test_delayed_final_step_cannot_publish_green` timed out at the global120s test allowance before reaching its final-step injection; three consumers of the module qualification fixture errored from the same timeout (`test_fixed_population_discriminates_artifacts`, `test_actual_feature_and_regression_test_reds`, `test_resources_have_real_refusal_and_positive_twins`). Full qualification declares a450s bound and359managed launches. Align the specific full-qualification test allowance with its declared bounded work and cleanup, retaining a finite outer guard and unchanged exact population; avoid repeating full qualification merely to exercise a final-publication boundary when a discriminating narrower fixture suffices. No blanket global timeout increase or weakened qualification contract.

Acceptance:
- Diagnose against actual retained1111 traces; preserve original failures and distinguish them from nested expected negative-control failures.
- Commit known-bad/healthy inputs for each changed load-bearing control. Actual pre-fix failures must be shown; a timeout increase alone is not evidence the intended assertion was reached. Keep task/reference/alternative and all qualification expected populations intact.
- No production coordination/verifier changes unless a real defect is separately demonstrated and the scope is re-reviewed. No baseline exemption, blind retry, skipped control or favorable-result tuning.
- Run focused discriminating checks, normal independent review and complete required verification, then exact-head CI. Parents568/569 remain open; no live study or efficacy claim.


<!-- end of body -->
