ELI5 Gate: Issue #1

== A. What this issue actually wants (ELI5) ==
`widget.parse("")` should return an empty list instead of crashing with an IndexError.

== B. Is it still needed? ==
No longer needed once the pending fix lands.

Evidence (since 2026-10-01):
  - commits: e970b8b55d2 guards the empty spec
  - PRs: none needed beyond the commit
  - dup/super: none
Reasoning: the merged fix already guards the empty spec and adds a regression test.

Recommendation: close #1, citing commit e970b8b55d2. No code was written and no PR was opened.

Step 3/9: ELI5 complete - approval: close recommended
