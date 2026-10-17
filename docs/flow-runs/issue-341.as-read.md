<!-- flow-run n=1 id=1c358b19280b4a519b2a2c6e1076492a -->
## Run 1 - issue #341 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #341
- Read at:      2026-10-12T14:14:18Z
- updatedAt:    2026-10-07T11:37:19Z   (context only - moves on comments and labels)
- Body digest:  ded33451e93b69a2ff406e90210146f44ba779b3d94fd609cfde9aed45f22100   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1660 of 1660 (cap 16384)

### Body as read
**Type:** scope:task. Follow-up hardening across all real-Docker live tests.
**Related:** #336 (introduces `_PropertyHeld` in #183's and #269's live tests), #266, #332, #315 (runner).

## Problem

Found by counter-model review on #336. Each live test file raises **one** `_PropertyHeld` type for every property it checks, and each break mode is marked `xfail(strict=True, raises=_PropertyHeld)`. Within a single break-mode run, the failure of a **neighbouring** property satisfies the xfail just as well as the targeted one. Example: in a `wrong-uid` run, a subject that exits non-zero for an unrelated reason is reported XFAILED before the uid is ever examined, and the control certifies a break it never observed.

This is a property of the shared pattern, not a regression. It is present in the live tests from #266 and #332, and in #183's and #269's once #336 lands.

## Fix

- Give each targeted property its own exception subtype, e.g. `_ExitPropertyHeld(_PropertyHeld)` or `_UidPropertyHeld(_PropertyHeld)`.
- Mark each break mode `xfail(strict=True, raises=<its specific subtype>)`.
- In the intact (`none`) run, every property must hold.

## Acceptance

- [ ] All five floor files are converted: channel, trial image build, witness, gate overlay, cold install.
- [ ] A committed `pytester` control shows that, under property A's break marker, a failure of property B is reported **FAILED**, not XFAILED.
- [ ] Mutation-checked: widening a marker back to the base type makes that control pass wrongly.
- [ ] The first real-runner run confirms each break reds on its own property. Record it on #315.

No live model trials are authorized by this issue.

