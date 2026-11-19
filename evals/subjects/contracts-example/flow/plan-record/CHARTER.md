---
contract: flow-plan-record
version: 1
intent:
  id: plan-record.intent
  what: An approved plan is recorded before any edit, so the diff can be compared against it.
  approved: 2026-11-14
purpose: Record and stamp the approved plan.
owner: owner
scope:
  in: [plan-record.approve]
provides:
  - id: approve
    what: the approval baseline the finish step compares against
    readers: [owner]
    test: checks/plan-record-approve/{bad,good}
---

The plan-record helper.
