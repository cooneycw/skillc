# Uptake study report (#237): a rewritten description moves selection completely

**Run 2026-10-04, 17:31-18:44Z. Primary result: significant.**

On the primary case, the rewritten `flow-check` description was selected in
**20 of 20** attempts. The published description was selected in **0 of
20**. The one-sided Fisher's exact p is **7.3 × 10⁻¹²**, against a declared
alpha of 0.05.

## Run

- **Command:** `skillc degrade-subject ... --override-file flow-check:SKILL.md=evals/uptake-study/flow-check-SKILL.md`,
  then `SKILLC_ALLOW_REAL_AGENT=1 skillc uptake-study evals/uptake-study/run-manifest.json --rewritten ...`.
  Exit 0, from a fresh clone at the declared commit `3ffcecc`.
- **Rewritten snapshot:** the pinned cpp-codex @ `85e9b03` with exactly one
  file changed, `flow-check/SKILL.md`, at digest `sha256:a750b223…`. That is
  the same digest as the offline check. `check_rewritten_files` accepted it.
- **Experiment:** `uptake-c42ef09a`.
- **Identities:** codex-cli 0.157.1, `gpt-6-astra` effort `high`, image
  `sha256:eb17e8c7…`.
- **Integrity:** all 60 attempts confirmed (one transcript, carrying the
  attempt's own prompt) and model-eligible, with no unconfirmed or excluded
  attempt. All 60 transcripts were retained.

## Results

| Case | Arm | `flow-check` selected | Task PASS | Mean wall time | Mean tokens |
|---|---|---|---|---|---|
| intended-use (primary) | published | **0/20** | 20/20 | ~83 s | ~175k |
| intended-use (primary) | rewritten | **20/20** | 20/20 | ~80 s | ~137k |
| near-miss | published | 0/10 | 10/10 | ~50 s | ~103k |
| near-miss | rewritten | **9/10** | 10/10 | ~60 s | ~116k |

No other skill was selected in any attempt.

## What the transcripts show

- **The selections are real reads.** Rewritten-arm agents ran `cat` on
  `flow-check/SKILL.md` and then on its `reference.md` before working.
- **The published arm did the same job by hand.** Agents on the
  intended-use case ran `python3 -m unittest`, Ruff and mypy directly. One
  wrote "All checks passed: unittest, Ruff lint, and strict mypy type
  checks".
- **Outcome is unchanged.** Every attempt in every cell passed the task. On
  this task, the skill changed *how* the agent worked, not *whether* it
  succeeded.

## Reading the result

1. **Discovery is description-driven, and the effect is total.** The one-line
   description decided selection completely: 0% vs 100%, with all else
   identical. This is the first positive evidence for reading (D) in #237:
   the published description did not tell the agent the skill applied. It
   also explains the 0/19 natural uptake across #203's runs better than "no
   need" does.
2. **The rewrite is not more precise. It is broader.** On the near-miss case,
   the bare task with no request to run checks, the rewrite was selected
   9/10 times against 0/10. The predeclared design treats a rise there as a
   finding against R. Whether it is a cost depends on the reading:
   - "Use before you report a change as done" honestly applies to every
     change, and the agent took it at its word;
   - it raises recall on the intended case at the price of firing where it
     was not asked for.
3. **Selection is not value.** All 60 tasks passed. The study measures
   discovery, and says nothing about whether reading `flow-check` improves
   work. #203 asks that question, and its candidate-3 run found the guidance
   read but not applied.
4. **Bounds.** One skill, one task family, one model. The rewrite worked at
   both ends at once (intended and near-miss), so it does not show a
   description that is selective, only one that is persuasive.

## For #238 (the description optimizer)

The pilot shows the lever is large, which is why #238 is worth building.
It also shows that an optimizer scoring only should-select cases would
overfit to "always open me". #238's design already scores should-not-select
cases. This run is the evidence that the second score is essential.

## Evidence

`uptake-report.json`, the store and the 60 retained transcripts stay in the
operator's private run directory. The tables above transcribe them.
