# Provenance: slug small-fix fixture

## Source

| Field | Value |
|---|---|
| Repository | [cooneycw/claude-power-pack](https://github.com/cooneycw/claude-power-pack) (CPP) |
| Pinned commit | `5b6c4c64b923769d99c241cc600b0a467f8386f4` (`main`, 2026-09-25) |
| Source path | `tests/fixtures/delivery_pilots/pilots/pilot-b-small-fix/` |
| Source tree object | `1c424d19c3f26cb0813ac386c40e5ee49d44206c` |
| Introduced by | `1c2b1fb` (CPP #861 / PR #875, 2026-09-12) |
| Copied file | `src/slugify.py`, blob `8229b1b71d1d6d23cc10e4d68b646e89572c4f3e` |

`fixture/src/slugify.py` is a byte-identical copy of that blob.
`tests/test_level1_slug.py` checks its `git hash-object` identity, so an edit to
the start state cannot pass as the pinned one. The blob is unchanged between
`1c2b1fb` and the pinned commit. Verify it with:

```bash
git -C <cpp-checkout> rev-parse 5b6c4c64b923769d99c241cc600b0a467f8386f4:tests/fixtures/delivery_pilots/pilots/pilot-b-small-fix/src/slugify.py
```

## Independence from the subject revision

This pin identifies the task fixture only. The CPP revision under test is
selected separately, as the installed subject in #7 and the experiment manifest
in #12. Moving the subject to a newer CPP commit does not change this fixture,
and changing this fixture is a new task revision, not a subject change.

## License and reuse

CPP is MIT-licensed, `Copyright (c) 2025 cooneycw` (its `LICENSE` at the pinned
commit). skillc is MIT-licensed by the same holder. The copied file is
reproduced under that license with this notice:

> MIT License. Copyright (c) 2025 cooneycw. Permission is hereby granted, free of
> charge, to any person obtaining a copy of this software ... The above copyright
> notice and this permission notice shall be included in all copies or
> substantial portions of the Software.

The full text is CPP's `LICENSE` at the pinned commit.

## Deliberately not copied

| CPP file | Why not |
|---|---|
| `check_slug.py` | CPP's grader. skillc owns an independent grader (`grade_slug.py`) whose held-out inputs are tied to published requirements. |
| `task.md`, `task-open.md` | Audited, not inherited: they are the arms whose differences confounded CPP's comparison. See README.md, "Audit of the historical arms". |
