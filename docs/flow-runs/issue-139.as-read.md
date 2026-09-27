# Issue #139 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #139
- Read at:      2026-09-27T17:13:19Z
- updatedAt:    2026-09-27T13:53:31Z   (context only - moves on comments and labels)
- Body digest:  b06f49c487ce0e2f9aa5f950cb941d5274e9aa0a749fe55328cb2bdd0922a4ec   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1764 of 1764 (cap 16384)

## Body as read
Found while working #12 (the matched pilot's live run).

## Problem

An attempt run through the agent-trial driver (`skillc/agent_trial.py`, #106) is graded, but no `verified-result` record is stored. `run_one_attempt` calls `verify.grade_files` directly and returns the verdict in memory (`record["graded"]`). The record-writing path, `verify.grade`, is never reached. It needs an installation receipt, and the agent path does not write one.

So every evidence bundle from this path fails `skillc check-records`, once per captured attempt:

```
error attempt-accounting: attempt 'a-...' is captured but has no result; grading is still owed, so it is not accounted for yet
```

That message is accurate about the records and misleading about the run: the grading did happen.

## Where it bites now

- `evals/matched-pilot/evidence/records/` (#12): 6 findings, one per attempt. The pilot's runner tolerates exactly this finding, by rule and text (`matched_pilot.KNOWN_GAP_*`), so that any other finding still refuses publication. The tolerance should be removed once this is fixed.
- #26's selection probe will hit the same gap on the same driver.

## Acceptance

- [ ] A captured, graded agent-trial attempt stores a `verified-result` bound to its artifact manifest and to the grader the ledger pinned. The receipt question is resolved explicitly: either the agent path writes an installation receipt, or the result contract states what stands in for one on this path.
- [ ] Red case: an attempt that was captured but never graded (grading blocked) still reports "grading is still owed".
- [ ] `matched_pilot.KNOWN_GAP_*` and the matching test allowances are removed, and the #12 bundle is regenerated (`skillc pilot-report` from the private run) to check clean.

