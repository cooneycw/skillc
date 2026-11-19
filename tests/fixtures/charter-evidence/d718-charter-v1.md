## Charter v1: skill-gauntlet

**Status:** draft. On 2026-11-14 the owner ruled on decisions 1 and 2 below. The charter text itself, and decisions 3 and 4, are still waiting for owner confirmation.

The gauntlet goes through its own round 1 first: a tool without a charter can't start, and that includes this one.

**Job:** take any skill and return one evidenced verdict (keep, trim or retire) and one `NEXT:` step, without ever making the skill worse.

**Must always**
1. End every run with exactly one verdict line per round and one `NEXT:` line. That includes the case where a round couldn't run: it reports `UNKNOWN` and stops.
2. Cite the evidence behind every finding: the record, PR, check result or task run.
3. Propose removals as well as additions. A run that only adds things has failed.
4. Resume from its record. Running it again never repeats paid work an earlier round already did.

**Must never**
1. Edit a skill, merge a change, or change a charter without the owner.
2. Raise a word budget, weaken a gate, or delete a committed bad case.
3. Count `UNKNOWN` as a pass, or present observational repo evidence as proof of cause.
4. Spend on paid trials (rounds 3 and 4) without a stated budget, or go over it.
5. Grow into a second scaffold. If the gauntlet's own instructions exceed a fixed size, that is a finding against the gauntlet.

**Its own charter tests, drawn from real history**
- **Purpose:** run it on CPP's `/project:next` as it stood just before the cooneycw/claude-power-pack#1626 fix. It must flag that the "recommend a pick" duty was lost.
- **Purpose:** run it on CPP's `flow/wave.md` at `d5ef0a66`. It must find the stale #635 and #640 workaround rules as class D.
- **Guard:** run it on a skill that is already lean. It must say **keep**, not trim just to have done something.
- **Guard:** give it a charter whose tasks can't tell a damaged skill from an intact one. Round 3 must stop.

## Decisions

| # | Decision | Status |
|---|---|---|
| 1 | Charters live in a `CHARTER.md` beside each `SKILL.md`, in the skill's own repo | **Ruled: yes** (owner, 2026-11-14) |
| 2 | Usage records start as an append-only local file per repo. Sending them to a data repository comes later and is opt-in | **Ruled: yes** (owner, 2026-11-14) |
| 3 | The PR trailer `Skill: <name>@<digest>` changes CPP output that other tools read, so it needs a stated reason and coordination issues in kyle, skillc and kyle-candidate before it lands | open, sequenced for build step 4 |
| 4 | A paid-trial budget cap per run, set by the owner | open; rounds 3 and 4 aren't built until it is set |

**To be designed when round 1 is built:** the overlap view compares duties by meaning, which is a model call. It needs its own negative control: two planted charters that share one duty in different wording must be flagged.

First build issue: https://github.com/cooneycw/skillc/issues/719