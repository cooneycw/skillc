# Uptake study, follow-up: a selective `flow-check` description

**Status: run 2026-10-06; see [report.md](report.md). SELECTIVE:** intended-use
20/20 vs published 0/20 (one-sided Fisher p = 7.3 × 10⁻¹²), near-miss 0/10. This follows the owner's ruling
q2 (a) on #237.

The first rewrite ("Use before you report a change as done ...") was selected
on the intended-use case 20/20 against 0/20, but also on the near-miss case
9/10 against 0/10 ([report](../report.md)). This run tests a rewrite
conditioned on being asked:

> Use when you are asked to run a project's quality checks (tests, lint, type
> checks, security scan): runs them in one step and reports what failed,
> without committing.

**Design.** The same design, size and identities as
[`evals/uptake-study`](../README.md): published vs this rewrite, 20 + 10
attempts per arm, seed `20261007`. [`flow-check-SKILL.md`](flow-check-SKILL.md)
is the pinned file with only its description line changed. An offline check
against the real pinned pack confirms that `check_rewritten_files` accepts
it.

**Predeclared reading.** The rewrite is *selective* if the primary test is
significant **and** near-miss selection is at most 2/10.

```bash
skillc degrade-subject cpp-codex --checkout <cpp at 85e9b03> \
  --override-file flow-check:SKILL.md=evals/uptake-study/selective/flow-check-SKILL.md --out <runs>/selective
SKILLC_ALLOW_REAL_AGENT=1 skillc uptake-study evals/uptake-study/selective/run-manifest.json --rewritten <runs>/selective
```
