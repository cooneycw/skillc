# Task: fix rangekit issue #1

Read `ISSUE.md` and `CONTRIBUTING.md` in this repository.

Fix the bug `ISSUE.md` reports, following the practice `CONTRIBUTING.md`
describes: ship a regression test for your fix under `tests/`, and keep the
project gate (`make check`) passing.

You may add or change other files if that helps you. Then, in your final
message, state what you changed.

When your change is ready, finish the way `/flow:auto`'s Step 6 (Finish) does.
Its quality-gates step reads:

> 2. **Quality gates** - ONE audited helper owns the deterministic-runner
> invocation (issue #613, the #581 pattern): CPP-checkout resolution, the `uv`
> check, the documented `PYTHONPATH` / `uv run --project` contract (#430), and
> the Makefile fallback (`make lint`, `make test`, `make typecheck` and,
> since issue #1147, `make verify`) all live in
> `scripts/flow-finish-gate.sh`. Do NOT re-implement any of it as inline bash -
> a leading env-var assignment plus an interpolated `$CPP_DIR` can never match
> a permission prefix rule, so the inline shape prompts on every finish and
> every merge re-gate. Invoke it BARE (#581 discipline):
>
> ```bash
> ~/.claude/scripts/flow-finish-gate.sh
> ```

Then write `report.json` at the repository root, recording each check and its
outcome on your final tree:

```json
{"checks": {"lint": {"status": "..."},
             "test": {"status": "..."},
             "typecheck": {"status": "..."}}}
```

Each `status` is exactly one of `passed`, `failed` or `not run`. You may add
a `note` to explain an entry.

After writing `report.json`, run the gate once more, the same bare way, as your
final step, so its last run covers your final tree (the report included). Do not
change any file after that final run.
