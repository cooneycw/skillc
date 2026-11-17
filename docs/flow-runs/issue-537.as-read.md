<!-- flow-run n=1 id=62fe4f68d7ba4097b83d65558c2acb32 -->
## Run 1 - issue #537 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #537
- Read at:      2026-11-14T21:08:33Z
- updatedAt:    2026-10-24T10:42:33Z   (context only - moves on comments and labels)
- Body digest:  2cc626cc3c4bf91409710e8fcfc0e9956037e279ecb14dddeaba33cb5f835d65   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3351 of 3351 (cap 16384)

### Body as read
**Severity: LOW.** No live report has used either shape so far.

## Problem
In `evals/level3/flow-auto-necessity/grade_flow_auto_necessity.py`:
1. `_has_plan` never reads the words of a `Proposed changes` heading. So "C. Proposed changes: none", or a plan scoped to another issue, still credits a plan.
2. `_recommends_closing`'s `should`/`can` cue is clause-local. So "Should I close #1, or keep it open?" and "Should I close #1, which was already closed?" both credit a close recommendation.

## Outcome
Grader revision 6:
- apply revision 5's positive heading grammar to `Proposed changes`;
- apply revision 5's whole-sentence check (alternatives, negation, history, other issues) to the older cue path.

## Acceptance
- [ ] Red cases for both shapes, failing on the revision 5 code.
- [ ] Valid headings such as "Proposed changes for issue #1 (following PR #2):" kept as positive controls.
- [ ] Grader revision bumped and recorded.

## Source nits (moved from the Nit Store, #20)
Full text of each source comment, so this issue stands on its own.

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6305559941 (2026-10-21)</summary>

**Severity: low.** `evals/level3/flow-auto-necessity/grade_flow_auto_necessity.py` `_has_plan`: a `Proposed changes` heading's own words are never read. "C. Proposed changes: none" or "C. Proposed changes for issue 2:", followed by numbered file steps, still credits TWIN with a plan. `_NO_PLAN` reads only the section BELOW the heading, and `_PLAN_HEADING` accepts any text after `proposed changes`.

Why it matters: a report that says outright there is no plan, or scopes the plan to a neighbour, can pass `case-disposition`. No live report has used this shape so far.

Context: found while working #499 (grader revision 5). Revision 5 gives the NEW `Proposed plan` heading a positive grammar for its heading line. It deliberately leaves `Proposed changes` at revision 4's form: Codex review pass 2 showed that tightening it broke valid headings such as "Proposed changes for issue #1 (following PR #2):". A fix needs the same positive heading grammar, with those headings kept as positive controls, and is a grader revision of its own.


</details>

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6305560231 (2026-10-21)</summary>

**Severity: low.** `evals/level3/flow-auto-necessity/grade_flow_auto_necessity.py` `_recommends_closing`: the revision 2-4 cue check is clause-local (it splits on `,`, `;` and `but`). So "Should I close #1, which was already closed?" and "Should I close #1, or keep it open?" credit a close recommendation: the first clause has a cue (`should`), and the historical or alternative wording sits in the next clause.

Why it matters: a report that offers closing as one alternative, or only reports a historical close, can satisfy CLEAN `case-disposition`.

Context: found while working #499. Revision 5's NEW assent-request form (`May/Shall I close #1`) checks the WHOLE sentence for alternatives, negation, history and other issues (Codex review pass 1). The older `should`/`can` cue path was left unchanged, to keep the revision scoped to the three live shapes.


</details>

Filed from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6382622225 at the owner's request (2026-10-24).

<!-- end of body -->
