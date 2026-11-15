---
contract: beta
version: 1
intent:
  id: beta.intent
  what: Why beta exists.
  approved: 2026-11-14
purpose: beta delivers one thing.
owner: owner
consumes:
  - alpha.out@2
provides:
  - id: beta.out
    readers: [owner]
    test: checks/beta-out/{bad,good}
invariants:
  never:
    - id: beta.never
      test: checks/beta-never/{bad,good}
authority:
  - id: beta.no-self-approval
    approved: 2026-11-14
    test: checks/beta-auth/{bad,good}
---

Prose about beta.
