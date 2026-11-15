---
contract: alpha
version: 1
intent:
  id: alpha.intent
  what: Why alpha exists.
  approved: 2026-11-14
purpose: alpha delivers one thing.
owner: owner
provides:
  - id: alpha.out
    readers: [owner]
    test: checks/alpha-out/{bad,good}
invariants:
  never:
    - id: alpha.never
      test: checks/alpha-never/{bad,good}
authority:
  - id: alpha.no-self-approval
    approved: 2026-11-14
    test: checks/alpha-auth/good
---

Prose about alpha.
