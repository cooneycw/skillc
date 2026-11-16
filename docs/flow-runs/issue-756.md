# Flow run record - issue #756

HISTORICAL RECORD of what was agreed BEFORE the code was written, at the base SHA
each run below names. It is not a description of the shipped system, it is not a
second statement of the issue contract or of a Tier 3 spec, and it does not
graduate. APPEND-ONLY (#1320): each /flow:auto run adds its own `## Run <n>`
section; nothing earlier is edited, and every check reads only its own run.

<!-- flow-run n=1 id=b0559b8ad7a84fef88886d3011f21245 -->
## Run 1

- Run-id:            b0559b8ad7a84fef88886d3011f21245
- Run-start:         7c310679d498c3bdd51365f95e9db3ff1e1b75d1
- Issue:             #756 (one PR, Closes #756)
- Base SHA:          7c31067
- Necessity verdict: Still needed (all four reproduce on 7c31067 by reading; the only commit on these paths since filing is 7c31067 itself, the code under review)
- Approval:          granted (GO-WITH-CONDITIONS)
- Approver:          wave orchestrator skillc-orch, wave skillc-work (authority-model orchestrator-only, owner-delegated), mailbox rev 84
- Recorded at:       2026-11-16T02:40:00Z

### Section B evidence
- since 2026-11-15T13:36:38Z: 7c31067 (#773) only, on skillc/gauntlet_trials.py and tests/test_gauntlet_trials.py
- merged PRs after filing: #782 #780 #773 #772 #771 #770 #768 #767 #764 #762; none but #773 touch these paths
- dup/super: none

### Section C - the approved plan
1. `skillc/gauntlet_trials.py` - (1) the task digest is `source_digest.tree_entries` over goal.md and fixture/ (git mode plus blob; a symlink as its link text, never followed; a special file as not-a-file; unreadable is a DeclarationError), replacing `_digest_files`; (2) `assignments` orders each clause's fresh tasks by identity before the seeded shuffle; (3) `load` checks task identity against grader identity across the whole declaration before planning; (4) `arm_text` keys `changes` by the canonical relative path inside the resolved skill, and refuses a target outside it (`../`, absolute, a symlink out)
2. `tests/test_gauntlet_trials.py` - five regressions, each red on 7c31067, each with a twin control: execute bit and directory-symlink retarget re-spend; a rename keeps assignments; cross-clause conflicting graders refused with 0 runner calls; `./SKILL.md` after `SKILL.md` needs 0 new attempts; plus the escape refusal for canonical paths
3. `docs/specs/gauntlet-rounds-3-4.md` - task identity (modes, symlinks, special files; empty directories invisible, as in git), the identity-ordered split, the declaration-wide grader check, canonical passage paths
4. `changelog.d/756.md` - the fragment

Conditions (rev 84): one PR Closes #756; canonicalising refuses an escape, with a red case; tree_entries never follows links and empty directories are documented as invisible; held-out-name test updates named under Plan deviations; targeted set only (no ci/ paths); up to 3 counter-model passes, pass-3 findings onto #736's checklist; mailbox-gated push in a slot; merge after #787 unless reordered.
Scope: one module (~40 lines), tests, spec, fragment. Risks: every task digest changes, so an existing ledger no longer matches (none committed, nothing real has run); the identity-ordered split may change which control task is held out.

### Lanes for this change
| Lane | Answer |
|---|---|
| Checkout | not applicable |
| Run placement | will test - Woodpecker CI (full-suite gate); host targeted set only |
| Execution backend | not applicable - ScriptedRunner only; the real runner is #736 PR 3 |
| Agent client | not applicable - no client and no model call |
| Client invocation | not applicable |
| Static-check target | not applicable |
| Subject collection | will test - the synthetic control collection evals/gauntlet-controls |
| Subject installation | not applicable |
| skillc distribution | will test - source checkout; built wheel not covered |
| Python version | not covered - 3.12 only |

Readers:
- Reader: the attempt ledger (`Ledger`) reads task, grader and arm digests as its key. Compatibility: digests change value, not shape; no committed ledger exists.
- Reader: #737's `gauntlet verdict` reads the round 3/4 JSON. Compatibility: the report shape is unchanged.

### Plan deviations
- 2026-11-16, held-out-name test updates: **none needed**. Every existing test reads the held-out tasks from `split()` rather than by name, and all 61 pre-existing tests pass on the identity-ordered split unchanged.
- 2026-11-16, a sixth regression test was added, for the plan's "special file as not-a-file": `test_a_fifo_in_a_fixture_is_recorded_never_opened`. It is red on 7c31067, because the old digest skipped a FIFO.
- 2026-11-16, the two fixture-identity regressions assert the task's identity, not a re-run's attempt count. The identity-ordered split means a changed task can move between train and held-out, so a round 3 re-run's count also depends on the split. The ledger key carries `task_digest`, so a new identity is exactly "no cached grade for this task is reused". The cache-reuse twin still re-runs round 3 and spends 0 attempts.
