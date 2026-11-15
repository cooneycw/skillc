---
contract: "skill-gauntlet"
version: 1
intent:
  id: "skill-gauntlet.intent"
  draft: true
  what: "Run the skill-gauntlet on one skill and report each round's verdict and the single NEXT step. Use when the owner asks to put a skill through the gauntlet, to check what a skill is for, or to see which ..."
  evidence:
    - "SKILL.md: frontmatter description"
purpose: "Run the skill-gauntlet on one skill and report each round's verdict and the single NEXT step. Use when the owner asks to put a skill through the gauntlet, to check what a skill is for, or to see which ..."
owner: "owner"
invariants:
  always: []
  never:
    - id: "skill-gauntlet.never-1"
      draft: true
      column: "unknown"
      what: "It never answers for the owner."
      evidence:
        - "SKILL.md:9"
        - "UNKNOWN: no usage log"
    - id: "skill-gauntlet.never-2"
      draft: true
      column: "unknown"
      what: "Say so; never round them up."
      evidence:
        - "SKILL.md:31"
        - "UNKNOWN: no usage log"
    - id: "skill-gauntlet.never-3"
      draft: true
      column: "unknown"
      what: "The run always stops by round 3 today: rounds 3 to 5 are not built, so the engine never exits 0 and never gives a keep, trim or retire verdict."
      evidence:
        - "SKILL.md:34"
        - "UNKNOWN: no usage log"
    - id: "skill-gauntlet.never-4"
      draft: true
      column: "unknown"
      what: "**Round 1 overlap:** overlaps are proposals for the owner, never findings against the skill."
      evidence:
        - "SKILL.md:48"
        - "UNKNOWN: no usage log"
    - id: "skill-gauntlet.never-5"
      draft: true
      column: "unknown"
      what: "Never edit the skill, its charter or its committed bad cases."
      evidence:
        - "SKILL.md:55"
        - "UNKNOWN: no usage log"
    - id: "skill-gauntlet.never-6"
      draft: true
      column: "unknown"
      what: "Never stage, commit or push `GAUNTLET.json`."
      evidence:
        - "SKILL.md:56"
        - "UNKNOWN: no usage log"
---

# Draft charter: skill-gauntlet

**Draft ready for owner confirmation.** Nothing here is approved.

From `SKILL.md`, no model call.

## Sources

- **skill text:** `SKILL.md`: a description and 8 stated duty candidate(s)
- **git history:** 1 commit(s), newest 62b197c 2026-11-15, oldest 62b197c 2026-11-15
- **usage records:** 0 record(s) for skill-gauntlet in 0 log(s); absences UNKNOWN (no usage log)
- **repository evidence:** missing (#718 build step 4)

## The three columns

| Column | Clause | Duty | Evidence |
|---|---|---|---|
| unknown | `skill-gauntlet.never-1` | It never answers for the owner. | SKILL.md:9; UNKNOWN: no usage log |
| unknown | `skill-gauntlet.never-2` | Say so; never round them up. | SKILL.md:31; UNKNOWN: no usage log |
| unknown | `skill-gauntlet.never-3` | The run always stops by round 3 today: rounds 3 to 5 are not built, so the engine never exits 0 and never gives a keep, trim or retire verdict. | SKILL.md:34; UNKNOWN: no usage log |
| unknown | `skill-gauntlet.never-4` | **Round 1 overlap:** overlaps are proposals for the owner, never findings against the skill. | SKILL.md:48; UNKNOWN: no usage log |
| unknown | `skill-gauntlet.never-5` | Never edit the skill, its charter or its committed bad cases. | SKILL.md:55; UNKNOWN: no usage log |
| unknown | `skill-gauntlet.never-6` | Never stage, commit or push `GAUNTLET.json`. | SKILL.md:56; UNKNOWN: no usage log |

## Further candidates, not drafted (2)

- never `SKILL.md:58`: Never count `UNKNOWN` as a pass, or read a round that did not run as clean.
- never `SKILL.md:59`: Never spend on trials.

## Limits

Per the round-1 spec (#726), the stated column undercounts, and `clause-backed` fails until round 3.
