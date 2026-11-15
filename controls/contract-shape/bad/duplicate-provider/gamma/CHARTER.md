---
contract: gamma
version: 1
intent:
  id: gamma.intent
  what: Why alpha exists.
  approved: 2026-11-14
purpose: alpha delivers one thing.
owner: owner
consumes:
  - alpha.out@2
provides:
  - id: gamma.out
    readers: [owner]
    test: checks/alpha-out/{bad,good}
invariants:
  never:
    - id: gamma.never
      test: checks/alpha-never/{bad,good}
authority:
  - id: gamma.no-self-approval
    approved: 2026-11-14
    test: checks/alpha-auth/{bad,good}
---

Prose about alpha.
