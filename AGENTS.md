# skillc

`skillc` is the build step skills never had. It refuses to ship a `SKILL.md` the
specification rejects, and it proves its own rules can fail before reporting them.

## Directives

- **A rule ships with a committed redcase or it does not ship.** See
  [ADR 0001](docs/decisions/0001-every-check-ships-a-redcase.md). If you cannot
  name the input that makes a new rule fire, the rule is not ready.
- **Run `skillc selftest` before trusting any `skillc check` output.** A rule that
  has gone blind reports the same green as a rule that is working.
- **Never let an empty population render as a clean one.** A scan with nothing to
  scan exits non-zero and says so.
- **Stdlib only in `skillc/`.** It has to run in a slim CI image with no network.
  Test and lint dependencies are fine.
- Use single dashes, never Unicode em or en dashes, in code and docs.

## Layout

- `skillc/spec.py` - the Agent Skills specification as a checkable object
- `skillc/checks.py` - the rules; each declares the control that proves it
- `skillc/records.py` - evaluation records as checkable objects; see [records spec](docs/specs/evaluation-facility/records.md)
- `skillc/cli.py` - `check`, `check-records`, `selftest`, `rules`
- `controls/<rule-id>/{bad,good}/` - the committed redcases
- `evals/` - behavioural evals; see `evals/README.md`

## Verify

```bash
uv run skillc selftest && uv run pytest && uv run ruff check . && uv run mypy
```

Woodpecker runs the same four checks on every pull request and push to `main`
(`.woodpecker/ci.yml`), plus `ci/negative-control.sh`, which removes one rule's
control and requires `selftest` to refuse. A green gate is only evidence while
that step can still go red.

`mypy` takes its scope from `[tool.mypy] files` in `pyproject.toml` (`skillc` and
`tests`). `ci/typecheck-control.sh` plants a type error in a test module and
requires mypy to report it, so narrowing that scope turns CI red.
