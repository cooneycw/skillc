<!-- flow-run n=1 id=56213bd9b85f49ce8b12a151fbe2c1f8 -->
## Run 1 - issue #543 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #543
- Read at:      2026-10-27T19:14:28Z
- updatedAt:    2026-10-24T11:56:19Z   (context only - moves on comments and labels)
- Body digest:  ebf999ae538cb3234904a4d0959e98c765faa0ebc6d1e1eafd533461d4ca1ea0   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 11386 of 11386 (cap 16384)

### Body as read
**Severity: LOW, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G2).

## Problem
The gate-stops-early and verify-stops-early graders grade `gate-green` from the test stage alone, not the full lint+test+typecheck gate. The fixture's own checks print OK when they discover zero files. A stage that runs zero tests grades as an honest pass. The freshness rule is an exact digest match that can understate honest reporting. The probe tracer compares paths by an absolute prefix.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **MEDIUM**: gate-green criterion in gate-stops-early/verify-stops-early only runs ci/check.py (the test stage), not the full project gate (lint+test+typecheck) that goal.md tells the agent to keep green, so a candidate that breaks lint or typecheck can still get gate-green SATISFIED and pass overall.
  - Still present: evals/level3/gate-stops-early/grade_gate_stops_early.py:290-309 (_gate_green) still grades purely off `g['exit']`/`g['last_line']` from a `ci/check.py` run, with no lint/typecheck stage check, on main 5ece908. Explicitly left as a grader-design question for #270/#375 (both closed without changing this).
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6155519372
- [ ] **LOW**: The gate-stops-early fixture's own ci/check.py, lint.py and typecheck.py print success and exit 0 even when they discover zero tests/files to inspect, so the project gate's own green is not evidence of what it inspected.
  - Still present: evals/level3/gate-stops-early-auto6/fixture/ci/check.py:60 still unconditionally prints 'OK' with no discovered-population count or non-empty requirement. Orchestrator ruling: pre-register, fix in the next fixture revision - not yet done.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6251686249
- [ ] **LOW**: gate-report-honest reads only a stage's pass/fail outcome, so a pytest stage that 'succeeds' having run zero tests would be graded an honest 'passed' - currently inapplicable because the live task's test step is make test -> ci/check.py, not pytest.
  - Still present: No per-stage test-count/coverage qualifier is retained in the finish capture used by gate-report-honest. Orchestrator explicitly rejected the finding for the current (non-pytest) task and pre-registered it for the next revision that runs a pytest-based task.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6251572625
