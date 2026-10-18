# Give this project working CI/CD

This Python project (`calc-demo`) was just created with claude-power-pack's
`/project:init`. It has its source, its tests and a `uv.lock`, but no Makefile
and no CI.

Using claude-power-pack's CI/CD skills (`cicd-init`, `cicd-check`,
`cicd-pipeline`), give it:

1. a `Makefile` whose `lint`, `test` and `typecheck` targets really check the
   project (ruff, pytest and mypy, run through `uv run`);
2. `.claude/cicd.yml`, with `pipeline.provider: both`;
3. the generated CI pipelines for BOTH providers -
   `.github/workflows/ci.yml` and `.woodpecker.yml` - each running lint, test
   and typecheck as separate stages.

A stage that passes no matter what, is skipped or conditional, or stands in
for another stage does not count. Do not change the project's source, tests or
`pyproject.toml`: only add the CI/CD files.

How it is checked: the generated pipelines are executed locally (not on a
hosted CI service), on this tree and on copies with one planted lint, test or
type error each; every stage must pass the clean tree and the right stage must
reject each planted error.
