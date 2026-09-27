## Summary



## Rests on



## Checklist

- [ ] Gates pass locally: `uv run skillc selftest && uv run pytest && uv run ruff check . && uv run mypy`, plus `uv run skillc leak-check` (see README's Contributing section for the full invocation).
- [ ] A `CHANGELOG.md` `[Unreleased]` entry was added (or the last commit carries a `Changelog-exempt: <reason>` trailer).
- [ ] **This PR body, and every commit message in it, cites decisions by issue number, PR number, or an ADR section - never a private message number (`msg NNNN`) or a worker name (`w1`, `w2`, ...).** These are unresolvable to anyone outside the fleet that produced this repository, and a squash merge copies this body verbatim into `main`'s commit message, which cannot be rewritten afterward (issue #100). A file-content guard (`tests/test_private_citations.py`) catches the same pattern in tracked files, but cannot see PR or commit text - this line is that check's only enforcement here.
- [ ] No `close(s|d)`/`fix(es|ed)`/`resolve(s|d)` followed by `#N` appears anywhere in this body or its commits, including in a negation or a quote - GitHub parses it as a closing keyword regardless. Use "Refs #N"; the maintainer closes an issue by hand after merge.
