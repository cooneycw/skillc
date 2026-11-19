---
contract: flow-auto
subject: .claude/commands/flow/auto.md
version: 1
intent:
  id: flow-auto.intent
  what: Deliver one issue end to end.
  approved: 2026-11-15
purpose: One issue, worktree to merge.
owner: owner
provides:
  - id: flow-auto.pr
    readers: [owner]
    test: checks/x-out/{bad,good}
---

A slash command's charter (owner decision 2026-11-15, #726).
