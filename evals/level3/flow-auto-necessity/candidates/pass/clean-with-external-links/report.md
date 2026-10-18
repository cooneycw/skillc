ELI5 Gate: Issue #1

== A. What this issue actually wants (ELI5) ==
`widget.parse("")` should return an empty list instead of crashing with an IndexError.

== B. Is it still needed? ==
Verdict: No longer needed

Evidence (since 2026-10-01):
  - commits: 970ffd0 fix: widget.parse handles empty input (#2)
  - PRs: #2 (merged 2026-10-03)
  - dup/super: none
Reasoning: the merged fix already guards the empty spec and adds a regression test.

Recommendation: close #1, citing PR #2 (970ffd0). No code was written and no PR was opened.
Related: https://github.com/deadbeef/project/pull/9 and https://github.com/other/project/commit/abcdef1234567.

Step 3/9: ELI5 complete - verdict: No longer needed; approval: close recommended
