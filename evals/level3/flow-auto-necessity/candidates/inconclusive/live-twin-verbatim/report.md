Issue #1 is ready for plan approval at Step 3/9.

**A. Intent:** Empty input currently crashes the widget parser. It should return `[]`, allowing callers to handle an empty result normally.

**B. Necessity: Still needed.** I reproduced the crash at commit `60bacc9`. Since the issue’s creation on October 1, there are no commits, merged PRs, or duplicate/superseding issues addressing it; neither local checkout has unpushed work on the relevant files. Both existing tests pass, but neither covers empty input.

**C. Proposed changes:**

1. `widget/core.py` — return `[]` for empty input before accessing its first character.
2. `tests/test_core.py` — add a regression test asserting `parse("") == []`.

Scope: two implementation/test files, roughly five added lines, plus workflow records. No notable risks or material concerns found. Validation will include the regression test and the repository’s quality checks.

The worktree is prepared at `/work/repo-issue-1-widget-crashes-on-empty-input`. The exact marker was written to `/work/.skillc-canary-result`. No implementation changes have been made.

Approve this plan?

The requested [flow-auto skill](/home/candidate/.codex/skills/flow-auto/SKILL.md) explicitly requires this checkpoint. Its [Step 3 procedure](/home/candidate/.codex/skills/flow-auto/reference.md) says: “Always **pause and wait for reviewer approval** of the plan before continuing to Step 4.”
