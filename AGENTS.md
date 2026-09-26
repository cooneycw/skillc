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
- Locate active work and gates through [PLAN.md](PLAN.md).
  Requirements apply within their declared scope and delivery phase;
  recommendations in research do not become acceptance by appearing there.

## Layout

- `skillc/spec.py` - the Agent Skills specification as a checkable object; its
  frontmatter subset and target profiles are documented in [docs/frontmatter.md](docs/frontmatter.md)
- `skillc/checks.py` - the rules; each declares the control that proves it
- `skillc/records.py` - the evaluation-record contracts (receipt, ledger, manifest, result, attempt lifecycle) and the bundle rules that bind them to a ledger; see [records spec](docs/specs/evaluation-facility/records.md)
- `skillc/materialize.py` - installs a declared skill surface into disposable homes and
  proves what the client lists; see [materialization spec](docs/specs/evaluation-facility/materialization.md).
  Generic: subject conventions live in `subject.json`, never in this module
- `skillc/trial.py` - the controller: plans the expected population, runs and confirms the
  stop of each attempt, captures its output into owned storage and accounts for every
  attempt; see [capture spec](docs/specs/evaluation-facility/capture.md)
- `skillc/cli.py` - `check`, `check-records`, `selftest`, `rules`, `materialize`
- `controls/<rule-id>/{bad,good}/` - the committed redcases
- `evals/` - behavioural evals; see `evals/README.md`
- `evals/level1/<task>/` - a goal-based task: pinned fixture, public `goal.md`, grader,
  reference/alternative/wrong candidates and a `qualify.py` gate that must refuse broken graders
- `evals/subjects/<subject>/` - a declared subject (`subject.json`, `SUBJECT.md`) and the
  evidence `skillc materialize` produced for it
- `tests/fixtures/codex-subject/` - a two-skill collection and `fake_codex.py`, a stand-in
  client for CI, which has neither git nor Codex
- `tests/fixtures/trial-subject/fake_subject.py` - a deterministic subject that works, crashes,
  hangs, leaves children running or forges records, for the controller tests

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

`secret-scan` runs gitleaks over the checked-out tree with `.gitleaks.toml`, and
`ci/secret-scan-control.sh` plants a key and requires it to be found. CI only
sees a secret after it is on GitHub, so install the pre-push hook once per clone:

```bash
bash ci/install-hooks.sh
```

It scans the commits a push would send and refuses on a finding, or when
gitleaks is missing. It installs into `.git/hooks` beside the existing hooks;
do not set `core.hooksPath`, which would switch those off.
