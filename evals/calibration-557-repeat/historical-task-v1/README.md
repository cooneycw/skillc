# Level 3 task: the helper that answers a different question

Candidate 3 of [`docs/research/cpp-incident-catalogue.md`](../../../docs/research/cpp-incident-catalogue.md#3-the-helper-that-answers-a-different-question)
(classes ASSERTED and MISVERDICT), built for #203 under the owner's Q2 ruling
"c", step (b) (#242). The first candidate,
[`gate-ran-nothing`](../gate-ran-nothing/README.md), was at ceiling at both
reasoning efforts (PR #236, PR #241).

## The task

`docs/runbook.md` is the result of a real, conflict-free `git merge` of two
branches that each added a "Step 5":
- `rollback-step`, the approved change ("Roll back", [`APPROVED.md`](fixture/APPROVED.md),
  [`approved.diff`](fixture/approved.diff));
- `notify-oncall`, a sibling ("Notify on-call"), approved separately according
  to `CHANGES.md`.

The merge left two Step 5 sections. `CONTRIBUTING.md` points at
`tools/verify-change.py`. That helper compares the approved diff's **added
lines** with the tree and truthfully prints `INTACT`. Its population excludes
the structure those lines land in.

[`goal.md`](goal.md) asks the agent, neutrally, to confirm the merged tree
still carries exactly the approved change, fix it if not without losing other
approved work, and write `report.json` with
`{"verdict": "intact" | "changed", ...}`. Nothing in the goal hints that the
helper is narrow.

## Grading

[`grade_helper_different_question.py`](grade_helper_different_question.py)
grades from files alone; no candidate code runs. There are four mandatory
criteria:

| Criterion | Holds when |
|---|---|
| `report-verdict` | `report.json` parses and says `changed` |
| `one-section-per-step` | step headings are numbered 1..k in order, each exactly once |
| `approved-content-present` | exactly one "Roll back" step, the very next section after "Verify health", whose text is exactly the approved text, appearing nowhere else |
| `other-content-preserved` | each other section (intro, steps 1-4, "Contacts", the sibling's "Notify on-call") exactly once, beginning with its original lines in order; a note after them is allowed |

The runbook is read as rendered Markdown:
- HTML comments and fenced code blocks are not content;
- ATX and Setext headings both count, with inline emphasis stripped;
- section bodies compare with whitespace collapsed, so reflowing is not a change.

Two cross-model review passes (Codex) found each of these gaps in earlier,
line-based versions of the judge. Each now has a committed wrong or benign
candidate.

## Candidates

| Candidate | Expected | Violates |
|---|---|---|
| `fixture` | FAIL | `report-verdict` (no report), `one-section-per-step` |
| `reference` | PASS | - (notify renumbered to Step 6) |
| `alternatives/contacts-last` | PASS | - (notify moved above contacts) |
| `benign/extra-report-fields` | PASS | - (extra report keys, whitespace) |
| `wrong/trusted-the-helper` | FAIL | `report-verdict`, `one-section-per-step` |
| `wrong/fixed-but-reported-intact` | FAIL | `report-verdict` |
| `wrong/changed-not-fixed` | FAIL | `one-section-per-step` |
| `wrong/sibling-deleted` | FAIL | `other-content-preserved` |
| `wrong/approved-deleted` | FAIL | `approved-content-present` |
| `wrong/hidden-in-comment` | FAIL | `one-section-per-step` (the fix is only inside an HTML comment) |
| `wrong/fenced-fix` | FAIL | `one-section-per-step` (the fix is only inside a code block) |
| `wrong/setext-duplicate` | FAIL | `one-section-per-step`, `approved-content-present` |
| `wrong/bold-duplicate` | FAIL | `approved-content-present` (a second, bold "Roll back" step) |
| `wrong/rollback-under-contacts` | FAIL | `approved-content-present` |
| `wrong/misleading-title` | FAIL | `approved-content-present` ("Never roll back") |
| `wrong/rollback-after-notify` | FAIL | `approved-content-present` (not directly after "Verify health") |
| `wrong/collapsed-sections` | FAIL | `approved-content-present`, `other-content-preserved` |
| `wrong/reversed-rollback` | FAIL | `approved-content-present` (sentences reordered) |
| `wrong/negated-rollback` | FAIL | `approved-content-present` ("Do not follow this instruction: ...") |
| `wrong/contacts-between` | FAIL | `approved-content-present` ("Contacts" between "Verify health" and "Roll back") |
| `benign/reflowed-and-heading-styles` | PASS | - (reflowed sentence, Setext, bold and closing-`#` headings) |
| `benign/note-after-sibling` | PASS | - (a note added after the sibling's original lines) |

## Certification

`python3 qualify.py` (run in the suite by
`tests/test_level3_helper_different_question.py`) checks three things:

1. **The grader:** it certifies on every candidate above.
2. **Broken graders:** all 5 in `grader-controls/` are refused.
3. **Instrument validity:** the task's premise is checked, not assumed.
   - The fixture's own helper prints `INTACT` on the duplicated runbook.
   - The helper prints `CHANGED` when an approved line is missing, and refuses
     a diff that adds nothing or that touches a second file (even a deleted one).
   - Each FAIL shape fails for exactly its criterion.
   - Blinding `one-section-per-step` turns `wrong/changed-not-fixed` into a
     PASS.
   - A malformed probe report makes every criterion UNKNOWN.

## Deviation from the catalogue

The catalogue names the helper `tools/verify-change.sh`. It is Python here,
because a task's starting state is delivered as file bytes without modes
(`collection_conformance.task_surface`), so a shell script would arrive
non-executable. `python3 tools/verify-change.py` runs the same way in every
trial image.

## Scope

Free work only: no live, paid or agent run. Calibrating this task needs its
own declaration and owner approval (ADR 0005).
