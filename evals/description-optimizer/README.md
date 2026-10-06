# Description optimizer (#238)

The owner ruled on 2026-10-06 to run all 74 cpp-codex skills, in priority
order, and to post results to claude-power-pack **12 skills at a time**.
Variants may be generated and tested without per-wording approval. Anything
proposed for CPP still goes to the owner. The plan and priority order are on
[#238](https://github.com/cooneycw/skillc/issues/238).

Each `batch-N.json` lists its skills. For each skill:
- two description **variants**, each stating a trigger condition ("Use when
  ..."), the principle #237's selective study established;
- **development** cases: two `select` and one `abstain`;
- **held-out** cases: one of each.

All cases are prompt addenda on the qualified `slug-small-fix` task.

[`scripts/description_optimizer.py`](../../scripts/description_optimizer.py)
runs a batch, skill by skill:
1. **Screen:** published + both variants on the development cases, with the
   45 s probe validated in PR #311, 3 attempts per cell. Each arm is scored
   as its select-rate minus its abstain-rate.
2. **Confirm:** the best variant vs published on the held-out cases, 8 select
   + 5 abstain per arm, with the predeclared one-sided Fisher test. If no
   variant beats published on the screen, the published description is
   **kept**.
3. **Verdict:** *improved* (significant and selective, abstain ≤ 0.2),
   *recall improved but not selective*, *not confirmed*, or *kept*.

```bash
SKILLC_ALLOW_REAL_AGENT=1 python3 scripts/description_optimizer.py \
  evals/description-optimizer/batch-1.json --cpp <cpp checkout at 85e9b03> --work <dir>
```

`tests/test_description_optimizer.py` checks that every committed batch
derives declarations that parse and authorize. An offline check against the
real pinned pack confirmed that every batch-1 variant builds with
`degrade-subject` and passes `check_rewritten_files`.

**Batch 1 finding before any run:** all five `github-issue-*` published
descriptions say "... in claude-power-pack". In any other repository, an
agent may reasonably read them as not applying.
