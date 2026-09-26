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

- **The fake `docker` CLI's state-file writes are now atomic and locked**
  (Refs #77): `test_execute_cancellation_kills_the_container` flaked on
  main at roughly 1 in 25 runs. Root cause: `tests/fixtures/docker-backend/
  fake_docker.py` rewrote each container's state file in place
  (`path.write_text(json.dumps(...))`), which truncates the file before the
  new bytes land; `kill` and a concurrently running `exec`'s own background
  write could race a separate `inspect` invocation's read, which then saw a
  torn or empty file, raised `JSONDecodeError`, and exited nonzero without
  the "no such object" message - `DockerBackend._inspect_status` correctly
  read that as UNKNOWN rather than guessing CONFIRMED, so the product code
  was honest and the fixture was racy. Every state write now goes through
  `_atomic_write_json` (temp file in the same directory, then
  `os.replace()`, atomic on POSIX) and, where a write is a read-modify-write
  (`kill`'s status flip, `exec`'s own `finally`), `_rewrite_state` under an
  exclusive per-name file lock, mutating whatever is CURRENTLY on disk
  rather than a stale in-memory snapshot - so a status flip to `"exited"`
  can never be silently overwritten back to `"running"` by a write that
  started earlier but finished later. Evidence: a 100-run stress loop of
  the flaky test found 4 failures on the pre-fix fixture and 0 after.
- **The no-project-name-branch genericity guard is now an open set, not a
  closed allowlist** (Refs #11): `tests/test_materialize.py`'s
  `CORE_MODULES` was a hand-maintained tuple that predated the Docker
  backend and everything built on it, so a real module could land - and
  five did (`docker_backend.py`, `reap.py`, `trial_bootstrap.py`,
  `cost_estimate.py`, `exposure.py`, plus `judge.py` from a sixth,
  concurrent PR) - with no test noticing it was unguarded. The guard now
  scans every `skillc/*.py` file by discovery (`sorted(Path("skillc")
  .glob("*.py"))`) minus a `GENERICITY_EXEMPT` dict requiring a stated
  reason per entry - empty today, since every current module is already
  clean. A committed test refuses a stale exemption naming a file that no
  longer exists, with its own negative control. Verified by hand: dropped a
  brand-new module containing a planted subject literal into `skillc/`
  outside any list, confirmed the guard caught it unprompted, then removed
  it and confirmed clean again - proving the OPEN-set claim, not just the
  AST scan's own logic (already proven).
- **The failure-path matrix and trustworthy cleanup** (#79, Refs #10):
  [`docs/specs/evaluation-facility/failure-matrix.md`](docs/specs/evaluation-facility/failure-matrix.md)
  states all ten of #10's addendum failure paths through the real driver
  (`lifecycle.run_through_backend`), each with a citation to the test that
  proves it. Writing the table found and closed a real gap: `destroy()` or
  `confirm_absent()` itself RAISING (not merely returning `NOT_CONFIRMED`/
  `UNKNOWN`) used to propagate out of the driver before `trial.finalize()`
  ever ran, leaving the attempt with no lifecycle record at all - both calls
  are now individually caught, folding into `backend_teardown="unknown"`
  plus a new `backend_teardown_error` string, confirmed to reproduce on the
  pre-fix code before the fix. New `skillc/reap.py`: label-scoped container
  reaping (`docker ps --filter label=...` only, never a name match - a
  foreign look-alike is structurally unreachable to it), where an unreachable
  daemon reaps nothing and reports every requested attempt `left-running`
  (UNKNOWN never reaps); resource snapshots that flag BOTH an unexpected
  leak of an owned container and an unexpected disappearance of a foreign
  one; and declared-host-path digests before/after, with the limitation
  (regular files only, nothing outside the declared list) stated in both the
  doc and a passing test. The fake `docker` CLI
  (`tests/fixtures/docker-backend/fake_docker.py`) gained `ps`, `--label`
  capture on `run`, and a per-container id to make this provable without a
  daemon; the real daemon boundary remains owed to the operator's live run
  (#10), as it does throughout this codebase's Docker-backend work.
  Cross-model review found one HIGH (`reap()` acted and confirmed by NAME,
  which a container removed and replaced under the identical name between
  its list/remove/re-list round trips could defeat - fixed by acting on
  container IDs instead, unique per container instance) and five MEDIUM
  findings: an empty attempt population silently reported
  `daemon_reachable=True` having checked nothing (both `reap()` and
  `snapshot_host_paths()` now refuse it); an unreadable host path collapsed
  into the same `None` as confirmed absence (now a distinct `UNREADABLE`
  state, reported `unresolved` rather than silently `unchanged`); and a
  declaration added or removed between two host-path snapshots was invisible
  because a missing dict key defaulted to the same `None` used for confirmed
  absence (now compared against a distinct not-declared sentinel). All fixed
  with committed regression tests confirmed red on the pre-fix code first.
  A subsequent orchestrator review found one more: `reap()`'s outcome
  vocabulary conflated `unknown` (the daemon could not be asked) into
  `left-running` (the daemon confirms something is still there) - a fourth
  outcome, `unknown`, now keeps the two distinct, with its own regression
  test confirmed red on the pre-fix commit.
- **`skillc exposure`, a rung-2 exposure check with planted markers**
  ([ADR 0004](docs/decisions/0004-evaluate-the-exposed-knowledge-surface.md),
  #55): measures what actually reaches a client's rendered session-start
  input, per client, with no model call - never what the author's files
  merely declare. A surface declaration extends `subject.json` with
  `always_loaded` (instruction files, each with an optional
  `claimed_limit_bytes`) and `index` (an on-demand file naming `targets`);
  the skill-listing layer reuses `materialize.py`'s own Subject/inventory/
  install/canary machinery wholesale. Every declared item reports `EXPOSED`,
  `TRUNCATED` (with the real cut point, never a bare pass/fail against a
  predicted one), `HIDDEN` (with a `policy` cause when known - verified
  empirically against codex-cli 0.157.1 that `agents/openai.yaml`'s
  `policy.allow_implicit_invocation: false` excludes a skill from the
  listing entirely), or `UNMEASURED` (a blind render reports every declared
  item this way, never an empty list - "nothing checked" and "checked but
  unobservable" are different facts). A marker whose text collides with
  ambient text (the checkout path, the disposable home, a skill's own
  description, or another marker) refuses the whole run rather than produce
  an untrustworthy verdict - found by this PR's own test suite to have a
  real gap in its first draft (an ambient string EQUAL to a marker's text
  was excluded from the comparison instead of being the clearest case).
  Claude Code has no supported model-free render command identified
  (`claude --help`, 2026-09-26) and reports `UNMEASURED` by declaration.
  Evidence published against the real `codex-cli 0.157.1`: mattpocock/skills
  (pinned, as in #11 - skill-listing layer only) and a synthetic surface
  built to exercise all three layers together
  (`evals/subjects/exposure-synthetic/`) - which honestly reports that the
  real client did not truncate `AGENTS.md` at the claimed boundary tested,
  contradicting ADR 0004's original ~25 KB observation, and that a declared
  index file is not auto-surfaced at all unless something actually loads it.
  Refs #55, not Closes: the Claude Code arm's `UNMEASURED` status means the
  acceptance is not fully met without a paid call.
- **The grading-tier judge seam** (Refs #69): `skillc/judge.py` adds a
  stdlib-only `Judge` Protocol for the same-model and independent tiers
  (ADR 0006), schema-constrained output validation (`parse_judge_verdict`
  refuses a malformed field outright - a malformed criterion becomes
  `UNKNOWN` with a stated reason, never the whole tier), per-tier
  availability (`JudgeUnavailable` makes only that tier `UNAVAILABLE`, with a
  reason, never a silent drop), the leak-check on judge input before either
  judge is ever called (`check_judge_input`, #63 - a leak is a refusal to
  grade at all, not a tier-level unavailability), and the per-criterion
  same-model-vs-independent disagreement record (`compute_disagreement`,
  unavailable until both tiers report a real verdict). `FakeJudge` is the
  only implementation shipped - #69's own acceptance forbids a real model
  call in the test suite. `skillc/verify.py`'s `grade()` gains an optional
  `judges`/`goal_text` parameter wired into `verification.tiers_enabled`/
  `verdicts`/`disagreement`; passing neither leaves `grade()`'s behavior
  unchanged. The real `mcp-second-opinion` adapter and the cost-estimate
  extension for its paid calls are a follow-up PR, kept separate to stay
  reviewable. A `/codex:code_review` pass found and fixed four issues before
  push: the leak-check scanned only file content, missing filenames and
  criterion ids also transmitted to a judge; a malformed `missing` field was
  silently discarded on a `SATISFIED`/`VIOLATED` entry instead of refusing
  the whole response; two responses for one criterion let response ORDER
  decide the grade (last-wins) instead of both being refused as ambiguous;
  and `judges={"deterministic": ...}` could silently overwrite the
  deterministic tier's own verdict, now refused before any grading starts.
- **Conformance through the real adapter, a no-Docker proof, and a published
  support matrix** (#80, Refs #10): interfaces.md's "Conformance cases
  required before trusting a backend" table, restated with a
  demonstrated-here / demonstrated-elsewhere / owed-to-live-run status and a
  concrete citation for every row (`tests/test_docker_conformance.py`'s
  `CONFORMANCE_CASES`, republished in
  [`docs/specs/evaluation-facility/support-matrix.md`](docs/specs/evaluation-facility/support-matrix.md)).
  The backend-owned cases run through the REAL `DockerBackend`, not an
  isolated helper - against the fake `docker` CLI, CI's own Docker-shaped
  green. `tests/test_no_docker_required.py` proves `skillc check`/`selftest`
  need no Docker at all: a committed redcase
  (`imports_docker_backend_at_load.py`) proves the "no static command
  imports the Docker backend at load" check itself can report the other
  verdict, and a positive control proves a Docker-stripped PATH actually
  makes `docker` unreachable before trusting the green run that follows.
- **Per-tier verdicts as a keyed collection, not one field** (Refs #69, Refs
  #10): a fresh owner ruling on #69 superseded #76's single
  `verification.grading_tier` before any real trial record ever carried it.
  Every result now records `verification.tiers_enabled` (which tiers were
  requested) and `verification.verdicts` (an object keyed by tier name, each
  entry with its own `status`/`criteria`/`backend`), never averaged or
  overridden across tiers; `verification.disagreement` is reserved, always
  `{"available": false, "reason": "fewer than two judge tiers"}` until a
  second tier exists to compare against. The top-level `status`/`criteria`
  are unchanged and, stated explicitly now, come from the deterministic tier
  alone. `check-records`' new `verdict-tiers` rule checks BOTH directions
  (orchestrator review found the first cut checked only one): a verdict
  entry for a tier absent from `tiers_enabled` is refused, and so is an
  enabled tier with no entry at all - an unavailable judge writes its own
  `UNAVAILABLE` entry with a stated reason, never a silent absence. Not a
  new envelope version: nothing outside this build's own tests ever
  produced or read the field it replaces.
- **The matched pilot's predeclared experiment record, evidence-report
  schema and cost estimate** (Refs #12, planning only - no paid run):
  `evals/matched-pilot/` predeclares the first bounded matched pilot's exact
  model/client/subject identities (the image digest is named explicitly as
  owed to the live build, never invented), goal population (the
  already-qualified `slug-small-fix` grader, #5), treatment-vs-baseline
  definition, repeat schedule (3 repeats x 2 arms = 6 attempts), arm order,
  time/monetary caps (the same $5 operator ceiling #26 uses) and stated
  clarification/approval behavior, planned through the real controller
  against a throwaway store. Reuses `skillc/cost_estimate.py` unchanged - no
  second estimator - with the same sensitivity lines ($0.675 at the stated
  assumption, $4.05 at 500k input tokens/attempt, $7.80 - over the ceiling -
  at 1M). `skillc/records.py` adds a new `pilot-report` record kind: the
  evidence report #12's acceptance requires (per-attempt disposition,
  per-criterion outcomes, uncertainty, intervention counts, and a cost/time
  split into setup/agent/grading with missing values explicit, never a
  silently absent key), with its own record-shape rule and a
  `ledger_binding` completeness check refusing a report that omits a
  scheduled attempt or names one the ledger never planned - the committed
  control #12's acceptance names by name. No paid model call, live agent,
  image build or report generator exists anywhere in this work; the
  manifest's `execution` stays `"incomplete"` pending an approved budget.
- **The Docker backend's implementation** (Refs #77, Refs #10, on top of the
  interface above): real bodies for `prepare`/`install`/`execute`/
  `confirm_stopped`/`export`/`destroy`/`confirm_absent`, all through the
  `docker` CLI. One persistent container per attempt (`docker run -d` at
  `prepare()`, acted on afterward via `docker cp`/`docker exec` - never a
  bind mount, a shared volume or a second container), running as the fixed
  `10001:10001` candidate user. `confirm_stopped()`/`confirm_absent()` return
  `Confirmation.UNKNOWN` whenever the daemon cannot be asked at all, and a
  cleanup sweep must never reap on that answer. Proven here only against a
  fake `docker` CLI (`tests/fixtures/docker-backend/fake_docker.py`, extended
  with `exec`/`kill`/`cp`/detached `run`); the real daemon boundary remains
  owed to the operator's live run (#10). Rests on PR #83 (merged as `2fcf6a5`
  on `main`), which landed the interface this builds on.
- **The case format, `case.observes_selection`, and #39's last control**
  (Refs #26 - its no-run part; Closes #39): a trial ledger's `case` identity
  gains an optional boolean, `observes_selection` - type-checked at plan
  time (`skillc/trial.py`'s generalized `_OPTIONAL_IDENTITY`) and again on
  any already-written ledger (`skillc/records.trial_ledger`). Declaring it
  `true` makes the `skill-invocations` observation stream (#39) REQUIRED for
  that trial's attempts, not merely optional - its absence is now refused by
  `skillc/records.ledger_binding`, closing the one control #39 deferred to
  this issue. `skillc/cost_estimate.py` adds a pre-spend cost projection and
  the spend gate (`authorize`) ADR 0005 rule 5 requires: a live run may
  proceed only with an approved budget at or above the estimate, and
  separately never above the operator's own $5 ceiling for the whole run
  (relayed via master, 2026-09-26) regardless of any larger approved budget.
  `evals/selection-probe/` publishes three predeclared cases (intended use, a
  near miss, an overlapping choice), each planning BOTH matched arms
  (treatment/baseline) as its own trial and reusing the already-qualified
  `slug-small-fix` grader (#5), planned through the real controller against a
  throwaway store, with a committed run manifest (6 attempts, $0.675
  estimated) whose every published number is asserted equal to what the code
  computes. A `/codex:code_review` pass found and fixed four issues before
  push: the estimate originally priced only the treatment arm, omitting the
  baseline's own paid attempt; `authorize` accepted a NaN/infinite budget
  (a `<` comparison against NaN is always False); `estimated_usd` was rounded
  before authorization, letting a tiny positive cost round down to a
  budget-of-$0 pass; and the manifest-consistency test checked only the
  final dollar figure, not the published price/token assumptions it was
  computed from. No paid model call, live agent or image build happens
  anywhere in this work; the manifest's `execution` stays `"incomplete"`
  pending an approved budget.
- **The Docker backend's interface** (Refs #77, sub-issue of #10):
  `skillc.docker_backend.DockerBackend`'s constructor/config, `describe()`'s
  claims, the composed `docker run` argv (`compose_run_argv`, a committed
  control surface - no socket mount, no bare `-e NAME`, matched
  `--memory`/`--memory-swap`, a literal `--` before the image, per-trial
  ownership labels, an opt-in disk bound), and the handle shape. The
  candidate user is a fixed, host-independent uid:gid (`10001:10001`), never
  the host caller's own - the container's own `id`, file ownership and
  transcripts would otherwise carry a piece of the host's real identity.
  The follow-up implementation PR above fills in every lifecycle method
  beyond `describe()`.
- **Trial image and per-trial agent bootstrap** (#78, Refs #10):
  `skillc/trial_bootstrap.py` composes a private per-trial home owned by a
  fixed `candidate` (10001:10001) identity, an onboarding seed bound to
  exactly one project and the exact CLI version about to launch, never
  auto-answering anything outside the documented interactive gates, a
  per-trial MCP config declared rather than inherited, a client-aware
  invocation (`--name` only where the pinned CLI actually supports it,
  never `--remote-control`, `GIT_TERMINAL_PROMPT=0` with no silent
  override), and a liveness canary requiring the transcript to show both a
  skill invocation and a tool use whose CONFIRMED output - never merely its
  request - carries a per-attempt nonce. `docker/trial/Dockerfile` pins the
  Claude Code and Codex CLI versions (`docker/trial/pinned-versions.json`,
  checked against the Dockerfile by `docker/trial/check_pins.py`, which
  derives each required pin from the manifest rather than a second
  hand-maintained mapping), verifies `codex-code-mode-host` lands beside the
  REAL native `codex` executable via Node's own module resolution
  (`docker/trial/verify_codex_sidecar.js`) and that no `docker` binary is
  reachable, and records a deliberate unsandboxed choice for Codex
  (`BWRAP_DECISION`). A `/codex:code_review` pass found and this PR fixed
  seven issues before push, several confirmed against the pinned CLIs'
  actual packaging and source. Consumed by `skillc/docker_backend.py` (#77);
  the image build itself and whether a real CLI starts un-wedged remain owed
  to a live Docker run (see `docker/trial/README.md`).
- **`skillc.verify` grades a probe through an `ExecutionBackend`, with a
  deterministic grading tier and a provenance stamp** (Refs #10): `grade()`/
  `grade_files()` accept an optional backend for stage 1 (the untrusted
  probe) - `None` keeps today's bare-subprocess path unchanged; stage 2 (the
  trusted judge) never changes either way. Adds `skillc/provenance.py`
  (`skillc_version`, source commit and dirty state, stamped from the
  package's own version - see `#73` above).
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
- **The `mcp-second-opinion` `Judge` adapter and its cost-estimate wiring**
  (Refs #69, the seam PR's follow-up): `skillc/judge_mcp_second_opinion.py`
  implements `skillc.judge.Judge` against a real
  [`cooneycw/mcp-second-opinion`](https://github.com/cooneycw/mcp-second-opinion)
  server, speaking MCP as an external process - stdlib `subprocess` plus
  line-delimited JSON-RPC 2.0 over stdio (the `initialize` handshake,
  `notifications/initialized`, one `tools/call`), no MCP SDK, matching
  `skillc/docker_backend.py`'s own precedent for an external tool with no
  vendored client library. An absent binary, a failed handshake, a timeout,
  or a tool-level error each become `JudgeUnavailable` with a stated reason;
  an unparseable verdict becomes `[]`, which `run_tier` turns into an honest
  per-criterion `UNKNOWN`, never a crash. The real tool's own schema
  (`get_code_second_opinion`: `code`/`language` required,
  `additionalProperties: false`, no field for a structured criteria list) is
  respected rather than worked around: the criteria ids are embedded as a
  JSON array literal inside `issue_description`, and the first JSON array of
  objects is parsed back out of the free-text response. Every one of its own
  tests drives a committed fake MCP stdio server
  (`tests/fixtures/mcp-second-opinion/fake_server.py`,
  `happy`/`garbage-handshake`/`hang`/`tool-error`/`unparseable-verdict`
  modes) instead of a real server - #69's own acceptance forbids a real model
  call in the test suite, now enforced structurally by an AST-walk test that
  refuses any `McpSecondOpinionJudge(...)` construction in the whole test
  suite that omits an explicit `command=` override, with its own planted-
  offender negative control. `skillc/cost_estimate.py`'s `estimate()` gains
  `judge_tiers_enabled` (0, 1 or 2), `judge_price` and per-call token
  assumptions: `judge_tiers_enabled=0` (the default) reproduces the
  function's pre-adapter behavior byte-for-byte, and enabling judge tiers
  adds paid calls into the same `estimated_usd` `authorize()` already checks
  against the $5 ceiling (ADR 0005) - a committed control shows a plan
  comfortably under the ceiling without judges crossing it once two judge
  tiers are enabled, refused in exactly that configuration and no other.
  Still owed: the judge does not yet run inside #10's grading boundary (a
  separate backend instance) - it spawns directly on the host today, bounded
  only by ordinary OS-level process isolation.

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
