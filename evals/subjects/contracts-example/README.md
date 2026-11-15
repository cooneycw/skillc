# contracts-example

A three-skill fixture for `skillc contracts` (#720), modelled on the hand-off from
`/flow:eli5` to `/flow:auto`: one composite (`flow/auto`) and two parts
(`flow/eli5`, `flow/plan-record`). It is test material, not a product skill set.

As committed it carries the real 2026-11-14 defect: `flow-eli5` provides
`eli5.section-c` at version 3 (it added lane answers), while `flow-auto` still
consumes `eli5.section-c@2`. So:

```bash
skillc contracts evals/subjects/contracts-example   # handoff-version BAD, exit 1
```

Changing `flow-auto`'s `consumes` to `eli5.section-c@3` makes every rule clean
(exit 0). `tests/test_contracts.py` runs both. The `checks/` tree holds the
placeholder test paths the clauses name; `skillc contracts` checks that they exist,
never that they can fail (rounds 3 and 4 of #718).
