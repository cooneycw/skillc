---
contract: alpha
version: 1
intent:
  id: alpha.job
  what: Why alpha exists.
  approved: 2026-11-15
purpose: alpha delivers one thing.
owner: owner
authority:
  - id: alpha.job
    what: never approves its own plan
    approved: 2026-11-15
    test: checks/alpha-auth/{bad,good}
---

The intent and an authority clause share the id `alpha.job` (#749): one owner
answer would approve both.
