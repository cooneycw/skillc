<!-- flow-run n=1 id=ae83b7533bc5404eb80effa142081b0c -->
## Run 1 - issue #726 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #726
- Read at:      2026-11-15T10:39:40Z
- updatedAt:    2026-11-14T20:33:20Z   (context only - moves on comments and labels)
- Body digest:  d908c7f8be457f713fd5895d01a925d8e0177f10e8babd38ab1cab1cc0411129   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 5888 of 5888 (cap 16384)

### Body as read
## Why

Round 1 of the skill-gauntlet (discussion #718) answers **"what is this skill for?"** Every later round measures a skill against its charter: round 3's tests, round 4's trims, round 5's verdict. Round 1 is what produces that charter. Today nobody starts with one, and the history in cooneycw/claude-power-pack#1830 shows purpose drifting when nothing pins it down, as with `/project:next` no longer recommending.

The owner's decision 1 on #718 puts charters in a `CHARTER.md` beside each `SKILL.md`. #720 defines that file's format and its static checks. This issue builds the round that **drafts** a charter from evidence, has the owner **confirm** it, and shows how it **overlaps** with the rest of the collection. It is #718's build step 3.

## What

### 1. Drafting a charter from what the skill has been seen to do

`skillc charter draft <skill>` reads three things:
- the skill's own text and git history;
- its usage records (`.skillc/usage.jsonl`, #719);
- repository evidence, once GitHub ingestion exists (#718 build step 4). Until then the draft says that source is missing; it does not leave it out silently.

From these it proposes the three-part charter (**Job**: one sentence; **Must always**: 2-4 outcomes; **Must never**: the safety rules) as #720's `CHARTER.md` YAML, every clause marked as a draft, and shows the evidence in #718's three columns:

| Observed and stated | Stated but never observed | Observed but never stated |
|---|---|---|
| core duties | candidates to drop, or the tests are missing | duties it took on unplanned: confirm or forbid |

Drafting is evidence, never a ruling. Every clause carries the evidence behind it, and a draft clause has no `approved` date. `intent` and `authority` clauses count only once the owner approves them (#718, "Contracts").

"Never observed" has to keep its honesty. When usage coverage is partial or missing (`coverage: partial`, Codex `unsupported`, or no usage log at all), a stated duty with no observation goes in the middle column as **`UNKNOWN`**, never as "never observed". An empty log is not evidence of non-use (see the hook-health note in the Nit Store, #20).

### 2. Owner confirmation, in a grilling-style dialogue

The owner works through the draft clause by clause: accept, edit, drop, or forbid an unplanned duty. Only the owner's answers become the charter. Approval stamps `approved: <date>` on `intent` and `authority` clauses. The tool never writes an approved charter by itself (#718 fixed rule: "never changes a charter without the owner").

**Stops when** there is no owner-approved charter. Round 1's report says so, and later rounds refuse to start.

### 3. The overlap (Venn) view across the collection

The tool compares each duty against every other charter in the collection **by meaning**, not by wording. That is a model call; #720's `duty-single-owner` already catches the same duty id by name. The report marks:
- **Shared:** two skills both claim the same job. Pick one owner and have the other point at it.
- **Shadowed:** this skill performs a duty another skill's charter already owns. This is the strongest candidate for removing text.
- **Orphan:** observed behaviour that no charter owns. Either a charter line is missing, or it is scope creep.

The diagram and the evidence for each overlap go in the round-1 report. Nothing is removed automatically; an overlap is a proposal for the owner to rule on.

## Acceptance

- [ ] **Negative control for the overlap view** (#718: "to be designed when round 1 is built"): two planted charters that share one duty **in different wording** must be flagged as shared. Two planted charters with no shared duty, but sharing vocabulary on purpose, must not be. Both cases are committed. Because the comparison is a model call, the PR states the model, the replicate count and the agreement rate, and says what happens on disagreement.
- [ ] **Negative control for drafting:**
  - a fixture skill whose text states a duty its usage records never show lands in the middle column;
  - a duty observed but never stated lands in the right-hand column;
  - with the usage log removed, the middle-column item reads `UNKNOWN`, not "never observed".
- [ ] `charter draft` with no evidence sources at all says "nothing to draft from" and exits non-zero. It never prints an empty charter.
- [ ] A draft passes #720's `contract-shape`, and its clauses fail `approval-present` (warn) until the owner confirms them.
- [ ] **Real-collection proof:** drafts, plus one owner-confirmed charter, for two CPP skills that hand off to each other. `/flow:eli5` and `/flow:auto` are suggested, being #720's worked example. The overlap view covers the CPP collection, and the PR shows its shared, shadowed and orphan counts and the evidence for each.

## Design questions to settle in the plan

- **Cost:** drafting and overlap make model calls. Decision 4 on #718 (a per-run budget cap) is still open and is ruled for rounds 3 and 4. Say whether round 1 needs its own cap, or a cost estimate through `skillc/cost_estimate.py`.
- **Overlap is a hypothesis, not a defect.** Some duplication protects a boundary or helps the skill be found, so a shared duty is a proposal, never an automatic finding against the skill. Raised by Codex (codex/gpt-6.1-sol), asked read-only to review the #718 charter on 2026-11-14 while #719 was worked.
- **Owner dialogue surface:** reuse the existing `grilling` skill's style, or a skillc-native prompt.

## Depends on

- #720 (the `CHARTER.md` format and its static checks). Drafts are written in that format.
- #719 (usage records), for the observed column. Merging now.
- GitHub ingestion (#718 build step 4) is **not** required. Its absence is reported in the draft.

Refs #718. Context: cooneycw/claude-power-pack#1830, #725 (round 2), #720 (format).

🤖 Generated with [Claude Code](https://claude.com/claude-code)


<!-- end of body -->
