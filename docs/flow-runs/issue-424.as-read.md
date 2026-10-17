<!-- flow-run n=1 id=c497ef24a7ed46659cf819b3bca66e82 -->
## Run 1 - issue #424 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #424
- Read at:      2026-10-17T16:52:26Z
- updatedAt:    2026-10-17T16:05:19Z   (context only - moves on comments and labels)
- Body digest:  f71a8e041a503d48a26501cfe2ce9711cd8904e795ed260fd0d65ea1b50132ca   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2010 of 2010 (cap 16384)

### Body as read
## Problem

#354 adds an **opt-in** pin: a trial that declares `skill_digests` gets its `skill-evidence` checked for unpinned, digest-omitted and stale attributions (`ledger-binding`), and `profile.skill_digest_pins(inventory)` derives the pins from a #265 inventory. A trial without `skill_digests` keeps the old shape-only behaviour, so nothing that exists changes verdict.

**No production planner declares the field yet.** Both production paths that create trials call `trial.plan(...)` without `skill_digests`:
- `skillc/calibration_run.py:318` `plan_calibration` (it calls `trial.plan` at `:357`);
- `skillc/uptake_study.py:397` `plan_study` (it calls `trial.plan` at `:417`).

So every trial these generate is unpinned, and its `skill-evidence` is still checked for shape only. #354's protection never applies to the evidence the #287/#288 flow-check study would produce. The #354 comment of 2026-10-12 records this gap ("the wave will need verified caller adoption for newly generated profile-based evidence before the #287/#288 path is ready").

## Outcome and acceptance

- [ ] `plan_calibration` and `plan_study` derive `skill_digests` from the treatment's #265 inventory (`profile.skill_digest_pins`) and declare them on every treated trial. A baseline or untreated arm that installs no skills says so explicitly rather than pinning nothing silently.
- [ ] A planner test FAILS on the current code, because the planned ledger has no `skill_digests`, and passes after.
- [ ] End to end: a planned trial whose recorded `skill-evidence` carries a digest different from the inventory is refused by `ledger-binding` (stale). The same bundle with the pins removed validates clean, which shows the planner is what armed it.
- [ ] #288's run declaration is not approved to run until this is merged.

## Scope

Caller adoption only. #354's design (opt-in pin, rule semantics) is unchanged.

Precondition for #287 / #288. Filed from the #354 drive (cpp-final-fix session) on the orchestrator's instruction.

