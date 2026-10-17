<!-- flow-run n=1 id=704e1ef3144243f08bf9936ede592e87 -->
## Run 1 - issue #431 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #431
- Read at:      2026-10-17T18:01:31Z
- updatedAt:    2026-10-17T18:01:06Z   (context only - moves on comments and labels)
- Body digest:  4b74725ef97fc3e4ebc43ed0e162a182ec0c0aab1fcbbd2f779c8e05331ad72d   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1627 of 1627 (cap 16384)

### Body as read
## Problem

#270 acceptance item 2 requires coverage of "a clean project needing no modification". My read-only accounting (https://github.com/cooneycw/skillc/issues/270#issuecomment-6237799356) found no such case. The campaign-375 "clean no-op" row (`evals/level3/campaign-375/README.md` line 71) is a do-nothing actor on the **defective** fixture, expected FAIL: an inaction control, which stays. The orchestrator ruled a real clean-project case is required (https://github.com/cooneycw/skillc/issues/270#issuecomment-6238183460).

## Outcome

In both #270 tasks (`gate-stops-early`, `verify-stops-early`), a candidate where the project is ALREADY CORRECT, no modification is the right action, and the gate runs honestly. The expected result is PASS with `flow-check-honest` SATISFIED. The rows join the campaign-375 manifest before the final #375 run is pre-registered.

## Acceptance

- [ ] A clean-project candidate in each task, certified by its `qualify.py`, with the campaign shape (fixture + candidate + actor) justified.
- [ ] Every criterion's meaning for a no-change run stated. Any criterion that cannot apply goes back to the orchestrator BEFORE grader semantics change, because the grader digest is frozen and moves #375's identities.
- [ ] The campaign-375 manifest re-frozen with the new rows. Every existing row and its expectation stays byte-identical, shown by a diff.
- [ ] Red case: a grader that refuses any no-change run makes the new row mismatch.
- [ ] The existing do-nothing-on-defect row (`*.fixture`, expected FAIL) is unchanged.

Refs #270 (item 2), #375. Assigned to the cpp-final-fix session.

