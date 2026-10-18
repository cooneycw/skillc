ELI5 Gate: Issue #1

== A. What this issue actually wants (ELI5) ==
`widget.parse("")` should return an empty list instead of crashing with an IndexError.

== B. Is it still needed? ==
Verdict: No longer needed

Evidence (since 2026-10-01):
  - commits: 1e7a7726f53 guards the empty spec
  - PRs: none needed beyond the commit
  - dup/super: none
Reasoning: the merged fix already guards the empty spec and adds a regression test.

Recommendation: close #1, citing commit 1e7a7726f53. No code was written and no PR was opened.

Step 3/9: ELI5 complete - verdict: No longer needed; approval: close recommended
