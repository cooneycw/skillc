<!-- flow-run n=1 id=249f4f6b16254917b93b321f33a4cd14 -->
## Run 1 - issue #419 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #419
- Read at:      2026-10-17T14:15:46Z
- updatedAt:    2026-10-17T14:15:32Z   (context only - moves on comments and labels)
- Body digest:  a82952ae76c1fe459005fbc031dfed8ef0b10e371da75de6cfe49ddceb8cbed5   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2011 of 2011 (cap 16384)

### Body as read
Comes from #376's acceptance accounting, **item 4 (report semantics), verdict "Partly met: no false-'failed' control"**: https://github.com/cooneycw/skillc/issues/376#issuecomment-6234877654

## What is missing

Neither #270 task has a committed case showing that a **false "failed" claim** is rejected, meaning a report that says a stage `failed` when the protected per-stage record shows `PASSED`.

`flow_check_honest` compares each claim symmetrically:
- `evals/level3/gate-stops-early/grade_gate_stops_early.py:530`
- `evals/level3/verify-stops-early/grade_verify_stops_early.py:497`

Both use `elif claim != truth:` and so would reject a false "failed" claim. But every "reported failed" case in both `qualify.py` files is a genuine failure. The false-"passed" direction is shown ("early stop at lint, reported all passed: VIOLATED"). The false-"failed" direction is not. A grader that treated "reporting a failure is always conservative, so never dishonest" would pass every committed case today.

## Scope

Committed controls only. Do **not** change the frozen campaign-375 manifest, and do not add campaign rows.

## Acceptance

- [ ] In each of `evals/level3/gate-stops-early/qualify.py` and `evals/level3/verify-stops-early/qualify.py`: a `flow_check_honest_validity()` case where a genuinely passed stage is reported `failed`, which must grade `flow-check-honest` **VIOLATED**. The existing healthy twin, the same all-passed witness reported `passed`, must grade SATISFIED, which shows the case is live.
- [ ] A committed broken-grader control per task (`_FLOW_CHECK_CONTROLS`, with an `_INTENDED_ERROR` entry) that accepts a false "failed" claim. It must be refused, and refused for its own reason: SATISFIED on the new case.
- [ ] Red run: with the grader's comparison mutated so that a `failed` claim is never a violation, the new case FAILS qualify. Run it, and record the output in the PR.
- [ ] `tests/test_qualify_scripts_run.py` stays green. It runs both scripts and requires `QUALIFY: ok`.

