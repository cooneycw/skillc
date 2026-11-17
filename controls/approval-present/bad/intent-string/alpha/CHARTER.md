---
contract: alpha
version: 1
intent: Why alpha exists.
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
    test: checks/alpha-auth/{bad,good}
---

Prose about alpha.
