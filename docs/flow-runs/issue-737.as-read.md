<!-- flow-run n=1 id=b72e9c5763fe476b9ca7cce4e8dc67dc -->
## Run 1 - issue #737 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #737
- Read at:      2026-11-15T15:34:01Z
- updatedAt:    2026-11-15T15:33:41Z   (context only - moves on comments and labels)
- Body digest:  43426e7ffb1b60268f7235658186424b07548b3ff80caa598cc3fd94011e2763   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 2938 of 2938 (cap 16384)

### Body as read
## Why

Round 5 is where the skill-gauntlet (#718) produces its output: **one evidenced verdict, keep, trim or retire, and one `NEXT:` line**. That is the gauntlet charter's Job. Rounds 1 to 4 only gather evidence, and without round 5 nobody acts on it.

The owner set the target on 2026-11-14: "there should be a usable skill by round 5". This issue builds the verdict. The usable skill that runs all five rounds is a separate issue, the engine and `/skill-gauntlet` (see "Depends on").

## What

### 1. The verdict report: `skillc gauntlet verdict <skill>`
- It reads the per-skill gauntlet record: the charter (round 1), inspect findings (round 2, #725), and the baseline and challenge results (rounds 3 and 4).
- It proposes exactly one of:
  - **keep**: no variant passed round 4, or nothing was found to remove;
  - **trim**: the winning round-4 variant, as a drafted PR with before/after scores per clause test;
  - **retire**: the charter's Job is shadowed by another skill's charter (round 1 overlap), or no clause has any observed use. A retire proposal names the skill that takes over each duty.
- Every finding cites its evidence (must-always 2). A **trim** must also remove text, not only add it (must-always 3).
- Class B findings from round 2 become **proposed checks**. Each names its bad input. The prose they describe stays as it is until the check exists (#718 round 5).

### 2. The owner rules, and the tool never does it alone
- The gauntlet drafts the PR. It never merges, edits a skill, or changes a charter (must-never 1).
- The owner's ruling (accept, reject, or amend) is recorded in the gauntlet record with a date.

### 3. Honesty rules
- If any earlier round is `UNKNOWN`, the verdict is `UNKNOWN`, and `NEXT:` names that round. It is never **keep** by default (must-never 3).
- Repository evidence (#718 build step 4) is labelled observational, never causal.

## Acceptance

- [ ] **Negative controls**, each committed with its expected verdict:
  - a planted lean skill reads **keep**. This is the charter's guard test: "keep, not trim just to have done something";
  - a planted skill with a removable passage reads **trim**, and its drafted diff removes that passage;
  - a planted skill whose only duty another charter owns reads **retire**, and names that owner;
  - a record with an `UNKNOWN` round reads `UNKNOWN`, and `NEXT:` names the round.
- [ ] Every run prints exactly one verdict line and one `NEXT:` line. This is tested across all four cases.
- [ ] No code path writes to the skill under review or its `CHARTER.md`. A test checks this by tree digest before and after.
- [ ] Real proof: the charter's purpose test on CPP `flow/wave.md` at `d5ef0a66` (the stale #635 and #640 rules found as D, proposed for removal), with the owner's ruling recorded.

## Depends on
- Blocked by #726
- Blocked by #736

Refs #718, #720, #725.

🤖 Generated with [Claude Code](https://claude.com/claude-code)


<!-- end of body -->
