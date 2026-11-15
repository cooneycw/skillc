<!-- flow-run n=1 id=b8674953e1664a24833579561107aeb2 -->
## Run 1 - issue #754 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #754
- Read at:      2026-11-15T13:14:38Z
- updatedAt:    2026-11-15T13:06:11Z   (context only - moves on comments and labels)
- Body digest:  d7f0d459494aba2595517dd5ab93284b4c73db45d328d7426df54bfe991320b7   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3777 of 3777 (cap 16384)

### Body as read
## Why

The owner wants a usable `/skill-gauntlet` soon (2026-11-15). The paid rounds (#736 rounds 3-4, #737 round 5) are still to be built, but rounds 0-2 are on main or landing: usage (#719), round 2 inspect (#725, #731, #741), contracts (#720), and round 1 charter draft, confirm and overlap (#726). This issue is the first slice of #738: the engine, the record and the skill for the **free rounds only**. The paid rounds then plug into the same engine.

The design is #718's (skillc discussion #718, and claude-power-pack discussion #1830 Part 7): the gauntlet **orchestrates only**. It runs the existing commands, reads their verdict lines, and never re-implements a round or copies a round's passages.

## What

1. **Engine: `skillc gauntlet <collection> <skill>`**
   - Runs, in order:
     - round 0: `usage` for this skill, with any log it can find;
     - round 1: `charter draft` when no CHARTER.md exists, and stops for owner confirmation; `contracts` when one does;
     - round 2: `inspect`, filtered to this skill;
     - round 1's overlap view: `charter overlap`. With no comparator configured this reads "not examined" (exit 3), as designed.
   - Each round ends with its verdict, and either passes or stops, with exactly one `NEXT:` line (#718).
   - **Rounds 3, 4 and 5 read `NOT BUILT` and the run stops there.** It never passes, and never reads as keep, trim or retire. The final line says plainly: "no trials ran; this is not a keep/trim/retire verdict".
   - **Resume:** a per-skill record stores each round's verdict and its inputs' digests. A re-run skips rounds whose inputs are unchanged and re-runs the rest.
2. **Record location.** #718's open question: in the skill's repo beside the charter, or in skillc's evidence store? The plan proposes one, and the owner rules at the Step-3 gate. The usage log stays local (#718 decision 2), so the record must not copy usage rows. It stores digests and verdicts only.
3. **Skill: `/skill-gauntlet <skill>`**
   - A `SKILL.md`, plus its own `CHARTER.md` drafted with #726's tool and left for the owner to confirm.
   - It calls the engine, shows each round's verdict, and stops at every owner point. It never answers for the owner.
   - It has a fixed word budget, checked by `skillc check` (body-budget), per must-never 5.
   - It is registered by hand in this repo. Registering it through CPP is a separate CPP coordination issue.

## Acceptance

- [ ] **Purpose control:** on CPP `flow/wave.md` at `d5ef0a66`, the run surfaces the closed #635 and #640 rules as class D (from inspect) and ends at `NOT BUILT` for round 3.
- [ ] **Unbuilt-round control:** with round 3 absent, the run reads `NOT BUILT` / `UNKNOWN` at round 3 and stops, never a pass. Committed.
- [ ] **No-charter control:** a skill with no CHARTER.md stops at round 1 with "draft ready for owner confirmation", never later rounds' verdicts.
- [ ] **Resume control:** a re-run with unchanged inputs re-runs nothing (shown by the record). Changing the SKILL.md re-runs rounds 1 and 2.
- [ ] **Orchestration only:** the engine imports no round's internals beyond their public command entry points or report JSON. `skillc inspect` reports no copied-passage between the skill text and the round specs.
- [ ] `/skill-gauntlet` is run in a real Claude Code session on one CPP skill. The PR quotes the verdicts and the `NEXT:` line.

## Out of scope

Rounds 3-5 (#736, #737), the keep/trim/retire ruling, and GitHub ingestion (#718 step 4, decision 3).

## Attribution

The round structure comes from skillc discussion #718, which credits two AI Engineer talks. They are talks, so there is no repository, commit or licence to pin. Only the ideas are borrowed; no code is.

Part of #738. Blocked by #726. Refs #718, #719, #720, #725, #736, #737.


<!-- end of body -->
