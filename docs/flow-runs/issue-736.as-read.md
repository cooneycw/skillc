<!-- flow-run n=1 id=62a61995a7a442568ae450309377ec66 -->
## Run 1 - issue #736 as read

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #736
- Read at:      2026-11-15T13:07:08Z
- updatedAt:    2026-11-15T12:37:20Z   (context only - moves on comments and labels)
- Body digest:  115249364fe7c1bd276c5bee15410fbb4198002271cd6ffdecb4f30e45c107d9   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 3510 of 3510 (cap 16384)

### Body as read
## Why

Rounds 3 and 4 of the skill-gauntlet (#718) are the only rounds that measure what a skill **does**, not what its text says. Round 5's verdict needs them. A **trim** verdict must come with before/after evidence, and the charter's guard test ("a lean skill must get **keep**") needs round 4's "no variant passes" result. Without these rounds, round 5 can only report `UNKNOWN`.

This is #718 build step 5. It is filed now so that the usable skill (the owner's target, 2026-11-14: "there should be a usable skill by round 5") has its whole path in the backlog.

## Blocked on an owner decision

**#718 decision 4: the paid-trial budget cap per run.** It is still open. The charter's must-never 4 says these rounds don't spend without a stated budget. Until the owner sets one, this issue is held, and `/flow:auto` stops at necessity.

## What

### Round 3: Baseline (paid, once per skill digest)
- Run the charter's clause tests (the `test` paths that #720 checks for existence) against the skill as it is, through skillc's existing trial runner.
- Use binary rubrics, replicates, and a train/test split of the tasks.
- **Stops when** the tasks can't tell a damaged skill from an intact one. Check this by running a planted damaged copy of the skill. If the scores don't separate, round 3 reports `UNKNOWN` and stops. This is the charter's guard test.
- Results are keyed by skill digest. A re-run on the same digest reuses them and never pays twice (must-always 4).

### Round 4: Challenge (paid)
- Generate leaner variants: remove class A and D text (from round 2) and shadowed duties (from round 1's overlap view). Score each variant against the baseline on the **held-out** split.
- A variant passes only if it is no worse on every clause test.
- **Stops when** no variant passes. That is a valid result and means **keep**.

### Budget enforcement
- Estimate the cost before any spend (`skillc/cost_estimate.py`). Refuse when the estimate exceeds the cap. Stop when the cap is reached mid-round, and record what ran.

## Acceptance

- [ ] **Negative control for round 3:** a task set that scores a planted damaged skill the same as the intact one stops round 3 with `UNKNOWN`. A task set that separates them passes. Both cases are committed.
- [ ] **Negative control for round 4:** a planted skill with one removable redundant passage yields a passing variant. A planted lean skill yields none, and the result reads **keep**.
- [ ] A run that would exceed the cap is refused before any spend, and a run with no cap set is refused. Both are tested offline.
- [ ] Re-running on the same digest spends nothing. This is shown by the cost ledger.
- [ ] Real proof: the charter's own purpose tests, CPP `/project:next` before the claude-power-pack#1626 fix, with replicate count and cost stated.

## Depends on
- Blocked by #726
- #718 decision 4 (owner)

Refs #718, #720, #725.

## Attribution

The approach comes from two AI Engineer talks, credited in #718. They are talks, so there is no repository, commit or licence to pin; this borrows ideas only, and no code. The citations are approximate (auto-captions).
- Nick Nisi, "Deleted 95% of My Agent Skills": https://www.youtube.com/watch?v=vy7o1g2iHY8 (measure a skill with and without it; "enforce, don't instruct").
- Lance Martin, "Your Old Prompts Are Making Claude Worse": https://www.youtube.com/watch?v=ys6YQ2yfBpM (binary rubrics, replicates, and train/test splits for evals).

🤖 Generated with [Claude Code](https://claude.com/claude-code)


<!-- end of body -->
