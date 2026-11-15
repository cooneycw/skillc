---
contract: flow-eli5
version: 3
intent:
  id: eli5.intent
  what: >
    The owner approves a plan only after seeing, in plain language, what will
    change, whether it is still needed, and where the claim will be exercised.
  approved: 2026-11-14
purpose: A plain-language plan, a necessity verdict and the proposed changes, for the owner to approve.
owner: owner
scope:
  in: [eli5.section-c, eli5.necessity]
provides:
  - id: eli5.section-c
    what: >
      proposed changes, a lane answer for every lane in .claude/lanes.md, and
      a Reader row per changed output (version 3 added the lane answers)
    readers: [flow-plan-record.approve, owner]
    test: checks/eli5-section-c/{bad,good}
requires:
  - id: eli5.issue-readable
    on_false: stop with UNKNOWN, never a guessed summary
    test: checks/eli5-issue-readable/{bad,good}
authority:
  - id: eli5.no-self-approval
    what: never approves its own plan
    approved: 2026-11-14
    test: checks/eli5-no-self-approval/{bad,good}
---

The flow-eli5 skill. Its contract block above is the part `skillc contracts` reads.
