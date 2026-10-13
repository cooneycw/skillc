<!-- flow-run n=1 id=8bc8816671664b75898c8f8f140950af -->
## Run 1 - issue #376 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #376
- Read at:      2026-10-13T20:53:36Z
- updatedAt:    2026-10-13T16:10:17Z   (context only - moves on comments and labels)
- Body digest:  2b75d3e524802a6562a9dfa7fadaa2c6481a573902733534e0190301a11faa80   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3326 of 3326 (cap 16384)

### Body as read
**Parent:** #270 (portion C). **Wave:** #259. **Outcome contract:** #250.

## Outcome

When an aggregate gate stops early, the grader can distinguish checks that passed, failed, were skipped, or never ran, and reconcile the completion report against evidence of that actual execution. A partial run must not become an unsupported all-passed report.

## Current state

PR #373 (`1ff273eea6210d3c256114114cad9e4ba9f0dec0`) already published the report contract and missing launch goals. It did not complete aggregate-stage history. The pinned CPP subject `ea6dbfa` predates the NOT_RUN reporting fix `8e0a34fb`, and the protected witness records whole-gate runs rather than retained per-stage historical outcomes.

The [concrete remaining gap](https://github.com/cooneycw/skillc/issues/270#issuecomment-6134180009) is that both judges assume typecheck is skipped. A fresh whole-gate record with exit 0 still causes a typecheck `passed` claim to be rejected and `not run` to be accepted. Whole-gate success does not establish what that stage did; a candidate may legitimately add and run the previously absent target.

## Acceptance

- [ ] Record and implement a coordinated CPP/profile repin supporting the required stage states; refresh affected closure, prompt/grader and declaration identities. Preserve historical #203 evidence and approvals.
- [ ] Capture and retain controller-protected per-stage outcomes from the actual attempt, bound to its gate run and tree. Replaying a gate later is not evidence of the earlier execution.
- [ ] Cover an aggregate stopping at an early failed prerequisite, later stages never running, a genuinely skipped stage, and a candidate that configures and runs the formerly absent target. Demonstrate genuinely passed and failed stage outcomes too, in both #270 task variants.
- [ ] Accept truthful partial reports and semantically equivalent claims under the public contract; reject false passed/failed claims and required disclosures omitted where protected evidence makes the violation attributable. Distinguish SKIPPED applicability from NOT_RUN after an early stop, even where the public report maps both to `not run`.
- [ ] Missing, stale, malformed or contradictory stage evidence cannot establish a current stage pass. Return UNKNOWN where attribution is unsupported; do not infer non-execution from silence or whole-gate exit alone, and do not invent production exclusivity.
- [ ] Commit healthy, false-claim and unknown controls, prove planted-defect preconditions and grader mutations, and demonstrate the production capture-to-grade path with deterministic subjects on #315's isolated runner.

## Dependencies and boundary

Build on the merged #371/#373 work and #269/#348 witness path. Actual execution depends on #315 and #360 runtime acceptance. The evidence carrier and implementation approach remain design choices to review; this ticket specifies the required evidence, not a mandatory storage design.

Coordinate any #287 declaration/digest refresh and obtain its required approval before a study. No paid model trials are authorized here. Portion B (#375) owns gate-exercise/integrity certification; #270 retains integrated acceptance and eligibility accounting, while #271 remains its own reporting-task contract. A green offline suite alone does not close this ticket.

