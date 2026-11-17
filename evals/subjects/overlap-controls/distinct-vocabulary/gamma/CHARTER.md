---
contract: gamma
version: 1
intent:
  id: gamma.intent
  what: "Planted overlap control for #726."
purpose: "Planted overlap control."
owner: owner
invariants:
  always:
    - id: gamma.always-1
      what: "After the merge, write the owner a summary of which plan edits needed approval."
    - id: gamma.always-2
      what: "Keep the worktree free of generated files."
---

Planted control (#726 acceptance 1). See ../../README.md.
