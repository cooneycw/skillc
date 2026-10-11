# Description optimizer (#238): the 11 most-used cpp skills

**Run 2026-10-06/07.** The skills are the 11 cpp-codex skills the operator
actually uses, by their own Claude Code invocation counts over the last 60
days. The other 63 had zero direct uses and are parked in #325.

## Verdicts

Columns: the published description's screen (select / abstain), variant-a's
screen, and the held-out confirmation (variant-a vs published, with variant-a's
held-out abstain).

| Skill | Uses | Published screen | Variant screen | Held-out confirmation | Verdict |
|---|---|---|---|---|---|
| `flow-check` | inside `flow-auto` | 2/6 · 0/3 | 6/6 · 0/3 | **7/7 vs 0/7**, abstain 0/5, p = 0.0003 | **improved** |
| `flow-auto` | 323 | 6/6 · 0/3 | 6/6 · 0/3 | 8/8 vs 8/8, abstain 0/5 | already good |
| `project-next` | 66 | 6/6 · 0/3 | 6/6 · 0/3 | 8/8 vs 8/8, abstain 0/1 | already good |
| `flow-register` | 41 | 6/6 · 0/3 | 6/6 · 0/3 | 8/8 vs 8/8, abstain 0/0 | already good |
| `flow-start` | 13 | 5/6 · 0/3 | 6/6 · 0/3 | 8/8 vs 8/8, abstain 0/5 | already good |
| `flow-wave` | 12 | 0/0 · 0/3 | 1/1 · 0/3 | no decided observations | **inconclusive** (probe limit) |
| `self-improvement-retro` | 4 | 6/6 · 0/3 | 6/6 · 0/3 | 8/8 vs 8/8, abstain 0/5 | already good |
| `flow-cleanup` | 3 | 6/6 · 0/3 | 6/6 · 0/3 | 8/8 vs 8/8, abstain 0/5 | already good |
| `flow-repair` | 2 | 6/6 · 0/3 | 6/6 · 0/3 | 8/8 vs 8/8, abstain 0/5 | already good |
| `flow-finish` | 2 | 3/3 · 0/3 | 6/6 · 0/3 | 8/8 vs 3/3, abstain 0/5 | **inconclusive** (probe limit) |
| `flow-merge` | 1 | 5/6 · 0/3 | 6/6 · 0/3 | 8/8 vs 8/8, abstain 0/0 | already good |

## Reading

1. **Only `flow-check`'s description fails.** Measured four times, its
   published wording "Run quality checks (lint + test + typecheck +
   security) without committing" was selected 0/20, 0/20 and 0/7 when asked to
   run a project's checks. The trigger-condition rewrite was selected 20/20,
   20/20 and 7/7, and stayed selective (0/10, 0/5). It was selected only when
   the request echoed its own words: "lint and test gates", 2/3.
2. **Every other description already works.** Each already names its situation
   in plain words. That holds even for the three whose published descriptions
   are cut off mid-sentence (`flow-register`, `flow-wave`,
   `self-improvement-retro`): the truncation did not prevent selection where
   it could be measured.
3. **The 45 s probe cannot measure long-running workflows.** `flow-wave` and
   `flow-finish` start blocking commands (orchestration, `git push` with no
   network) before the cut-off, so their attempts are *undecided*. They need a
   longer cut-off or full attempts.
4. **Some held-out abstain cases were mostly undecided.** These were
   `project-next` (1/5 decided), `flow-register` and `flow-merge` (0/5): the
   prompt sent the agent into a blocking command. Their selectivity rests on
   the development screen, where every arm abstained 0/3.

## What this does not show

- **Value:** whether reading a skill improves the work (#203).
- **Unprompted uptake:** every select case here asks for the action. This
  shows descriptions match requests, not that the agent reaches for skills
  unasked.

## Runs

- **Batch 1:** `flow-check`, `flow-start` and `flow-merge` (first pass).
- **Re-runs with the #319 rule:** `flow-auto` and `flow-finish`.
- **Batch 2 (priority):** the remaining six.
- **Identities:** codex-cli 0.157.1, `gpt-6-astra` effort `high`, image
  `sha256:eb17e8c7…`, cpp-codex @ `85e9b03`.
- **Evidence:** per-skill result files and stores stay in the operator's
  private run directories.
