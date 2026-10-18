ELI5 Gate: Issue #1

== A. What this issue actually wants (ELI5) ==
`widget.parse("")` should return an empty list instead of crashing with an IndexError.

== B. Is it still needed? ==
Verdict: Still needed

Evidence (since 2026-10-01):
  - commits: none touching widget/core.py since the issue was filed
  - PRs: none merged
  - dup/super: none
Reasoning: nothing has landed that guards the empty spec.

== C. Proposed changes (pending approval) ==
  1. `widget/core.py` - return [] for an empty spec before indexing it
  2. `tests/test_core.py` - add test_an_empty_spec_has_no_parts
Scope: 2 files, ~6 lines
Risks: no notable risks

Approval: REQUIRED (interactive)

Step 3/9: ELI5 complete - verdict: Still needed; awaiting approval
