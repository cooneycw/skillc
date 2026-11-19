## The problem

Skills rot. They gather rules one incident at a time, and they outlive the reasons those rules were written. Then attempts to trim them either stall or quietly damage the skill. CPP discussion cooneycw/claude-power-pack#1830 documents this with git history: twelve of twelve "until #N" rules waiting on closed issues, rules removed and re-added, and a `/project:next` that stopped recommending because nothing tested that it still did its job.

skillc already has most of the machinery to fix this: `check`, `selftest`, `exposure`, `selection-probe`, `degrade-subject`, `configuration-compare`, an independent verifier, and per-skill digests in trial records (#424). What's missing is **one process** that strings those tools together in an order you can follow, for any skill, without having to remember it.

## The skill-gauntlet

One entry point. Run it, then do what its `NEXT:` line says.

```
skillc gauntlet <collection> <skill>        # engine
/skill-gauntlet <skill>                      # thin command for any session

  1 CHARTER  ->  2 INSPECT  ->  3 BASELINE  ->  4 CHALLENGE  ->  5 VERDICT
   (owner)       (free)         (paid, once)    (paid)           (owner)
```

- Every round ends with a verdict and either passes or stops with exactly **one** `NEXT:` line.
- State lives in a per-skill gauntlet record, so running the same command again resumes where it stopped.
- A round that couldn't run reads `UNKNOWN` and stops. It never passes.

### Round 1: Charter (what is this skill for?)

The charter has three parts:

- **Job:** one sentence.
- **Must always:** 2-4 outcomes.
- **Must never:** the safety rules.

Every line maps to an eval task. Purpose tasks are realistic, messy inputs on which the skill must still deliver. Guard tasks are inputs it must refuse. Some tasks are held back and never shown to the round-4 proposer.

**Drafting the charter from what the skill has been seen to do** (so nobody starts from a blank page):

- The gauntlet reads usage records (see *Usage tracking* below), the repo evidence it has taken in (*GitHub ingestion*), and the skill's own text and history.
- From those it proposes a charter in three columns:

  | Observed and stated | Stated but never observed | Observed but never stated |
  |---|---|---|
  | core duties | candidates to drop, or the tests are missing | duties it took on unplanned: confirm or forbid |

- The owner confirms the draft in a grilling-style dialogue. The draft is evidence. The charter is the owner's decision.

**Overlap with other skills (the Venn view):**

- The gauntlet compares each drafted duty against every other charter in the collection, by meaning rather than wording.
- It highlights three things:
  - **Shared duties:** two skills both claim the same job. Pick one owner and have the other point at it.
  - **Shadowed duties:** a duty this skill performs that another skill's charter already owns. This is the strongest candidate for removing text.
  - **Orphan duties:** nobody's charter owns this behaviour, yet it is observed. Either it's a missing charter line or it's scope creep.
- The diagram goes in the round-1 report, with the evidence behind each overlap. Nothing is removed automatically; overlap is a proposal for the owner to rule on.

**Stops when:** there's no owner-approved charter.

### Round 2: Inspect (free, mechanical)

- `skillc check`, plus new decay rules, each with a bad case and a good case so `selftest` covers it:
  - references to files, scripts or flags that don't exist in the skill's tree;
  - `until #N` or `expires-with: #N` markers whose issue has closed (with no network, this reports `UNKNOWN`, never `fine`);
  - passages copied from other skills in the collection;
  - emphasis density (MUST/NEVER/CRITICAL), which only warns.
- `skillc exposure`: what actually reaches the model.
- Output: findings sorted into **A** (already enforced elsewhere: shrink to a pointer), **B** (nothing enforces it: propose a check), **C** (a fact the code can't show: keep) and **D** (history or a retired feature: move to a reference doc).

**Stops when:** there's a hard error, such as a reference to a deleted helper. That is a bug, not a trim.

### Round 3: Baseline (can the tests tell when the skill is damaged?)

- Run the charter tasks three ways: on the current skill, with the skill removed (`degrade-subject --remove-skill`), and on a deliberately damaged copy (`--override-file`).
- **This round is the gauntlet's own negative control.** If removing or damaging the skill doesn't fail at least one purpose task, the tasks can't see damage. The gauntlet then refuses to approve any trim, and says why.
- It also records whether the skill helps at all. If "without" beats "with", the skill is a candidate for retirement.

**Stops when:** the tasks can't distinguish a damaged skill from an intact one.

### Round 4: Challenge (make it smaller, prove it)

- A model drafts a variant that edits only text outside the charter, working from round 2's A and D findings and round 1's shadowed duties.
- It is built with `degrade-subject --override-file` and compared with `configuration-compare --vary collection`.
- Every charter task is run, including the held-back ones, with replicates and pass/fail grading.
- **Passes only if** every must-always task still passes and every must-never task still refuses.

**Stops when:** no variant passes. That's a valid result: the skill is already lean.

### Round 5: Verdict (owner)

- One report: **keep**, **trim** (here is the PR, with before/after evidence) or **retire**.
- B findings become proposed checks, each naming its bad input. The prose stays as it is.
- The gauntlet drafts the PR. The owner merges, or doesn't.

## GitHub ingestion: proof from where the skill was actually used

Trials say what a skill does in a fixture. Repos say what it did in real work. The gauntlet can take in the repos where a skill was applied and derive outcome evidence:

**What it reads:**
- PRs and their review threads
- CI results on the PR head
- reverts and follow-up fixes that touch the same lines within N days
- issues reopened after a "Closes #N"
- Nit Store comments and friction logs that cite the PR or issue

**How an outcome is tied to a skill:**
- Through usage records (below) and commit or PR trailers, for example `Skill: flow-auto@<digest>`.
- Without that link, the gauntlet doesn't guess. The PR goes into an `unattributed` bucket, and the report says how big that bucket is.

**What it produces, per skill and digest:**
- merged without rework, or reworked
- CI green on the first push
- escaped defects (reverts, reopens, follow-up fixes)
- human interventions (owner corrections mid-run, like the lanes miss in #1830)
- time to merge
- each figure with its N

**What it can and can't prove:**
- This evidence is observational. A skill used on harder issues will look worse.
- So ingestion produces **signals and hypotheses**: "flow-auto@abc has 3x the rework of @def on comparable issues". Rounds 3 and 4 confirm or reject them under controlled conditions. The report keeps the two kinds of evidence visibly separate.
- Evidence from one repo is labelled as one repo's evidence. It isn't generalised.

## Usage tracking: so data repositories can show improvement or deterioration

Today we capture friction, but not which skill version was running when it happened. The proposal is a small, versioned **usage record**, validated by the same record rules skillc already enforces:

```json
{
  "kind": "skill-usage", "version": 1,
  "skill": "flow-auto", "skill_digest": "sha256:...", "collection": "claude-power-pack@908d332c",
  "invocation": "explicit | model-selected",
  "repo": "owner/name", "commit": "<sha>", "issue": 1828, "pr": null,
  "outcome": "completed | stopped | abandoned | unknown",
  "stop_reason": "approval-gate | gate-red | owner-correction | ...",
  "interventions": 1,
  "session": "<opaque id>", "client": "claude-code | codex", "model": "<id>",
  "at": "2026-11-14T13:36:00Z"
}
```

- **How it's emitted:** a hook writes the record at skill start and at skill end. Writing it is not the model's job, the same lesson CPP learned with permission-prompt capture. It goes to an append-only local file, and optionally to a data repository.
- **Data repositories:** a repo (or a store such as CPP's `cpp_memory`) collects the records. `skillc gauntlet --trend <skill>` produces per-digest series: outcome rate, interventions per run, stop reasons, rework from ingestion. When a skill changes, the next digest's numbers show whether it got better or worse, so a trim's effect is measured rather than assumed.
- **Its own negative control:** a planted deterioration (a digest whose seeded records show doubled interventions) must be reported by the trend. Otherwise a flat trend means nothing.
- **Privacy:** records carry no host paths, usernames, emails or prompt text, only identifiers and outcomes. Sending records anywhere beyond the local file is opt-in, per repo. A `skillc check-records` rule rejects a record containing a path under a home directory or an email address.

## Fixed rules

The gauntlet:

- never edits a skill directly;
- never raises a word budget;
- never changes a charter without the owner;
- never deletes a committed bad case;
- never counts an `UNKNOWN` as a pass;
- never presents observational repo evidence as causal.

## Build order

Cheapest first, with each step able to show its worth before the next one starts:

1. **Usage records and the hook.** This starts collecting data now, because every later round is better with history.
2. **Rounds 2 and 5 plus decay rules.** Free, and they work on any collection. Try them on CPP and on mattpocock/skills.
3. **Round 1 with observed-behaviour drafting and the overlap view.**
4. **GitHub ingestion,** with trailers added to CPP's PR templates so new work can be attributed.
5. **Rounds 3 and 4** (paid trials), once round 2 has found real problems in at least two collections.

## Open questions

- Where should the gauntlet record live: in the skill's repo beside the charter, or in skillc's evidence store?
- Should charters be part of the portable skill spec (a `CHARTER.md` beside `SKILL.md`), or skillc-only metadata?
- What's the minimum N before a trend is reported as a trend rather than a list of runs?

---
Background, evidence and the series this grew out of: cooneycw/claude-power-pack#1830. Approach credits from AI Engineer talks (auto-captions, approximate):
- Nick Nisi, "Deleted 95% of My Agent Skills": https://www.youtube.com/watch?v=vy7o1g2iHY8 (measure skills with and without; "enforce, don't instruct").
- Lance Martin, "Your Old Prompts Are Making Claude Worse": https://www.youtube.com/watch?v=ys6YQ2yfBpM (binary rubrics, replicates, train/test splits for evals).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