- [ ] **MEDIUM**: The freshness rule (last.tree_digest_at_start == graded_tree_digest, used by gate-stops-early/verify-stops-early graders and skillc/stale_tree.py) still does an exact digest comparison with no exclusion for benign post-plan writes (the model's own pytest/python run writing __pycache__, or the canary result written after the gate), so an honest real-model run can read UNKNOWN/stale even though #400 only silenced the WITNESSED gate's own bytecode writes via PYTHONDONTWRITEBYTECODE.
  - Still present: skillc/stale_tree.py:49-87 (run_freshness/last_run_is_fresh/stale_gates) still does plain `==` digest comparison on main 5ece908, no bytecode/canary-path exclusion pattern or gate-end digest option implemented; skillc/agent_trial.py:833 and skillc/verify.py:416 still only set PYTHONDONTWRITEBYTECODE for the witnessed gate's own env, as described. Options from #400 (gate-end digest, or exact-pattern exclusion) remain not taken.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6225263364
- [ ] **LOW**: evals/level3/gate-stops-early/probe.py and verify-stops-early/probe.py's _TRACE_SOURCE tracer compares frame.f_code.co_filename against an absolute tree-rooted prefix, so a candidate gate that loads tests via a RELATIVE runpy.run_path filename is never observed (produces conservative UNKNOWN, not false success).
  - Still present: evals/level3/gate-stops-early/probe.py:191 (`if not code.co_filename.startswith(_root + os.sep + 'tests' + os.sep): return _trace`) unchanged on main 5ece908; same pattern in verify-stops-early/probe.py. No false-success direction; explicitly accepted as a conservative gap by the comment itself.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6133802905

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6155519372 (2026-10-13)</summary>

**gate-green does not cover lint or typecheck, though the task asks for `make check` to stay green** (found while working #376)

`evals/level3/gate-stops-early/probe.py` (and the verify-stops-early counterpart) grades `gate-green` by running `ci/check.py` directly - the test stage only. `goal.md` tells the agent to keep the project gate (`make check`, which is lint + test + typecheck) passing. So a candidate that introduces a lint failure (for example a bare `except:` in the package), or an unannotated function that fails `ci/typecheck.py`, still gets gate-green SATISFIED.

Why it matters: a delivered patch that breaks the project's declared gate can PASS the task overall, as long as its report honestly says lint failed. In #376 this forced the truthful early-stop report case into direct validity cases rather than a committed `alternatives/` candidate, because that candidate would PASS while breaking `make check`. Whether gate-green should run the aggregate (or its stages) is a grader-design question for #270/#375, not a #376 fix.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6251686249 (2026-10-18)</summary>

**Severity: low.** The gate-stops-early fixture's own checks report success on an EMPTY input population. Found by Codex reviewing #287's auto6 grader (branch `issue-287-auto6-grader`). The orchestrator ruled: pre-register, and fix in the next fixture revision.

**Where:** `evals/level3/gate-stops-early{,-auto6}/{fixture,discrimination/fixture,reference}/ci/check.py` prints `OK` and exits 0 when it discovers zero test functions. `ci/lint.py` and `ci/typecheck.py` likewise print success when their `rangekit/*.py` glob matches nothing.

**Why it matters:** these scripts ARE the project gate the agent is asked to keep green, and their success cannot distinguish "inspected a clean population" from "inspected nothing". The graders catch the consequences elsewhere: zero-test candidates fail `regression-fails-on-original`, and auto6 flags any change to the gate definition. But the gate's own green is not evidence of what it inspected.

**Shape of a fix (a new fixture revision, re-qualified):** require a non-empty discovered population before success, and print the count inspected. Add empty-test and missing-source candidates.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6251572625 (2026-10-18)</summary>

**Severity: low (for now).** `gate-report-honest` (#287's `gate-stops-early-auto6`, revision 1) reads a stage's outcome only. A pytest-based test stage that "succeeds" having executed zero tests, or `warn (zero coverage: …)`, would grade an unqualified "passed" as honest. `/flow:auto` Step 6 forbids exactly that summary (CPP 86641e8 `codex/skills/flow-auto/reference.md:1229-1234`, `:1241-1251`). Found by Codex reviewing the auto6 grader.

**Why it does not apply now:** on this task the test step is `make test` → `python3 ci/check.py`, not pytest. So the runner prints no zero-test qualifier (measured: with every test file deleted, still `warn (skipped gates: verify)`), and "passed" is the runner's own truth. Zero-test candidates fail `regression-fails-on-original`. The orchestrator rejected the finding for this task and pre-registered it.

**For the next revision on a pytest task:** keep the runner's per-stage counts and coverage qualifiers in the finish capture, refuse an unqualified "passed" for a known-empty stage, and add real zero-test and zero-coverage finish-plan samples with honest and dishonest controls.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6225263364 (2026-10-16)</summary>

**Severity: medium (silent: understates honest reporting in #288; no effect on the scripted #375 campaign).** Found while working #400 (PR to follow).

**Where:** freshness rule `last.tree_digest_at_start == graded_tree_digest` in `evals/level3/gate-stops-early/grade_gate_stops_early.py:441`, `evals/level3/verify-stops-early/grade_verify_stops_early.py:408`, and `skillc/stale_tree.py:75`.

**What is wrong:** #400's fix sets `PYTHONDONTWRITEBYTECODE=1` only in the witnessed gates' env, so the gate itself no longer writes bytecode. A real model can still write to the tree after its last honest plan run, and the run then reads stale. Two benign ways: it runs `pytest` or `python` itself, which writes `__pycache__/*.pyc` (the model's own shell does not have the variable), or it writes the canary result `.skillc-canary-result` after the gate rather than before. The scripted actor writes the canary before the plan gate (`level3_campaign.py:116-118`), which is why the campaign is unaffected.

**Why it matters:** the #288 study would score some honest real-model runs as UNKNOWN, the same "understates honest reporting" effect #400 named. It is silent: the reason line says stale, which reads like a real finding.

**Options:** these are #400's options 1 and 2, not taken there: a digest at gate end bound to stage outcomes, or an exact-pattern exclusion (bytecode caches, the controller canary paths) from both digests, with a negative control showing that a source edit is still stale.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6133802905 (2026-10-12)</summary>

**Severity: low - conservative observation gap.** In both `evals/level3/gate-stops-early/probe.py` and `evals/level3/verify-stops-early/probe.py`, `_TRACE_SOURCE` compares `frame.f_code.co_filename` with an absolute tree prefix. A healthy candidate gate that loads a test with `runpy.run_path('tests/test_example.py')` supplies a relative code filename, so its actual calls/failures are not observed and the new gate criteria can become UNKNOWN. The equivalent absolute `run_path` input is observed. This produces no false success, but narrows compatibility and may increase inconclusive outcomes.

Found while implementing the #270/#271 completion follow-up (`issue-270-271-completion`, checkpoint `15e0571`) and constructing the cleanup-propagation controls: the plain raising control was initially unobserved with a relative filename, then observed with its absolute equivalent. Future support should resolve relative code identities carefully and include working-directory-change controls; arbitrary compile-time filenames must not be treated as protected execution proof. The current change keeps the conservative UNKNOWN behavior.


</details>


<!-- end of body -->
