<!-- flow-run n=1 id=fd571ca0cf9f4980aa6515a51bd4d56b -->
## Run 1 - issue #375 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #375
- Read at:      2026-10-14T15:33:56Z
- updatedAt:    2026-10-13T16:26:11Z   (context only - moves on comments and labels)
- Body digest:  bd7d7edcaf4b5c5eed68538f32b71e344cd7da45e6733190d98d3bf0d1c8f9f2   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2994 of 2994 (cap 16384)

### Body as read
**Parent:** #270 (portion B). **Wave:** #259. **Outcome contract:** #250.

## Outcome

A correct patch receives regression-test credit only when the delivered gate actually exercises the new regression. A gate that reports success without detecting a planted failure must not certify the work.

## Already delivered

PR #373, merged as `1ff273eea6210d3c256114114cad9e4ba9f0dec0`, implemented the core gate-exercise and integrity checks for both `gate-stops-early` and held-out `verify-stops-early`. It includes candidate controls for outside-discovery tests, unconditional green, swallowed failures, valid expanded discovery and unobservable execution. Its qualification checks and pre-fix failures are recorded in [the completion record](https://github.com/cooneycw/skillc/blob/1ff273eea6210d3c256114114cad9e4ba9f0dec0/docs/flow-runs/issue-270-271-completion.md).

This split tracks completion of portion B, not a request to rebuild that implementation. The remaining gap is production-runner certification and any repairs its evidence demonstrates.

## Acceptance

- [x] Deliver the core gate-exercise/integrity implementation and committed healthy, broken and UNKNOWN controls in both task variants (PR #373).
- [ ] Freeze the merged skillc revision, subject/profile and image identities, task/grader/prompt revisions, deterministic subjects, expected per-criterion outcomes and resource caps before running.
- [ ] Through the production install/capture/grade path, demonstrate healthy/reference and valid-alternative behavior, a clean no-op case, and attributable rejection of outside-discovery, unconditional-green and swallowed-failure cases for both variants.
- [ ] Show that a credited regression fails on the original source inside the delivered gate. An unrelated collection error, a disabled assertion or an unobserved failure must not substitute for that evidence.
- [ ] Preserve UNKNOWN for missing or contradictory observations. State that candidate-process tracing does not establish protection against coordinated forgery; do not present it as controller-protected history.
- [ ] Retain the attempt population, frozen artifacts, witness/envelope evidence and exact criterion outcomes, including negative controls. Any repair needs a pre-fix failure and appropriate committed controls.

## Dependencies and boundary

The runner campaign requires #315's isolated environment and the integrated #348/#360 runtime acceptance. Follow the campaign requirements in the linked completion record; a local general-purpose Docker daemon is not a substitute. No paid model trial or study approval is granted by filing this issue.

Portion C (#376) separately owns aggregate-stop reporting and protected per-stage history. #270 retains integrated acceptance and eligibility accounting; #271's reporting-task certification remains separate. Preserve #203 historical results. Closing this child establishes only its bounded certification, not measured model reliability or study eligibility.

