# Issue #19 as read by this run

EVIDENCE OF WHAT THIS RUN READ, not a second statement of the contract.
The issue is the authority; read it. This copy exists so a later check can
report that the source moved. It does not graduate.

- Issue:        #19
- Read at:      2026-09-25T14:02:00Z
- updatedAt:    2026-09-25T13:23:00Z   (context only - moves on comments and labels)
- Body digest:  f45545cd3a2c64bc6e4118f7f1d4f4cc6e5b042895b83f377c88d47b480af43a   (sha256 of the FULL body; the verdict keys on this)
- Stored bytes: 1181 of 1181 (cap 16384)

## Body as read
## Problem

`mypy .` reports 10 errors in `tests/test_records.py` on `main` (857781f):

- lines 78, 79, 87, 90, 92, 96, 97: `"object" has no attribute "id"` - `test_each_bad_case_fires_ITS_OWN_rule_and_NOTHING_ELSE(rule: object)` annotates the parametrized rule as `object`.
- lines 86-88: `found` is typed `list[Record]` by the first branch and then assigned `list[Skill]`, so `checks.run` receives a `Record`.

The repo's documented verify gate is `mypy skillc` (AGENTS.md), which is clean, so this went unnoticed; PR #17's "mypy clean" claim is accurate for that scope only. The CPP `/flow:finish` gate runs `mypy .` and fails on these, which blocked the finish gate for #18.

## Why it matters

The attribution test is the one guarding selftest's `frontmatter` early-return hole (see #2). Untyped, a refactor that changes the rule objects' shape is caught only at runtime.

## Acceptance

- [ ] `mypy .` is clean: annotate `rule` as the rule union (`checks.Rule | checks.RecordRule`) and split the two discovery branches into separately typed variables.
- [ ] Decide whether the CI gate (#18) should typecheck `tests/` too, and make AGENTS.md match.

Found while working #18.

