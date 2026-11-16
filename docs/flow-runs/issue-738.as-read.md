<!-- flow-run n=1 id=e1084a90a414491a9b87060c64e21760 -->
## Run 1 - issue #738 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #738
- Read at:      2026-11-16T06:11:48Z
- updatedAt:    2026-11-16T04:52:49Z   (context only - moves on comments and labels)
- Body digest:  b6ed3989b7d8cacdc9f955e3b888dce95e6c01c4faafed7a3ec77bb1a0637aa6   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3263 of 3263 (cap 16384)

### Body as read
## Why

The owner's target, 2026-11-14: **"there should be a usable skill by round 5"**. Today the gauntlet is a set of separate `skillc` commands: `usage` (#719), `contracts` (#720), `inspect` (#725), and later `charter draft` (#726) and `gauntlet verdict`. #718 designs one entry point: "Run it, then do what its `NEXT:` line says". This issue builds that entry point and the thin skill that any session can call.

## What

### 1. The engine: `skillc gauntlet <collection> <skill>`
- It runs rounds 1 to 5 in order, using the per-skill gauntlet record. Running it again **resumes** where it stopped and never repeats paid work (must-always 4).
- Every round ends with a verdict and either passes or stops, with exactly one `NEXT:` line (#718).
- A round that isn't built or can't run reads `UNKNOWN` and stops. It never passes.
- Record location follows #718's open question ("in the skill's repo beside the charter, or in skillc's evidence store?"). The plan proposes one, and the owner rules on it at the Step-3 gate.

### 2. The skill: `/skill-gauntlet <skill>`
- A `SKILL.md`, with its own `CHARTER.md` (the gauntlet's charter v1 from #718), shipped in this repository. It is registered by hand, as #719 did for the hook. Registering it through CPP is a separate CPP issue (CPP interface changes need coordination issues).
- It calls the engine, shows each round's verdict, and stops at every owner point: charter confirmation (round 1), the budget (rounds 3 and 4), and the ruling (round 5). It never answers for the owner.
- **Size cap** (must-never 5, "grow into a second scaffold"): the skill text has a fixed word budget, checked by `skillc check` `body-budget`. Going over it is a finding against the gauntlet.

### 3. The gauntlet runs its own gauntlet first
- #718: "a tool without a charter can't start, and that includes this one." Before the skill is called usable, round 1 runs on the gauntlet itself and the owner confirms its charter.

## Acceptance

- [ ] **The charter's own tests** pass, each from real history:
  - **purpose:** CPP `/project:next` just before the claude-power-pack#1626 fix. The gauntlet flags that the "recommend a pick" duty was lost.
  - **purpose:** CPP `flow/wave.md` at `d5ef0a66`. It finds the stale #635 and #640 rules as class D.
  - **guard:** an already-lean skill gets **keep**.
  - **guard:** a charter whose tasks can't separate a damaged skill from an intact one stops round 3.
- [ ] **Resume control:** after a stop at the round-3 budget point, a second run does not re-run rounds 1 and 2 and spends nothing. This is shown by the record and the cost ledger.
- [ ] **Unbuilt-round control:** with a round's implementation absent, the run reads `UNKNOWN` at that round and stops. It never reports a pass.
- [ ] `/skill-gauntlet` is run end to end in a real Claude Code session on one CPP skill, and the session's verdict and `NEXT:` line are quoted in the PR.
- [ ] The gauntlet's own `CHARTER.md` is owner-confirmed, and `skillc contracts` reports it clean.

## Depends on
- Blocked by #726
- Blocked by #737

The engine and record (part 1) can start once #726 lands. The end-to-end acceptance needs round 5.

Refs #718, #719, #720, #725.

🤖 Generated with [Claude Code](https://claude.com/claude-code)


<!-- end of body -->
