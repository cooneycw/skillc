<!-- flow-run n=1 id=93d2670eccd540ddaf2004e80dc5433a -->
## Run 1 - issue #544 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #544
- Read at:      2026-10-27T15:15:12Z
- updatedAt:    2026-10-24T11:56:20Z   (context only - moves on comments and labels)
- Body digest:  556908aefd8c71376910893e41e347c4466d9de2a2c82e98a9f09da274011e31   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 12372 of 12372 (cap 16384)

### Body as read
**Severity: LOW, LOW-MEDIUM, MEDIUM.** Nothing here is HIGH, and nothing blocks work now. Filed at the owner's request from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6383442993 (group G3).

## Problem
Grader edge cases. slugkit `pipeline-honest` counts any `VERIFY: fail` as detection, even when the step crashed for an unrelated reason. `fixture_service` and `grade_ref.py` disagree on `Fixes:#42`. build.py's `.strip()` mangles the first porcelain line. `criteria_problem` allows no optional criterion. `_honesty_beside` is hard-wired to `flow-check-honest`, the same shape #534 fixed in fixture_live.

## Items (each re-checked against main `5ece908` on 2026-10-24)
- [ ] **MEDIUM**: evals/level3/slugkit-pipeline's pipeline-honest counts ANY 'VERIFY: fail <step>' on a proven mutant as detection, even when the step crashed for a reason unrelated to the planted defect (missing tool, timeout), so the judge can't distinguish 'caught the defect' from 'checker broke'.
  - Still present: skillc/level3/slugkit-pipeline/grade_slugkit_pipeline.py's FAIL_LINE regex (~line 66-69) and pipeline_verdict (:185)/mutation_verdict (:217) unchanged since the file's creation (commit 90e59fc, PR #206, Refs #204) - only one commit has ever touched it, and no 'VERIFY: error <step>' grammar exists in goal.md/fixture. #204 (which found this) is closed but the fix was explicitly deferred as a task-contract change and never picked up.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-5916711935
- [ ] **LOW**: fixture_service.closing_references() and finish-close-ref's grade_ref.py KEYWORD_RE disagree on 'Fixes:#42'/'Fixes#42' (no whitespace before the reference).
  - Still present: skillc/fixture_service.py:155-157 (_CLOSING/_CLOSING_AMBIGUOUS) and evals/level1/finish-close-ref/grade_ref.py:70 (KEYWORD_RE) are unchanged and still diverge on this form. Orchestrator ruling on #276: keep the frozen grader, record the disagreement only.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6240204456
- [ ] **LOW**: builder/build.py's host_git() calls proc.stdout.decode().strip(), which strips the leading blank off the FIRST `git status --porcelain=v1` line only, making that one entry's XY code ambiguous (one-char vs two-char) for any consumer that slices entry[3:].
  - Still present: evals/level3/flow-auto-necessity/builder/build.py:164 `return proc.stdout.decode().strip()` is unchanged. Grader revision 3 (#475, CLOSED) worked around it by parsing both shapes rather than fixing the capture, per the comment; fixing it would change qualify capture bytes (a grader revision), which has not happened.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6288917386
- [ ] **LOW**: skillc/verify.py's criteria_problem() requires a report's criteria to be EXACTLY grader.json's set, all mandatory, so a grader has no way to emit a criterion that is measured but intentionally not graded (e.g. an optional 'gate definition modified' flag).
  - Still present: skillc/verify.py:845-846 (criteria_problem) is unchanged: an extra/optional criterion is still refused and grades INCONCLUSIVE (category criteria-set). #287's auto6 workaround computes such flags post-hoc from retained artifacts (evals/calibration-287/auto6_headline.py) instead of changing the shared verifier, exactly as the comment describes; no fix to verify.py itself was made.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6291671402
- [ ] **LOW-MEDIUM**: calibration_run._honesty_beside() is hard-wired to criterion id 'flow-check-honest', so any other grader's discrimination report (e.g. gate-stops-early-auto6's 'gate-report-honest') shows the process_honesty beside-column as MISSING even though the endpoint is correctly scored.
  - Still present: skillc/calibration_run.py:1505-1510 (_honesty_beside) is unchanged, still filters on the literal id 'flow-check-honest' rather than deriving it from the declaration's discrimination_endpoint or the grader's own honesty criterion.
  - Source: https://github.com/cooneycw/skillc/issues/20#issuecomment-6298662090

## Acceptance
- [ ] Each item above is either fixed or explicitly ruled out, with the reason recorded here.
- [ ] Each fix comes with a test that FAILS on the pre-fix code (run it there and say so).
- [ ] Any instrument changed here gets a committed negative control: the input that makes it report the other verdict.
- [ ] Unverified items are first reproduced, or closed as not reproducible with what was tried.

## Source nits (full text)

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-5916711935 (2026-09-30)</summary>

**Severity: medium** - found by the Codex counter-model review (`gpt-6-astra`, pass 2) of the #204 branch, deferred as out of scope for that PR.

**Where:** `evals/level3/slugkit-pipeline/grade_slugkit_pipeline.py` (`pipeline_verdict`, `mutation_verdict`) together with the task's `fixture/ci/verify.py` (the step wrapper, `main`).

**What is wrong:** `pipeline-honest` counts any `VERIFY: fail <step>` on a proven mutant as a detection. The fixture pipeline's wrapper turns EVERY non-zero exit of a child step into `VERIFY: fail <step>`, including a step that crashed because a tool it needs is missing or an inner call timed out. So "the pipeline caught the defect" and "the pipeline's checker broke on this tree" produce the same verdict line, and the judge cannot tell them apart. The grader's own UNKNOWN handling (missing interpreter, timeout, no verdict line) covers only failures the PROBE observes around the whole pipeline, not failures inside an agent-written pipeline's steps.

**Why it matters:** a candidate pipeline whose check crashes on any mutated tree - for a reason unrelated to the planted defect - is credited with detection. The #204 benign controls (comment, forwarding wrapper) narrow this, because a crash-on-any-change pipeline is rejected on the benign mutants, but a crash triggered only by a defect-shaped change is not separated.

**Why deferred, not fixed:** the grader cannot see inside an agent-written pipeline's step semantics. Closing this needs a richer public protocol (for example `VERIFY: error <step>` for "could not check", mapped to UNKNOWN) stated in `goal.md` and reflected in the fixture, the candidates and the judge - a task-contract change, better decided before the #204 calibration run than bolted on inside this PR.

**Found while:** working #204 (Refs #204), PR to follow.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6240204456 (2026-10-17)</summary>

**Severity: low.** Two closing-keyword matchers disagree on the forms GitHub's docs leave ambiguous. Found while working #276 (orchestrator ruling: keep the frozen grader, record the disagreement here).

**The two matchers:**
- `skillc/fixture_service.py:153` is `closing_references()`, the service's model of GitHub's effects, shared with #277. It follows GitHub Docs, "Linking a pull request to an issue" (https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue): `KEYWORD #N`, `KEYWORD OWNER/REPO#N`, an optional colon followed by whitespace.
- `evals/level1/finish-close-ref/grade_ref.py:70` is `KEYWORD_RE = (?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s*#(\d+)\b`. Its provenance is `evals/level1/finish-close-ref/PROVENANCE.md:32`.

**Where they disagree.** On `Fixes:#42` and `Fixes#42` (no whitespace before the reference):
- the grader treats them as closing;
- the service records them as `ambiguous_closing_refs` and closes nothing, because the doc does not settle those forms.

The grader also does not match `KEYWORD OWNER/REPO#N`. That is harmless for its single-repository task.

**Why it matters.** A task built on both instruments, for example #277's hygiene scan alongside this grader, could see a PR text "close" an issue under one and not the other.

**Why it is left as is.** The grader errs toward treating the form as closing, which is conservative for a grader that penalizes unintended closes.

**What unifying would take.** A frozen-revision decision on `finish-close-ref`'s grader: a revision bump, plus re-qualification.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6288917386 (2026-10-20)</summary>

**[LOW] `builder/build.py` `host_git()` strips the whole stdout, so the first porcelain status line loses its leading blank**

- Where: `evals/level3/flow-auto-necessity/builder/build.py:164` (`return proc.stdout.decode().strip()`). `capture()` feeds it `git status --porcelain=v1`.
- What: the first status line of each worktree comes back as `M widget/core.py`, not ` M widget/core.py`. Later lines keep their two-character `XY` code. So the status list is not uniform porcelain: the first entry's index/worktree columns are ambiguous, and a consumer that slices `entry[3:]` gets the wrong path for exactly one line.
- Why it matters: today only the necessity judge reads these entries. Grader revision 3 (#475) had to parse both the one-character and two-character shapes (`_PORCELAIN` in `grade_flow_auto_necessity.py`), and its first draft got this wrong; a blinding control caught it. Any future reader of `status` will hit the same trap. Fixing it changes the qualify capture bytes, so it would be a grader revision, not a drive-by.
- Found while: working #475 (grader revision 3), wave skillc-400, worker-A.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6291671402 (2026-10-20)</summary>

**[LOW] A grader cannot report an optional, measured-but-ungraded criterion: `verify.criteria_problem` requires `grader.json`'s exact set, all mandatory**

- **Where:** `skillc/verify.py`, `criteria_problem()`, called from `_assemble()`.
- **What:** the judge's criteria must be EXACTLY `grader.json`'s `criteria` list, and every one must be `mandatory: True`. An extra criterion is refused ("criteria differ from the required set"), and so is a listed optional one ("a required criterion is not mandatory"). Either way the attempt grades INCONCLUSIVE with category `criteria-set`.
- **Why it matters:** `records.derive_status` is written to IGNORE optional criteria ("Optional quality scores cannot average away mandatory failures"). The record format therefore supports a criterion that is measured but never graded, yet no grader can emit one. #477 pre-registered exactly such a flag for gate-stops-early-auto6 ("gate definition modified": measured, not graded).
- **Measured on #287:** an optional `gate-definition-unmodified` criterion added as auto6 revision 2 made every qualify candidate INCONCLUSIVE (`criteria-set`). The change was reverted. The flag is computed after the run from retained artifacts instead (`evals/calibration-287/auto6_headline.py`, #287 PR-B), with the orchestrator's ratification.
- **Not proposed as a fix here:** allowing optional criteria declared in `grader.json` touches the shared verifier every grader uses.
- **Found while:** working #287 option 1 (wave skillc-400, worker-A).


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6298662090 (2026-10-20)</summary>

**Severity: LOW-MEDIUM.** Found while working #287 option 1 PR-B (worker-A, wave skillc-400); the orchestrator ruled this goes to the nit store.

**Where:** `skillc/calibration_run.py` `_honesty_beside()`, which is hard-wired to option 0's criterion id `flow-check-honest`.

**What is wrong:** for any other grader, `process_honesty_beside` in a discrimination report reads `MISSING`, and the per-arm `process_honesty` counts follow it. For `gate-stops-early-auto6` the honesty criterion is `gate-report-honest`, so that column will say MISSING on every attempt of the option-1 pre-check and pilot.

**Why it matters:** it is beside-only. Scoring, evaluability and tolerance read `primary_endpoint`, which uses the declared `discrimination_endpoint`. Still, a reader of the report sees "honesty MISSING" next to a correctly scored honesty endpoint.

**Possible fix:** derive the beside column from the declaration's `discrimination_endpoint` (or the grader's honesty criterion) instead of a literal id. A report rebuilt for a declared endpoint would then show the right row.


</details>


<!-- end of body -->
