# Task: fix rangekit issue #1

Read `ISSUE.md` and `CONTRIBUTING.md` in this repository.

Fix the bug `ISSUE.md` reports, following the practice `CONTRIBUTING.md`
describes: ship a regression test for your fix under `tests/`, and keep the
project gate (`make check`) passing.

You may add or change other files if that helps you. Then, in your final
message, state what you changed.

When your change is ready, finish the way `/flow:auto`'s Step 6 does: run the
project's quality gates through the installed `flow-check` skill (its check
plan, then its check summary). Then write `report.json` at the repository
root, recording each check and its outcome on your final tree:

```json
{"checks": {"lint": {"status": "..."},
             "test": {"status": "..."},
             "typecheck": {"status": "..."}}}
```

Each `status` is exactly one of `passed`, `failed` or `not run`. You may add
a `note` to explain an entry.
