<!-- flow-run n=1 id=8935e2bef25540c7b4cb5982f8fee831 -->
## Run 1 - issue #778 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #778
- Read at:      2026-11-15T18:19:55Z
- updatedAt:    2026-11-15T18:19:17Z   (context only - moves on comments and labels)
- Body digest:  ea26dc4412bfa6192176c839dcbd279cc17c8a030b58460237d2c21df4495a9e   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3087 of 3087 (cap 16384)

### Body as read
## Why

The owner's own `/skill-gauntlet` run (2026-11-15) stopped at round 1: its drafted `CHARTER.md` fails `clause-backed` (6 must-never clauses with no tests), and every duty column reads `unknown`. `charter draft` (#726) composes a charter from EVIDENCE: the skill's own MUST/NEVER sentences and usage records. When the skill is new, or usage records carry no duty tokens (`observed_as` is a convention nothing writes yet), the draft can only echo the skill text, and it leaves every clause untested.

The owner, 2026-11-15: "do we need a 'create' skill to compose a good charter? why don't we start there now that we know what we intend to do?"

A charter should state what the owner INTENDS. So the gauntlet needs an intent-first authoring flow that composes the charter WITH the owner and gives every clause a test from the start.

## What

`/charter-create <collection> <skill>`: a skill, plus a `skillc charter create` engine step, that holds a guided dialogue (grilling style, one decision at a time) and writes a charter in #720's format.

1. **Intent:** the job in one sentence, the purpose and what it provides. The owner's answer is the intent, and their approval sets `approved` on intent.
2. **Must-always / must-never, one clause at a time.** For every must-never, ask "what's the tempting shortcut a capable model would take here?" and turn the answer into a **trap-task stub**: a `bad/` case where the shortcut is the wrong move, and a `good/` case where the skill's rule is followed, in the `evals/level3` trap-task shape #736 PR 2 needs. The clause's `test` path points at those stubs, so `clause-backed` and `negative-backed` pass at creation. Stubs are marked as stubs, and #736 fills them into graded tasks.
3. **Authority:** who approves, and what the skill may never do alone. `approved` lands only on intent and authority clauses (as in `charter confirm`).
4. **Evidence, optional:** if a SKILL.md, usage log or `charter draft` output exists, offer its lines as suggestions with their file:line citations. Never accept one on the owner's behalf.
5. **Output:** CHARTER.md at the right place (beside SKILL.md, or `charters/<ns>/<cmd>/` with `subject:`) plus the stubs. It never edits the skill. `skillc contracts` must report the result CLEAN.

## Acceptance

- [ ] First real subject: **/skill-gauntlet's own charter**, composed with the owner. `skillc contracts` reports it CLEAN, and `/skill-gauntlet` on itself passes round 1.
- [ ] Controls:
  - an engine run with planted answers produces a CHARTER that passes contract-shape, clause-backed and negative-backed;
  - an unanswered clause is refused;
  - no approval stamps without an owner answer;
  - an answer that names no shortcut for a must-never refuses that clause (every never needs a trap);
  - the skill under review is unchanged (tree digest).
- [ ] The dialogue skill stays under a pinned word budget and never answers for the owner.
- [ ] The stub shape matches what #736 PR 2 consumes; that lane confirms.

Refs #726, #736, #738, #718. Related: #720 (format), #755 (charter draft/confirm).


<!-- end of body -->
