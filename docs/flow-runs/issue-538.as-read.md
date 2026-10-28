<!-- flow-run n=1 id=29a8974240cd4a0396abba5f0abdf0ff -->
## Run 1 - issue #538 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #538
- Read at:      2026-10-28T00:51:00Z
- updatedAt:    2026-10-24T10:42:34Z   (context only - moves on comments and labels)
- Body digest:  0a7ca3b233ada5ba29d7afdb9bfd57d955064c741229121228763cf44da882ab   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2594 of 2594 (cap 16384)

### Body as read
**Severity: LOW** while neither instrument runs; **MEDIUM** before either is used again.

## Problem
Since #505, the calibration, collection, uptake and fixture paths deliver each installed file at the owner-only bits of its source mode. Two older call sites still pass no `extra_home_modes`, so every file arrives at 0600:
- `skillc selection-probe`: `skillc/cli.py:1129`
- `skillc pilot-run`: `skillc/cli.py:1564`

A skill's bundled helper scripts are therefore not executable there. That is the same broken-install failure #505 found in #434's campaigns. Confirmed still present on main `5ece908`.

## Acceptance
- [ ] Thread `cc._collection_home_modes(...)` through `sp.agent_trial_runner` and `mp.run_pilot` to `run_one_attempt(extra_home_modes=...)`.
- [ ] One test per path asserting the modes reach the attempt. Each must fail on the pre-fix code.

## Source nits (moved from the Nit Store, #20)
Full text of each source comment, so this issue stands on its own.

<details><summary>https://github.com/cooneycw/skillc/issues/20#issuecomment-6309232278 (2026-10-21)</summary>

**Severity: LOW** (neither instrument is active; MEDIUM once either runs again).

**Where:** `skillc/cli.py`, two call sites:
- `skillc selection-probe` (~line 1129): `sp.agent_trial_runner(..., treatment_home_files=cc._collection_home_files(...))`;
- `skillc pilot-run` (~line 1558): `mp.run_pilot(..., treatment_home_files=home_files)`.

Both still deliver installed skill files with no `extra_home_modes`.

**What's wrong:** after #505, calibration (both kinds), collection runs, uptake studies and #434's fixture path deliver each installed file at the owner-only bits of its source mode. These two older paths still deliver every file at 0600, so a skill's bundled helper scripts are not executable there. The only safe workaround is calling the helpers through an interpreter.

**Why it matters:** a future selection probe or matched pilot on a subject whose skills bundle executable helpers would measure a broken install, the same failure #505 found in #434's campaigns.

**Fix shape:** thread `cc._collection_home_modes(acquired.source, acquired.files)` through `sp.agent_trial_runner` and `mp.run_pilot` to `run_one_attempt(extra_home_modes=...)`. Add a test per path asserting the modes reach the attempt.

**Found while working:** #505 (Codex review pass 1 named the uptake path, fixed in that PR; these two were left out of its scope).


</details>

Filed from the Nit Store aggregation pass https://github.com/cooneycw/skillc/issues/20#issuecomment-6382622225 at the owner's request (2026-10-24).

<!-- end of body -->
