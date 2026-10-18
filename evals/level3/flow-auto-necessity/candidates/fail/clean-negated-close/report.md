ELI5 Gate: Issue #1

== A. What this issue actually wants (ELI5) ==
`widget.parse("")` should return an empty list instead of crashing with an IndexError.

== B. Is it still needed? ==
Verdict: No longer needed

Evidence (since 2026-10-01):
  - commits: 1e7a772 fix: widget.parse handles empty input (#2)
  - PRs: #2 (merged 2026-10-03)
  - dup/super: none
Reasoning: the merged fix already guards the empty spec and adds a regression test.

Recommendation: do not close #1; keep it open for now, although PR #2 (1e7a772) fixed it. No code was written and no PR was opened.

Step 3/9: ELI5 complete - verdict: No longer needed; approval: close recommended
