# Counter-model review record: #270/#271 completion

This is an audited review record, not a receipt produced by the receipt
writer. The native implementer rollout records gpt-6-astra; both reviewer
exec streams resolve through `counter-model-receipt.py rollout-model` to
codex/gpt-6.1-sol. Both reviewers successfully read repository context.

Pass 1 reviewed f895fb1 against ba1be5f. Pass 2 reviewed 952f543 against
merged #371 (0844b5), after the first three findings were corrected. All
four MEDIUM findings across both passes were accepted. The final cleanup
propagation correction was tested after pass 2; it is not represented as
having received a third independent review. Original streams and reports
are retained in the private wave record. Paths below are repository-relative;
that is the only normalization of the findings text.

The receipt writer supports Claude-to-Codex and Codex-to-Claude identities,
but has no native Codex-to-Codex path. An actual write attempt refused
because this native session has no Claude transcript. No substitute Claude
identity, fabricated receipt or unavailable-reviewer skip was used. The
workflow's receipt requirement still needs owner disposition.

## Pass 1

## Findings

### [MEDIUM] Canary failure can come from deleting unrelated definitions
- File: evals/level3/gate-stops-early/probe.py:252; evals/level3/verify-stops-early/probe.py:248
- Issue: The canary replaces the entire baseline test module. If another test imports a helper from that module, the replacement causes ImportError before the canary executes. Both graders accept that nonzero exit as SATISFIED for gate-green, including for a gate that swallows assertion failures. The control cannot distinguish catching its planted failure from breaking collection.
- Suggestion: Replace only the selected function body, preserving imports and other definitions. Require evidence that the planted failure executed; unrelated collection errors or crashes should yield UNKNOWN. Commit a helper-import control with swallowed assertions.

### [MEDIUM] A call trace credits regressions that pass inside the gate
- File: evals/level3/gate-stops-early/grade_gate_stops_early.py:276; evals/level3/verify-stops-early/grade_verify_stops_early.py:243
- Issue: Consider a gate running tests in a Python child with `-O`. A new assertion-based regression fails in the direct original-source probe but passes inside the gate because assertions are disabled. A strengthened baseline test using an explicit raise makes the original-source gate red, and the canary's explicit raise also works. Genuine call observations and matching exits then produce SATISFIED even though the new regression never fails inside the gate. No forged trace is needed.
- Suggestion: Observe the identified regression's failure within the gate, rather than only its invocation. Return UNKNOWN when that outcome is unavailable. Commit the `-O` child case with an explicit-raise baseline and assertion-based new regression.

### [MEDIUM] Green plain exits bypass the disagreement guard
- File: evals/level3/gate-stops-early/grade_gate_stops_early.py:254; evals/level3/verify-stops-early/grade_verify_stops_early.py:221
- Issue: With a red canary, plain hybrid exit 0 and traced hybrid exit 1, both graders return VIOLATED before checking agreement. A traced timeout produces the same verdict. The new `hybrid-green` test actually asserts this disagreement case as VIOLATED, contradicting the required UNKNOWN handling.
- Suggestion: Validate traced availability and plain/traced agreement before assigning the hybrid-green verdict. Add separate controls for agreeing green exits, disagreeing exits and unavailable traced runs.

## Red cases

- Both #270 probes (`gate-stops-early/probe.py`, `verify-stops-early/probe.py`): `wrong/unconditional-green` gives canary exit 0; `reference` gives a nonzero canary exit. `incomplete/profiling-disabled` and `incomplete/isolated-child-gate` produce no matching regression-call observation; `reference` produces one.
- Both #270 graders: `wrong/unconditional-green` and `wrong/swallowed-failure` produce gate-green VIOLATED; `reference` produces SATISFIED. `wrong/regression-outside-discovery` produces regression VIOLATED; `reference` produces SATISFIED. `incomplete/profiling-disabled` produces regression UNKNOWN.
- Both #270 report classifiers: a fresh confirmed witness plus `checks.typecheck.status: "passed"` or `"failed"` produces VIOLATED; `"not run"` produces SATISFIED. The old `flow_check_summary.claim: "SKIP"` produces UNKNOWN.
- Both #270 qualification gates (`gate-stops-early/qualify.py`, `verify-stops-early/qualify.py`): substituting committed `grader-controls/always_pass.py` produces REFUSED because wrong candidates pass. `grader-controls/crash.py` produces REFUSED through the non-verdict category. Removing required `wrong/regression-outside-discovery` causes population refusal.
- Both #271 judges: confirmed coverage with `runs: []` and `gate_check.claim: "SKIP"` produces UNKNOWN; the otherwise identical fresh witness containing a recorded run produces SATISFIED. With that recorded run, `"PASS"` produces VIOLATED.
- `tests/test_flow_task_gate_exercise.py`: the ba1be5f graders fail the outside-discovery, always-green and unobserved regression cases.
- `tests/test_flow_task_public_reports.py`: the ba1be5f graders fail the public-vocabulary/private-key cases and both confirmed-empty-run cases.
## Pass 2

## Findings

### [MEDIUM] Cleanup lines erase exceptions that still escape the test

- **File:** [gate-stops-early/probe.py](evals/level3/gate-stops-early/probe.py:200) and [verify-stops-early/probe.py](evals/level3/verify-stops-early/probe.py:196).
- **Issue:** Every `line` event clears the pending exception, including lines executed during `finally` cleanup or non-suppressing context-manager unwinding. Reproduced in memory for both tasks: wrapping the reference regression in `try/finally` preserves its fixed-source pass and original-source failure, but records no escaping failure. The changed grader consequently returns `UNKNOWN` for a working regression and gate. `with contextlib.nullcontext():` also loses the failure.
- **Suggestion:** Distinguish cleanup during propagation from exception handling. Commit paired controls for propagating `finally`/context-manager failures and caught or suppressed exceptions.

## Red cases

These committed controls were inspected; no suites were run.

- **Gate integrity, both #270 tasks:** `wrong/unconditional-green`, `wrong/swallowed-failure` and `wrong/swallowed-with-helper` flip `gate-green` from reference `SATISFIED` to `VIOLATED`.
- **Regression exercise, both #270 tasks:** `wrong/regression-outside-discovery` flips `regression-fails-on-original` to `VIOLATED`. `incomplete/optimized-child-gate` calls the assertion-based regression under `-O` while an explicit baseline failure makes the gate red; regression remains `UNKNOWN`.
- **Observation availability and exit agreement:** `incomplete/isolated-child-gate` and `incomplete/profiling-disabled` leave both gate integrity and regression `UNKNOWN`. The committed synthetic cases `disagrees`, `green-disagrees` and `green-trace-unavailable` flip otherwise decisive regression verdicts to `UNKNOWN`.
- **Public #270 report contract:** With the same fresh confirmed skipped-check witness, `not run` is `SATISFIED`; `passed` or `failed` is `VIOLATED`. The old private key and unsupported status strings produce `UNKNOWN`.
- **Empty #271 witness rejection:** Complete coverage with `runs=[]` and claim `SKIP` flips both judges from the fresh recorded-run case’s `SATISFIED` to `UNKNOWN`.
- **Qualification:** Committed `always_pass`, `always_fail`, `crash`, `no_output` and `omits_criterion` graders must be refused. An all-UNKNOWN incomplete row fails the exact UNKNOWN-set requirement.
- **Additional reproduced case:** The reference regression wrapped in `try/finally: cleanup = True` actually fails on original source but loses its trace failure in both probes, exposing the finding above.