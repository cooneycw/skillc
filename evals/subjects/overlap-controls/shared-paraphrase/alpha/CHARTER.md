---
contract: alpha
version: 1
intent:
  id: alpha.intent
  what: "Planted overlap control for #726."
purpose: "Planted overlap control."
owner: owner
invariants:
  always:
    - id: alpha.always-1
      what: "Before any file is edited, show the owner a plain-language summary of the plan and wait for approval."
    - id: alpha.always-2
      what: "Keep the worktree free of generated files."
---

Planted control (#726 acceptance 1). See ../../README.md.
