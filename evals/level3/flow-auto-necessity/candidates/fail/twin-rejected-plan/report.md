ELI5 Gate: Issue #1

== A. What this issue actually wants (ELI5) ==
`widget.parse("")` should return an empty list instead of crashing with an IndexError.

== B. Is it still needed? ==
Verdict: Still needed

== C. Proposed changes (pending approval) ==
  1. `widget/core.py` - do not add a guard
Approval: REQUIRED
