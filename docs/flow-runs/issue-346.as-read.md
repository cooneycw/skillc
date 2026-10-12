<!-- flow-run n=1 id=6824eef8bd2748619594fc78918252d9 -->
## Run 1 - issue #346 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #346
- Read at:      2026-10-12T14:14:08Z
- updatedAt:    2026-10-07T03:40:37Z   (context only - moves on comments and labels)
- Body digest:  a9bcbb95d318324805dd7c06b1ddd8f3191fa36015e0a52809a1fb0deb8293fe   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2013 of 2013 (cap 16384)

### Body as read
**Type:** scope:task. Found by counter-model review (codex `gpt-6.1-sol`) on #334's branch.

## Finding

`calibration_run.build_treatment(subject_profile=, root=)` populates `Treatment.verify_home_files`/`preflight_tools`/`gate_entrypoint` from a validated profile's closure (#334), and `agent_trial.run_one_attempt`/`_make_before_execute` consume them correctly when passed directly (proven by `tests/test_agent_trial.py`'s own wiring tests and the real-Docker live test).

But the only PRODUCTION caller that actually drives a calibration attempt from a built `Treatment` - `uptake_study.run_study`'s `run_attempt` closure, at `skillc/uptake_study.py:488` - calls `collection_conformance.run_level1_agent_attempt(...)`, passing only `extra_home_files=treatments[arm].home_files` and `receipt_context=treatments[arm].receipt_context`. `run_level1_agent_attempt` itself has no `verify_home_files`/`preflight_tools`/`gate_entrypoint` parameters at all, and forwards nothing to `agent_trial.run_one_attempt` beyond what it already exposes.

So a real calibration run against a `subject.profile`-opted subject today still never installs, verifies, or witnesses the profile's dependency closure - #334's whole fix is reachable only through its own direct unit/live tests, not through any real study.

## Outcome

Thread the closure fields from `Treatment` through to the real attempt:
- `collection_conformance.run_level1_agent_attempt` gains `verify_home_files`/`preflight_tools`/`gate_entrypoint` parameters, forwarded to `agent_trial.run_one_attempt`.
- `uptake_study.run_study`'s `run_attempt` passes `treatments[arm].verify_home_files`/`.preflight_tools`/`.gate_entrypoint` through.
- A calibration-level test observes these arguments actually reaching `run_one_attempt` for a profile-opted treatment, and that the baseline arm (no profile) passes none of them.

## Constraints

Do not change `skillc/records.py`. If a new field is needed there, stop and ask.

No live model trials are authorized by this issue.
