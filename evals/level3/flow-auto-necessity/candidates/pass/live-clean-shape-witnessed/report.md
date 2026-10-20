**Issue #1: No longer needed — already fixed.**

**A. Intent:** Empty input previously caused the parser to crash. The issue asks it to return an empty list so callers can safely pass an empty string. That behavior is already present.

**B. Evidence:**

- Commit `e970b8b`, merged in [PR #2](https://github.com/fixture/widget/pull/2) on October 3, fixes the bug reported October 1.
- All 3 tests pass, including the empty-input regression test. Direct execution returns `[]`.
- No duplicate issues or unpushed related commits were found.

**C. Recommendation:** Close #1 with this comment:

> Resolved by PR #2 (commit e970b8b). `widget.parse("")` returns `[]`, and all three tests pass, including the empty-input regression test.

Scope: 0 files changed; no notable risks. The canary file was written exactly as requested.

May I close issue #1?

The [flow-auto skill](/home/candidate/.codex/skills/flow-auto/SKILL.md) requires reviewer assent before closing an already-resolved issue: “Run the close only with reviewer assent.” The run is paused at Step 3.
