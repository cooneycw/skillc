# Changelog

All notable changes to skillc are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Dates are the day the
work landed on `main`, not the day a version is tagged - see
[#72](https://github.com/cooneycw/skillc/issues/72) for the release checklist
and version plan.

## [Unreleased]

Everything below has landed since `0.1.0` and is not yet part of a tagged
release; `0.2.0` is planned when [#10](https://github.com/cooneycw/skillc/issues/10)
(a real Docker trial end to end) closes, `0.3.0` when
[#11](https://github.com/cooneycw/skillc/issues/11) (a second independent
collection) closes.

### Added

- **Self-maintaining version and README instruments** (#73): `skillc.__version__`
  reads `pyproject.toml`'s `version` through the package's own installed
  metadata instead of a second literal; `skillc --version`; this changelog and
  its CI gate; README drift checks (commands, version, status vs. a committed
  milestones file).
- **`skillc leak-check`** (#63): refuses a tree or a produced bundle carrying a
  machine identity - a home-directory path, a `uid=`/`gid=` number, a private
  (RFC 1918) IPv4 address, or a hostname from a locally-configured deny-list.
  Wired into CI on the whole repository tree, with its own negative control.
- **A second, independently-authored subject** (#11): mattpocock/skills,
  proving `skillc materialize`'s "generic by declaration" design against a
  collection with a bucketed layout, a manifest-scoped shipped surface and
  Codex-native invocation metadata - no adapter change needed.
- **`skillc check --manifest`** (#53): scopes a check to a plugin manifest's
  declared skills (`.claude-plugin/plugin.json`), reporting the undeclared
  remainder as a count instead of mixing shipped and draft skills into one
  total.
- **`skillc check --json`, a repair-hint consumer, and a clean packaged
  install proof** (#27): machine-readable findings for tool consumption, and
  `ci/clean-install-check.sh`, which builds a real wheel into a fresh venv and
  proves `skillc selftest`/`check` behave the same as the source checkout.
- **`invocation-consistency`** (#50): a new rule comparing Claude Code's
  `disable-model-invocation` (`SKILL.md`) against Codex's
  `policy.allow_implicit_invocation` (`agents/openai.yaml`), refusing to treat
  an unreadable second-client file as agreement.
- **`skill-invocations`, an optional declared observation** (#39): gives
  "skill actually invoked" its own place in the evaluation record contracts,
  so "available but never invoked" no longer has to be re-derived from raw
  events outside any rule.
- **The execution backend seam and lifecycle driver** (#65, #70, Refs #10): a
  `Protocol`-based `ExecutionBackend` and `skillc/lifecycle.py`, which drives
  one attempt through prepare/install/execute/confirm_stopped/export/destroy/
  confirm_absent/finalize against a real backend, with a nonce liveness canary.
- **Native materialization and a proven clean baseline** (#7): `skillc
  materialize` installs a declared skill surface into disposable homes and
  proves what a real client lists, against the first subject (CPP's native
  Codex skills).
- **Independent grading and adversarial evaluator controls** (#9): the
  disposable-copy verifier and result assembler (`skillc/verify.py`).
- **Controller-owned trial accounting and artifact capture** (#8): the
  population planner and capture controller (`skillc/trial.py`).
- **The Level 1 slug-fix goal and a proven grader** (#5): the first
  independently-checkable goal-based task, with a certified grader and its own
  broken-grader controls.
- **Version 2 of all four evaluation record contracts** (#4), later joined by
  `attempt-lifecycle` (#8): the installation receipt, trial ledger, artifact
  manifest and verified result, each with discriminating rule controls under
  `skillc check-records`.
- **`ref-depth` counts a back-link to `SKILL.md` or an already-linked sibling
  as ordinary, not a deeper chain** (#52), and reports every distinct chain,
  not just the first.
- **`trigger-shape` stays silent on a user-invoked skill under
  `--target claude-code`** (#51): the model cannot fire a skill declaring
  `disable-model-invocation: true`, so the premise the rule warns under does
  not hold for that client; `--target portable` is unchanged. `skillc
  selftest` itself became target-aware to prove this (`controls/<rule>/
  targets/<target>/`).
- **Frontmatter types, a documented YAML subset, and target-scoped field
  rules** (#3): `name`/`description` must be strings; `--target portable`
  (the Agent Skills specification) vs. `--target claude-code` (plus its
  documented extensions).
- **`skillc selftest` refuses an empty, unparsed or misattributed control, and
  an unknown `--rule`** (#2): a rule with no committed control is `UNPROVEN`,
  not silently passing.
- **A pinned research trail**: provenance notes and adopted-concept maps for
  [Coder Eval](docs/research/coder-eval-lessons.md) (#6),
  [config-drift-checker](docs/research/config-drift-checker-lessons.md)
  (#38, #40), and [mattpocock/skills](docs/research/mattpocock-skills-lessons.md)
  (#49), each naming the pinned commit and licence per
  [ADR 0003](docs/decisions/0003-no-external-evaluation-runtime.md) (ideas,
  never code).

### Fixed

- A non-boolean criterion `mandatory` flag is refused, not silently dropped
  from the derivation (#37).
- `tests/` is inside `mypy`'s scope, with a control that plants a type error
  there and requires it reported (#19).
- The fixture pin is computed without needing a `git` binary at import time
  (#5 follow-up).

### CI / process

- Woodpecker gate (`selftest`, `pytest`, `ruff`, `mypy`) with its own negative
  control (#18), a gitleaks secret scan with a negative control (#43, #47),
  and now `leak-check` (#63) and this changelog gate (#73), each proven able
  to report the failing verdict, not only the passing one.

## [0.1.0] - 2026-09-15

The static checker: `skillc check`, `skillc selftest`, `skillc rules`. Every
rule ships a committed redcase (ADR 0001) and `skillc selftest` proves each one
can still report the other verdict. Tagged retroactively at
[`d99ed0c`](https://github.com/cooneycw/skillc/commit/d99ed0cab3c1988a5079c34f6f9d57d63e570ea7)
on 2026-09-26, the last commit before the evaluation-facility work began - see
[the v0.1.0 release](https://github.com/cooneycw/skillc/releases/tag/v0.1.0)
and [#72](https://github.com/cooneycw/skillc/issues/72).
