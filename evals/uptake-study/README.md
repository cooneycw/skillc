# Uptake study (#237): does a rewritten description raise natural selection?

**Status: run 2026-10-04; see [report.md](report.md).** Primary: rewritten 20/20
vs published 0/20, one-sided Fisher p = 7.3 × 10⁻¹² (significant). Near-miss:
rewritten 9/10 vs published 0/10. Task PASS 60/60. This is the pilot of #238, the
description optimizer.

## Design

| | `published` | `rewritten` |
|---|---|---|
| Installed | cpp-codex @ `85e9b03`, whole surface | the same, with `flow-check/SKILL.md`'s description replaced |
| `flow-check` description | "Run quality checks (lint + test + typecheck + security) without committing" | "Use before you report a change as done: run this project's quality checks (tests, lint, type checks, security scan) in one step and report what failed, without committing." |

The owner approved the target and the wording on 2026-10-04 (#237).

[`flow-check-SKILL.md`](flow-check-SKILL.md) is the pinned file with only its
description line changed. `skillc uptake-study` refuses any rewritten snapshot
that differs from the published install anywhere else.

**Cases.** Both are on the qualified Level 1 `slug-small-fix` task:
- `intended-use` (primary, 20 attempts per arm): the task plus "Before
  finishing, run this project's quality checks (tests, lint, type checks) and
  report the result." `flow-check` exists for exactly that. Running the
  checks by hand stays allowed. Selection is the measure, never outcome
  success.
- `near-miss` (secondary, 10 attempts per arm): the bare task, a
  false-selection check.

**Primary test** (declared in advance): a one-sided Fisher's exact test that
`rewritten` selects `flow-check` more often on `intended-use`, at alpha
0.05. Selection counts only confirmed observations (one transcript, carrying
the attempt's own prompt). The power is in `run-manifest.json`'s
`power_note`: about 0.81 to detect a rise from about 5% to 40%.

**Why `flow-check`, not #26's `qa-test`.** `qa-test`'s description says it is
for web applications (Playwright), so declining it for a library's unit tests
is correct, not a discovery failure (#237).

## Running (after approval)

```bash
skillc degrade-subject cpp-codex --checkout <cpp checkout at 85e9b03> \
  --override-file flow-check:SKILL.md=evals/uptake-study/flow-check-SKILL.md --out <runs>/rewritten
SKILLC_ALLOW_REAL_AGENT=1 skillc uptake-study evals/uptake-study/run-manifest.json --rewritten <runs>/rewritten
```

That is 60 attempts in total, at about 100 s each.
