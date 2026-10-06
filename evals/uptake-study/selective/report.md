# Uptake study follow-up: a description that is both effective and selective

**Run 2026-10-06, 00:50-01:58Z. Result: SELECTIVE, by the predeclared
reading.** The conditioned rewrite was selected on **20 of 20**
intended-use attempts (published: 0 of 20), and on **0 of 10** near-miss
attempts (published: 0 of 10). The one-sided Fisher's exact p is **7.3 ×
10⁻¹²**, and near-miss selection of 0/10 is well inside the declared at-most-2/10.

## Run

- **Command:** `skillc degrade-subject ... --override-file flow-check:SKILL.md=evals/uptake-study/selective/flow-check-SKILL.md`,
  then `SKILLC_ALLOW_REAL_AGENT=1 skillc uptake-study evals/uptake-study/selective/run-manifest.json --rewritten ...`.
  Exit 0.
- **Commit:** the run used PR #294's head `7737f1b`, whose tree is identical
  to the merge commit `540d6a3` on main.
- **Experiment:** `uptake-dda89e00`.
- **Rewritten snapshot:** cpp-codex @ `85e9b03` with only
  `flow-check/SKILL.md` changed, at `sha256:d4999dc3…`. The runner's guard
  accepted it.
- **Identities:** codex-cli 0.157.1, `gpt-6-astra` effort `high`, image
  `sha256:eb17e8c7…`.
- **Integrity:** all 60 attempts confirmed and model-eligible, all 60
  transcripts retained, and no other skill selected.

## Results, beside the first rewrite

| Case | Published | First rewrite ("Use before you report a change as done ...") | **Selective rewrite ("Use when you are asked to run ...")** |
|---|---|---|---|
| intended-use (asked to run checks) | 0/20, then 0/20 | 20/20 | **20/20** |
| near-miss (not asked) | 0/10, then 0/10 | 9/10 | **0/10** |

Task PASS was 60/60 here, as in the first run. Mean wall time and tokens:

| Case | Arm | Mean wall time | Mean tokens |
|---|---|---|---|
| intended-use | published | ~72 s | ~184k |
| intended-use | rewritten | ~61 s | ~136k |
| near-miss | published | ~45 s | ~103k |
| near-miss | rewritten | ~43 s | ~103k |

## Reading

1. **A description can be both effective and selective.** Conditioning on the
   situation ("when you are asked to run a project's quality checks") kept
   full recall on the intended case. It removed every near-miss selection
   the first rewrite produced (9/10 to 0/10).
2. **The published description's problem is that it never says when to use
   the skill.** It states what the skill does ("Run quality checks ...")
   but gives no trigger. Across the two studies it was selected **0 of 60**
   times, even when the task asked for exactly what it does.
3. **Selection is still not value.** All 60 tasks passed in both studies.
   The published arm ran the checks by hand, and on the intended case it
   cost about 35% more tokens.
4. **Bounds.** One skill, one task family, one model and two wordings. This
   shows that a selective wording exists, not how to find one for every
   skill. Finding one per skill is #238's job.

## For #238 and CPP

- **For #238:** score should-select and should-not-select cases separately,
  and prefer wordings that state a trigger condition. One study found a
  description that maximized only recall (9/10 false selection); the other
  found one that achieved both.
- **For CPP (the owner's decision):** the evidence supports replacing
  `flow-check`'s description with the selective wording, and auditing
  CPP's other descriptions for a missing trigger condition.

## Evidence

`uptake-report.json`, the store and the 60 retained transcripts stay in the
operator's private run directory. The tables above transcribe them.
