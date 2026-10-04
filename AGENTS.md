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
- `skillc/verify.py` - the independent verifier and result assembler: grades a disposable
  copy of the frozen artifacts in a contained probe, then a trusted judge, and derives
  the result; see [verification spec](docs/specs/evaluation-facility/verification.md)
- `skillc/judge.py` - the grading-tier judge seam (#69): a stdlib-only `Judge` Protocol,
  schema-constrained output validation, per-tier availability, the leak-check on judge
  input, and the same-model-vs-independent disagreement record; `FakeJudge` is what
  every test in this module's own PR uses - see [ADR 0006](docs/decisions/0006-grading-tiers.md)
- `skillc/judge_mcp_second_opinion.py` - the real `mcp-second-opinion` `Judge` adapter
  (#69 follow-up): speaks MCP to the server as an external process (stdlib `subprocess`
  plus stdio JSON-RPC, no SDK); every one of its own tests drives the committed fake
  server below instead, enforced by an AST-walk structural test
- `tests/fixtures/mcp-second-opinion/fake_server.py` - a committed fake MCP stdio server
  (`happy`/`garbage-handshake`/`hang`/`tool-error`/`unparseable-verdict` modes) that
  `skillc/judge_mcp_second_opinion.py`'s own tests drive instead of a real judge
- `skillc/trial_bootstrap.py` - the per-trial home, onboarding seed, MCP config,
  invocation and skill+tool liveness canary a live agent needs to actually start and
  work inside a Docker trial, independent of which `ExecutionBackend` runs it; see
  [trial-bootstrap spec](docs/specs/evaluation-facility/trial-bootstrap.md)
- `docker/trial/` - the pinned trial image (`Dockerfile`, `pinned-versions.json`,
  `check_pins.py`) that `skillc/trial_bootstrap.py`'s composed home/seed/invocation runs
  inside
- `skillc/cost_estimate.py` - pre-spend cost projection and the spend gate (`authorize`):
  ADR 0005's cost stop, made structural rather than a convention (#26)
- `skillc/cli.py` - `check`, `check-records`, `selftest`, `rules`, `materialize`
- `controls/<rule-id>/{bad,good}/` - the committed redcases
- `evals/` - behavioural evals; see `evals/README.md`
- `evals/selection-probe/` - three predeclared cases probing native skill selection
  (#26): case identities and allowed choices published before any attempt runs,
  planned through the real controller, and a cost-estimate run manifest computed
  and asserted equal to the code that produces it - no live attempt has run
- `evals/matched-pilot/` - the first bounded matched pilot's predeclared experiment
  record and cost estimate (#12), reusing `skillc/cost_estimate.py` rather than a
  second estimator, and its live evidence (`evidence/`: 6 attempts, run 2026-09-27)
- `skillc/matched_pilot.py` - `skillc pilot-run`/`pilot-report`: runs the predeclared
  pilot schedule (pins checked, caps enforced), reconciles every planned attempt, and
  publishes a leak-checked, record-checked `pilot-report` bundle
- `skillc/calibration.py` - #204's symmetric primary endpoint (the task grader's criteria,
  never `installation-ready`, which a baseline arm cannot satisfy) with readiness reported
  beside it, and the two- or three-arm (B/N/P, #231) calibration declaration validator (`require_approved` refuses
  an unapproved one)
- `skillc/calibration_run.py` - `skillc calibration-run` (#207): runs an APPROVED calibration declaration
  (refused before anything exists otherwise) in its seeded arm order through one attempt path, the
  arms differing only in what is installed; pins the model via `matched_pilot.pin_model_argv`, enforces
  the caps and reconciles through `matched_pilot`, and reports `primary_endpoint` with readiness beside it.
  Evidence stays private; nothing is exported
- `evals/calibration-204/` - the two-arm calibration predeclaration (not approved, not run)
- `evals/calibration-203/` - the three-arm B/N/P calibration predeclaration for #203 on `gate-ran-nothing` (approved and run 2026-10-03; report: REDESIGN)
- `evals/calibration-203-low/` - #203 Q2 step (a): the calibration-203 identities at reasoning effort low, B and N, 3 each (run 2026-10-04: still at ceiling, 6/6)
- `evals/calibration-203-c3/` - #203 Q2 step (b): B/N/P on `helper-different-question`, 6 each (approved 2026-10-04, not run)
- `evals/level3/helper-different-question/` - #203 candidate 3 (#242): a clean merge left two Step 5
  sections and the shipped helper truthfully prints INTACT; graded from files, certified by `qualify.py`
- `evals/level3/slugkit-pipeline/` - Level 3 task with a local `ci/verify.py` pipeline the
  agent must keep passing and honest; its grader plants mutations and `qualify.py` proves
  them valid
- `evals/level1/<task>/` - a goal-based task: pinned fixture, public `goal.md`, a grader
  (`grader.json`: probe, inputs, judge), reference/alternative/wrong candidates and a
  `qualify.py` gate that must refuse broken graders
- `evals/subjects/<subject>/` - a declared subject (`subject.json`, `SUBJECT.md`) and the
  evidence `skillc materialize` produced for it
- `tests/fixtures/codex-subject/` - a two-skill collection and `fake_codex.py`, a stand-in
  client for CI, which has neither git nor Codex
- `tests/fixtures/trial-subject/fake_subject.py` - a deterministic subject that works, crashes,
  hangs, leaves children running or forges records, for the controller tests

## Verify

```bash
make verify
```

Installs the `dev` extra (`ruff`/`mypy`/`pytest-timeout` live there, not in
the base dependencies - a bare `uv run mypy` in a fresh worktree fails with
`Failed to spawn: mypy` without this) and then covers EVERY step
`.woodpecker/ci.yml` runs, not only its `gate` and `negative-control` steps -
`tests/test_ci_local_gate_coverage.py` fails when a new CI step has no
target here, so this list cannot silently fall behind the workflow file the
way it did once (#156: PR #155 went red on `changelog-check`, which no local
gate ran):

- `skillc selftest`, `pytest -rA`, `ruff check .`, `mypy` (the `gate` step)
- `ci/negative-control.sh` (the `negative-control` step)
- `ci/typecheck-control.sh` (the `typecheck-control` step)
- `skillc leak-check .` with CI's exact `--exclude` set, then
  `ci/leak-check-control.sh` (the `leak-check` step)
- `python3 ci/changelog_check.py origin/main`, after fetching it (the
  `changelog-check` step)
- `python3 ci/readme_drift.py` (the `readme-drift` step)
- `gitleaks dir . --config .gitleaks.toml --redact --no-banner`, then
  `ci/secret-scan-control.sh` (the `secret-scan` step) - **skipped locally**,
  loudly, when gitleaks is not installed; CI always runs it, a missing local
  scanner is not evidence of no secret, and the pre-push hook below still
  catches it before anything reaches GitHub.

A green gate is only evidence while every one of these steps can still go
red - `ci/negative-control.sh` and `ci/typecheck-control.sh` are two of the
committed proofs that they can. Equivalent without `make` (the `gate` and
`negative-control` steps only; see the Makefile for the rest):

```bash
uv sync --locked --extra dev && uv run skillc selftest && uv run pytest -rA \
    && uv run ruff check . && uv run mypy && uv run bash ci/negative-control.sh
```

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

`ci/clean-install-check.sh` builds a wheel and installs it into a fresh, clean
`uv venv` to prove the checker's own installation (#27): `skillc selftest`
correctly refuses without its packaged redcases (`controls/` is fixture data
and is not shipped), correctly certifies when a fresh copy of them is
supplied, and `skillc check` still matches the source checkout's own verdict
on a known-bad/known-good pair after packaging. Retains a build/install
identity record (wheel digest, versions, source commit - logical values only,
issue #63) and carries its own committed negative control
(`CLEAN_INSTALL_CONTROL=neuter-installed-rule` or `=delete-scratch-controls`).
Not wired into Woodpecker - the build+venv round trip is slower than the four
gates above, and #27's own scope excludes CI expansion - so run it by hand:
`bash ci/clean-install-check.sh`. Details: [docs/findings.md](docs/findings.md).

`leak-check` refuses a tree or a produced bundle that carries a machine
identity - a home-directory path, a `uid=`/`gid=` number, a private (RFC 1918)
IPv4 address, a hostname from a locally-configured deny-list (issue #63,
never committed with real names), or the scanning process's own live
home/cwd (`leak.default_host_paths`, issue #134 item 5 - catches a checkout
under `/workspace`, `/opt`, `/srv` or anywhere else the home-path pattern
does not recognize). `skillc leak-check .` runs in CI over the checked-out
tree, and `ci/leak-check-control.sh` proves it against the seeded fixture in
`controls/leak-check/bad/`. What it cannot see is stated in
`skillc/leak.py`'s module docstring - absence of a finding is not proof of
absence.
