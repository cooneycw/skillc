---
contract: flow-auto
version: 1
intent:
  id: auto.intent
  what: One command runs an issue from worktree to merge, stopping where the owner must approve.
  approved: 2026-11-14
purpose: Orchestrate the parts, in order, with the owner's approval point.
owner: owner
scope:
  in: [auto.orchestration]
  out: [eli5.section-c, plan-record.approve]
consumes:
  - eli5.section-c@2
invariants:
  never:
    - id: auto.never-skip-gate
      what: never implements before Section C is approved
      test: checks/auto-never-skip-gate/{bad,good}
authority:
  - id: auto.owner-approves
    what: the owner, not the run, approves the plan
    approved: 2026-11-14
    test: checks/auto-owner-approves/{bad,good}
---

The composite. It still consumes Section C at version 2, the copy it carried before
flow-eli5 added lane answers: exactly the 2026-11-14 lanes miss (CPP #1830, Part 5).
