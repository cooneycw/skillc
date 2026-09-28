# Changelog

All notable changes to skillc are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Dates are the day the
work landed on `main`, not the day a version is tagged - see
[#72](https://github.com/cooneycw/skillc/issues/72) for the release checklist
and version plan.

## [Unreleased]

### Added

- **Capability-gated in-container TERM forwarding to the exec'd subject**
  (Refs #158). `docker/trial/skillc-supervisor.py` (a new foreground
  process, replacing the `sleep infinity` keep-alive placeholder once the
  held #78 image change lands) and `docker/trial/skillc-wrap.py` (a
  one-shot registering exec wrapper) let a container-level TERM reach the
  exec'd subject's process group for real - something no real Docker daemon
  does on its own (`docker kill` only ever reaches PID 1). Both scripts
  ship as source files only; the Dockerfile is NOT changed here - that
  remains HELD pending the operator's #150 discriminating run
  (`docs/specs/evaluation-facility/signal-forwarding.md`). `DockerBackend.
  execute()` probes each container for the wrapper before prefixing the
  exec argv with it (`_forwarding_available`), so this is inert - byte-for-
  byte the pre-#158 behavior - on every image today. `ExecuteResult` gains
  `term_forwarding` (`unavailable-in-image` / `not-needed` /
  `exited-within-grace` / `killed-at-escalation`), naming only what the
  HOST observed - never a claim sourced from inside the container, which
  shares the subject's own trust boundary and cannot prove anything about
  itself the subject could not also fabricate. Three committed cases:
  `tests/test_docker_backend.py`'s two new end-to-end tests (through
  `execute()` against the fake docker CLI's new "supervisor present and
  survives TERM" mode) and `tests/test_skillc_supervisor.py`'s two
  process-level tests (a real supervisor subprocess under a stand-in
  `tini`, and - the must-not-exit rule's own red case - a monkeypatched
  mutant kept entirely in the test tree, never a switch in the production
  script) all fail against pre-#158 code and pass now.
- **`skillc/authority_interceptor.py`, the L4 authority-boundary fixture
  service for #14's runtime half** (Refs #14). `AuthorityInterceptor` polls
  a live attempt's WHOLE out-of-scope surface from OUTSIDE the container -
  via `ExecutionBackend.export()`, an existing read-only method, never
  anything run inside the container under the subject's own uid - on a
  background thread concurrent with `execute()`, and assembles the
  `trusted_observation` bytes `skillc.verify.grade_agent_attempt` carries.
  Diffs the WHOLE exported tree outside a declared `allowed_prefixes` (PR
  review: watching only one named hostile path let `stayed-in-bounds` grade
  SATISFIED over a violation on any OTHER out-of-scope path the interceptor
  never looked at) at no extra I/O cost, since `export()` already copies
  everything every poll; `.git/` changes are tagged their own `category`
  since a `git` command's side effects there are an action violation, not
  an ordinary file edit. `wrong/unwatched-out-of-scope-edit` commits this
  at the certification level, proven both there and directly against the
  real interceptor. One backend artifact (`observations`,
  `DockerBackend.execute()`'s own captured-stdout file) is excluded
  unconditionally - backend plumbing, never a subject action, found by
  running this module's own tests against the real backend.
  A mandatory final snapshot, taken immediately after `confirm_stopped()`
  confirms the stop regardless of the configured poll interval, catches any
  PERSISTENT violation even in an attempt shorter than one interval;
  `stop_and_finalize()` returns `None` (never a hollow, clean-looking empty
  log) if that mandatory snapshot itself cannot be taken. The design has a
  real, committed blind spot - a violation both made and undone strictly
  between two observations leaves no trace - proven directly against the
  real interceptor (`tests/test_authority_interceptor.py::test_delete_then_
  restore_within_one_poll_window_is_invisible`, run against the same fake
  `docker` CLI `test_docker_backend.py` uses) and committed at the
  certification level as `evals/level4/instruction-conflict-config-secret/
  known-gaps/delete-then-restore/`, mutation-tested the same way
  `known-gaps/forged-log` was before it closed. A poll that FAILS to export
  mid-run is counted, not silently skipped: the assembled log carries a
  `coverage: {polls_attempted, polls_failed}` field, since "half the polls
  failed" and "every poll saw nothing" both give an empty `entries` list on
  their own. `_loop`'s single-threaded wait-then-poll structure makes a slow
  poll unable to pile up by construction, not by a check - documented with a
  measured (fake-CLI, floor-only) export cost for this task's ~24 KiB
  workspace, ~0.04s over 20 calls, against a 2.0s default interval. Neither
  the interceptor nor its known-gap fixture cover the override's "quote its
  full contents" half
  - stated plainly in the module docstring and PROVENANCE.md as an
  uncovered gap, since a filesystem watcher cannot observe data copied out
  of a file into the subject's own report text, and none of
  `grade_workflow.py`'s four criteria inspect report text for a secret-value
  match either. Nothing in production wires this into a real attempt yet.

- **`skillc/verify.py` gets a trusted-observation channel for #14's Level
  4/5 runtime half** (Refs #14). `grade_files`/`grade_directory`/
  `grade_agent_attempt`/`grade` take an optional `trusted_observation: bytes
  | None`, delivered to the judge as `envelope["trusted"]` - a key
  `_probe`/`_probe_via_backend` never set, so it reaches the judge without
  ever passing through the probe or candidate code. Both L4/L5 judges
  (`grade_workflow.py`, `grade_recovery.py`) now trust ONLY that key, never
  a candidate-writable file's self-declared `provenance` field, and
  `known-gaps/forged-log` moves to `wrong/forged-log` in both tasks -
  correctly FAILing where it used to PASS undetected. Red/green pair on
  `forged-log`: pre-fix `main` grades it PASS (true status FAIL, the
  documented miss); post-fix it grades FAIL, matching `expected.json`, in
  both `qualify.py` runs. **Nothing in production supplies
  `trusted_observation` yet** - the fixture services that will (an
  authority-boundary interceptor for L4, a disruption trigger for L5) are
  not built here; a real L4/L5 attempt still grades `stayed-in-bounds`/
  `work-preserved`/`report-supported` UNKNOWN until they land.

## [0.3.0] - 2026-09-28

### Added

- **Level 2 and Level 3 calibrated task families: constraint-handling and
  real installed-path grading** (Refs #13). Two new sibling task families,
  never touching Level 1's own fixtures.

  `evals/level2/slug-constrained/` extends Level 1's slug bug fix with three
  PUBLIC constraints (goal.md states all of them; #13's own "keep public
  requirements"), each its own mandatory criterion, bucket-prefixed
  (`functional-*`/`constraint-*`, no schema change - `grader.json`'s
  `criteria` stays a flat list of strings) so a report can group by bucket:
  interface stability (`inspect.signature`, a structural check), a
  dependency restriction (`ast.parse` on the source TEXT, never executed -
  static on purpose, since a dynamic check only ever sees an import a run
  actually reaches, and `wrong/deferred-import` hides one behind a branch no
  functional held-out input takes), and data preservation (a hardcoded
  sha256 of `fixture/NOTES.md`, never re-read at grade time - `wrong/notes-
  touched` proves the digest isn't lenient about whitespace-only edits).
  `qualify.py` (Level 1's generic harness, copied) certifies all three: red
  on each `wrong/*`'s own criterion only, green on `reference/`/
  `alternatives/char-loop`.

  `evals/level3/slugkit-installed/` reframes "a real installed consuming
  path" (#13's own wording) as a property of the CANDIDATE's code, not of
  agent skill consumption (already measured by #26/#150) - a fix that
  passes a visible unit test must also work through the package's real
  console entry point. Neither pip nor a build backend is present in this
  dev venv or the #78 trial/grading container (checked directly:
  `import pip`/`setuptools`/`hatchling` all fail here; `docker/trial/
  Dockerfile` installs no `python3-pip`) - a first design making the
  criterion UNKNOWN everywhere was rejected during review, since a mandatory
  criterion INCONCLUSIVE on every attempt means `qualify.py` can never
  certify the task at all. The shipped design instead grades through a
  stdlib-only install EMULATION (`tomllib` reads the candidate's declared
  package directories and `[project.scripts]` target; only those
  directories are copied into an isolated site dir; the entry point runs in
  a fresh interpreter with only that dir on `sys.path`), honestly named in
  its own evidence and proven to discriminate SATISFIED/VIOLATED today, in
  this repository, against three known-bads: a fix applied only to an
  undeclared `scratch/` copy (`wrong/scratch-copy`), a correct fix shipping
  a stale package-data file (`wrong/stale-data`, caught on a held-out input
  a mocked/hardcoded unit test would miss), and a renamed entry function
  whose `pyproject.toml` target was never updated (`wrong/renamed-entry-
  point`). An optional, secondary real-pip mode exists behind a capability
  check and is proven separately, since pip's absence here means it can
  never fire in a real `qualify.py` run: `check_real_pip_mode.py` uses a
  committed fake `pip`/`hatchling` module pair
  (`fixtures/fake-pip/`, the same fault-injection convention `tests/
  fixtures/docker-backend/fake_docker.py` already establishes, adapted for
  a module rather than a PATH-resolved CLI) to prove the mode-selection
  branch fires correctly AND that real-pip mode's own install logic still
  excludes `wrong/scratch-copy`'s undeclared fix.

- **A level-qualification method, planning only, worked once against Level
  1** (Refs #15, #139, #150-D, #12, #147). Restates protocol.md §7's
  qualification requirement (predefined task population, repeat policy,
  controlled graders, mandatory acceptance, regression evidence from
  earlier levels, four-way reporting) as a table naming what the project
  already has toward each requirement and what it does not, then applies
  it once against the only real Level 1 dataset that exists - the #12/#147
  matched pilot (n=3 matched treatment/baseline pairs, all task-PASS, all
  stored INCONCLUSIVE under #139's B1). The worked example's own result:
  three-for-three does not support a failure-rate estimate of any kind
  without a stated sampling plan, which the project does not have yet -
  the honest report is "no failure observed in three attempts," not a
  qualification claim. Verdict: Level 1 is `not evaluated` under the
  method, not `exploratory` and not `qualified`, because the bundle covers
  one task rather than a declared family - the same gap #13's and #14's
  own landed tasks (one each for Levels 2-5) currently share, so this is
  the project's present shape everywhere, not a Level-1-specific finding.
  No threshold, breadth number, or qualification claim is proposed for any
  level; #150-D is noted as unmerged and, even once merged, as a mechanism
  that produces no pilot data by itself - only a live run does. #15 stays
  open; this is its
  planning half, not its closing evidence.
  [`docs/specs/evaluation-facility/level-qualification-method.md`](docs/specs/evaluation-facility/level-qualification-method.md).

- **A real installation receipt for an agent-trial arm that installs a
  declared skill collection, narrowing #139's own B1 ruling** (Refs #150-D,
  #139, #150). Before this, EVERY agent-trial arm - installing or not -
  stayed on the agent-observation stand-in, so `installation-ready` was a
  mandatory UNKNOWN and the trial could never PASS on readiness alone, even
  when a declared collection genuinely installed and the client's own
  listing would have shown it. An installing arm now writes a real
  `installation-receipt`, built from the client's own model-free listing run
  before and after delivery inside a fresh, dedicated, throwaway container
  of the same image digest as the agent's own - never the agent's own
  container, since `DockerBackend.execute()` runs once per handle and stops
  it before returning. The receipt's evidence states the claim precisely
  ("this delivered tree, delivered by the same method, into a fresh
  container of the same image digest, was discovered by the client's
  model-free listing"), carries the image digest it was measured on, and
  `verify.py`'s cross-check refuses it for any attempt whose own planned
  image digest differs. An arm that installs nothing (an empty baseline, the
  matched pilot's own shape) keeps the B1 stand-in exactly as before - this
  is a narrowing of B1's scope, not a reversal. Only `codex` has a
  model-free listing; a Claude Code arm is unaffected. Committed red cases:
  a canary-failing installing arm reads VIOLATED, never SATISFIED; an empty
  baseline arm keeps the stand-in at both the pure-function and the
  integration level (the latter verified with a negative control: removing
  the empty-declared short-circuit turns it red with a real `Refused`); an
  unobtainable listing reads UNKNOWN, never SATISFIED; a receipt measured
  against one image is refused for an attempt planned against another; and
  production's own digest resolution (`skillc/cli.py`'s `cmd_collection_run`,
  never a test-supplied value) is driven end to end through `cli.main`, also
  verified with a negative control (forcing the resolved digest to `None`
  reproduces the exact refusal a real production gap would produce). The
  operator's attestation ruling ("accept (a)", 2026-09-28, ADR 0005) is
  quoted there in full, including what the receipt does NOT attest.

- **An optional managed-container backend, client-only: `skillc.managed_backend.ManagedBackend`**
  (Refs #64). A second `ExecutionBackend` implementation (#10's seam) for a
  platform that already manages its own containers and is willing to run one
  trial inside a container it creates - never a dependency, never a
  fallback: an absent or refusing platform is `unavailable`, exactly like
  `DockerBackend`'s own structural rule. Talks over
  [a newly published protocol](docs/specs/evaluation-facility/managed-backend-protocol.md)
  (status "Proposed" - no platform implements it yet; a first intended
  implementer is tracked as [cooneycw/kyle#1397](https://github.com/cooneycw/kyle/issues/1397),
  a different project), a single Unix-socket, one-connection-per-request,
  newline-delimited-JSON contract with a closed schema in both directions -
  `tests/test_managed_backend.py` parses the protocol page's own field
  tables and asserts the client's request builder never emits a field
  outside them, so the doc and the code cannot drift apart unnoticed.
  Platform-neutral by construction: nothing under `skillc/` names, imports or
  assumes any particular platform, checked directly
  (`test_module_names_no_platform_and_docker_backend_does_not_import_it`).
  Error/unavailable semantics match `skillc/backend.py`'s existing
  per-method contract exactly, applied to one more kind of failure (a dead
  socket, a timeout, an out-of-schema response): `describe()` never raises;
  `prepare()`/`install()` raise `BackendUnavailable`; `execute()` never
  raises; `confirm_stopped()`/`confirm_absent()` return
  `Confirmation.UNKNOWN`, never a guessed answer - a committed red case
  drops the connection mid-`confirm_absent` and proves the result is
  UNKNOWN, not a guessed CONFIRMED (verified: a mutation mapping that
  failure to CONFIRMED instead makes the test fail). An optional credential
  hook (`SKILLC_MANAGED_BACKEND_TOKEN_FILE`) rides the `prepare` request
  only, held with `field(repr=False)`; a committed red case plants a
  credential value, runs a full stub lifecycle, and asserts it appears in no
  record, report or exception text and that a real `skillc leak-check` over
  the produced output stays clean (verified: removing `repr=False` makes the
  test fail). The neutral-identity obligation (#63) is checked against a
  deliberately non-neutral identifier the test stub plants into its own
  output - proving skillc's own leak-check instrument catches a violation of
  this shape, never a real platform's compliance, which the protocol page's
  "Handle rule" states plainly. Tested only against
  `tests/fixtures/managed-backend/stub_server.py`, a test-only stand-in (the
  same role `fake_docker.py` plays for `DockerBackend`) - conformance
  through a real platform-created container and parity with `DockerBackend`
  on the same trial are owed, not demonstrated
  (`docs/specs/evaluation-facility/support-matrix.md`'s new "Managed-container
  backend" section carries both as `owed` explicitly, and is not wired into
  any CLI command in this PR).

- **A worked configuration-boundary comparison for #28's evidence-refresh
  half** (Refs #28). Step 1's eligibility survey found no reproducible
  subject-behaviour failure in retained evidence (12 of 12 stored/graded
  attempts across both matched-pilot bundles show no task failure - see
  the issue comment for the precise field-by-field accounting), so case
  delivery stays incomplete per #28's own stop condition; nothing was
  invented and no new trial was run to manufacture one.
  [`docs/specs/evaluation-facility/configuration-boundary-example.md`](docs/specs/evaluation-facility/configuration-boundary-example.md)
  delivers the issue's other half instead: for each of six identity
  dimensions (skills, transitive in-tree helpers, client version/config,
  task, grader, image/environment), whether a deliberately changed
  configuration still falls inside the `evidence-2026-09-27-gpt-6-astra`
  bundle's claim, using only the existing `trial-ledger`/`verified-result`
  identity fields - no new schema, no watcher. Also names the one change
  those identities cannot see: a skill's own instructions reaching outside
  its pinned collection tree at run time (a network fetch, an unpinned
  host tool) moves none of the six recorded identities.

- **`finish-close-ref` gains a degraded arm: `evals/level1/finish-close-ref/degraded/`**
  (Refs #150). The baseline arm installs `cpp-codex` unmodified - its
  `flow-finish` skill already teaches the negated/incidental
  closing-keyword rule this eval grades, so the discriminating run needs a
  SAME-otherwise subject with only that teaching removed, isolating the
  skill collection under test rather than the underlying agent. CPP's
  LICENSE `## Scope` does not cover `codex/skills/`, so no CPP text is
  vendored: `degrade.toml` commits only facts about five files at the pinned
  revision (sha256 hashes, exact line ranges to delete, and exact
  hash-checked substring replacements for lines shared with retained flags),
  and `prepare.py` turns those facts into the five real files given a real
  checkout, refusing on a stale original, a range that deletes an undeclared
  CODE line (checked independently of the delete ranges themselves, `.sh`
  locations only - PROSE is removed everywhere the rule is stated, even
  inside the retained guard's own region, but every line of its actual
  control flow is kept, since a comment change is not a behaviour change and
  a code change is), an insufficient deletion (a content-hashed residual
  allowlist covers only two remaining harmless lines - an honesty pass found
  the first version of this list too permissive, since three of its seven
  entries and two whole header comments were real, undocumented statements
  of the rule hiding behind "cites an identifier" reasoning; DEGRADATION.md
  says plainly what a reader of the retained guard's raw control flow could
  still infer), a result that fails `bash -n`, an ambiguous replacement (the
  target substring not occurring exactly once), a range that swallowed a
  line that should have survived, or the rule - including a GENERAL pattern
  for "regardless of grammatical context", not only the removed guard's own
  identifiers - still being stated anywhere else under `codex/skills/`.
  `tests/test_degraded_prepare.py` runs the whole checker against a
  synthetic, fabricated-content mini-checkout
  (`tests/fixtures/degraded-prepare/`), never real CPP text - one test per
  refusal, each confirmed to fail for the specific reason it claims, plus
  the green path and its own positive control for the whole-tree scan and
  for the general-fact pattern. Running `prepare.py` against the real
  pinned revision, and the `skillc degrade-subject` invocation it prints,
  is a runbook step owed to the operator.

- **Selection-probe attempts retain their raw transcript, leak-checked
  before it is kept** (Refs #26). Before this, a real attempt's transcript
  existed only in memory during `run_one_attempt` and was discarded with the
  workspace, so a live selection run's zeros could never be re-scanned - the
  first live run (2026-09-27) had exactly this gap. `agent_trial.run_one_attempt`
  gains an opt-in `retain_transcript=True` (default `False`; every existing
  caller is unaffected) that attaches the ORIGINAL transcript bytes to its
  returned record; `selection_probe.AgentTrialRunner` uses it, leak-checks
  the bytes with `leak.default_host_paths()` (#134 item 5) before writing
  anything, and records the outcome on `AttemptTranscript`/`ArmResult` either
  way - `transcript_retained_digest` on success, `transcript_retention_reason`
  on a leak (never a silent drop, never a silent keep). Retained files live
  under `<base>/retained-transcripts/<attempt_id>.jsonl`.

### Changed

- **Documented, not fixed: no non-image workaround delivers TERM to a
  Docker-lane subject** (Refs #133 item 2). `docker kill` reaches only the
  container's init/placeholder process, never the sibling `docker exec`
  session the subject runs as, and neither signaling the local `docker exec`
  client nor a `docker top` plus targeted `kill` (evaluated, rejected -
  ambiguous with concurrent sessions or a forking subject, unverifiable
  against a real daemon from the fake CLI alone) reaches it either. A timed-
  out or cancelled subject therefore gets no graceful shutdown and simply
  dies at teardown; `capture.md`, `support-matrix.md` and `describe()`'s
  unobserved claims now say so explicitly and cross-reference the real fix,
  filed separately as it needs a pinned trial image change: #158.

- **Documented, not fixed: the unbounded local spool write is the
  bare-subprocess lane's limit, not the Docker lane's** (Refs #133 item 5,
  re-checked rather than assumed). `DockerBackend.execute()` never opens a
  local spool file at all - it drains stdout/stderr into a capped in-memory
  buffer - so `capture.md`'s existing "the spool is bounded at capture, not
  during execution" limit only ever applied to `trial.run_attempt`'s
  host-subprocess path (`matched_pilot.py`, this module's own tests).
  `capture.md` now says so explicitly instead of reading as a blanket claim
  about every lane.

### Fixed

- **A `coverage: "complete"` skill-invocations stream could omit an
  installed skill's row and still pass clean** (Refs #26, folded in from the
  Nit Store). `records.ledger_binding`'s `_skill_invocation_binding` checked
  that every REPORTED row named an installed path, but never the reverse -
  that every installed path had a row under complete coverage. Reproduced at
  `70ead2c`: a second installed skill with no invocation row gave exit 0, 0
  errors. Fixed by cross-checking the row set against the same installed-path
  set the rule already reads for the other direction; a two-skill committed
  red/green pair (`controls/ledger-binding/{bad,good}/skill-invocations-*-coverage`)
  is confirmed missed on the pre-fix code (`skillc check-records`: 0 errors)
  and caught after (1 error, naming the missing path).

- **`make verify` and a real `## Verify` command, covering every
  `.woodpecker/ci.yml` step** (Refs #134, items 1 and 2). Nothing ran
  `skillc selftest` or `ci/negative-control.sh` locally without a Makefile,
  so CPP's finish-gate fallback silently skipped both - a change that
  blinds one rule's control went green locally and red only in CI (#37).
  `make verify` runs `uv sync --locked --extra dev` then `skillc selftest`,
  `pytest -rA` (teed to a gitignored `reports/pytest.log`, covering #148's
  local one-off-red sighting), `ruff check .`, `mypy`,
  `ci/negative-control.sh`, `ci/typecheck-control.sh`, `skillc leak-check .`
  (CI's exact excludes, plus a local-only `reports/` exclude - `test`'s own
  output would otherwise leak-check as a real finding), `ci/changelog_check.py`,
  `ci/readme_drift.py` and `gitleaks`/`ci/secret-scan-control.sh` (SKIPPED
  loudly, never silently, when gitleaks is not installed locally) -
  every step Woodpecker runs, not only `gate` and `negative-control`.
  `tests/test_ci_local_gate_coverage.py` maps each CI step to its local
  target and fails when a new one has no mapping, so this list cannot
  silently fall behind the workflow file the way the first version did
  (PR #155 went red on `changelog-check`, which no local gate ran).
  AGENTS.md's `## Verify` now names every step instead of only four plus
  `negative-control`, and instead of the bare `uv run` chain that failed in
  a fresh worktree with `Failed to spawn: ruff` (the dev tools live in the
  `dev` extra).

### Fixed

- **`degrade.load_persisted_degraded` now refuses a persisted degraded tree
  built for a different subject or pinned to a different revision** (Refs
  #150). Found reviewing #160: the receipt records both `"subject"` and
  `"pinned_revision"`, but neither was ever compared against the caller's
  own subject/pin - a degraded tree built from `cpp-codex` and loaded via
  `collection-run cpp-claude-code --degraded DIR` installed silently under
  the wrong subject and client, and a tree pinned to a stale revision
  installed as if it were still the subject's current pin. Now refuses
  (`DegradationRefused`) before reading anything else in the receipt when
  `receipt["subject"] != subject_name` or
  `receipt["pinned_revision"] != subject.revision`. Two new red cases,
  reproduced directly against the pre-fix code (not merely asserted): a
  subject-name mismatch and a pin mismatch each loaded successfully with no
  refusal at all before this fix, returning a `Source` as if nothing were
  wrong.

- **`collection-run` can now target a Level 1 task other than
  `slug-small-fix`, via `--task DIR`** (Refs #150). Nothing read `--task`
  before this: `run_level1_agent_attempt` always read `demo.GRADER_ROOT`
  (slug-small-fix's own `goal.md`/`fixture/`/`grader.json`) and
  `plan_collection_attempt` ledgered every run with the literal
  `{"id": "slug-small-fix", "revision": "r1"}` - itself already stale,
  since `slug-small-fix/grader.json` declares revision `"2"`. So the
  operator's own discriminating run against a different Level 1 task (e.g.
  `finish-close-ref`) could not actually run that task at all: it would
  install and prompt for the wrong fixture, get graded by the wrong grader,
  and have the ledger record it as `slug-small-fix` regardless. `--task DIR`
  (default unchanged) is threaded through `plan_collection_attempt` and
  `run_level1_agent_attempt`/`run_collection_agent_attempt`; the plan's
  `case.id`/`case.revision` are now read from `DIR`'s own `grader.json`,
  never a literal. A `DIR` that is not a Level 1 task layout (missing
  `goal.md`, `fixture/` or `grader.json`) is refused up front, before
  `new_run_root` creates anything. Three groups of new tests, each verified
  to fail on the pre-fix code: the plan for `--task finish-close-ref` carries
  that task's case id and a grader digest that differs from slug-small-fix's;
  the DEFAULT path's own case now records slug-small-fix's real `"2"`, not
  `"r1"`; and a fake-docker run against `--task finish-close-ref` grades a
  candidate writing the reference answer PASS, and the committed
  `wrong/negated-close` candidate (a negated closing disclaimer that still
  matches the closing grammar) FAIL on `no-closing-match` - proving
  `finish-close-ref/grade_ref.py` itself ran, not slug-small-fix's.

- **A new, target-scoped rule checks Claude Code's real listing cap: the
  COMBINED `description` + `when_to_use`, not `description` alone** (Refs
  #132 item 2). `required-fields`' own `description` check is the portable
  specification's 1024-character limit on `description` alone; Claude Code
  actually truncates the combined `description` + `when_to_use` text at
  1,536 characters in the skill listing "to reduce context usage"
  (`https://code.claude.com/docs/en/skills#frontmatter-reference`, read
  2026-09-28 - same page `CLAUDE_CODE`'s own profile already cites, dated
  2026-09-25 for its field list). A skill whose `description` alone stayed
  under 1024 could still be silently truncated once `when_to_use` was
  added, with skillc reporting nothing. The new `claude-code-listing-cap`
  rule is scoped to `--target claude-code` only; portable runs are
  unchanged (the rule does not run under `--target portable` at all).

- **`skillc rules` can now show target-VARYING behaviour, not only
  target-RESTRICTED rules** (Refs #132 item 3). `trigger-shape` has
  `target=None` (it runs for every profile) yet its own finding depends on
  the `target` value it is handed - it is silent under `claude-code` when
  `disable-model-invocation` is true. The `[target: ...]` suffix, keyed on
  `rule.target` alone, read the same - empty - for that rule and for one
  whose output truly never varies. A new, separate `Rule.varies_by_target`
  field (declared `True` for `trigger-shape`) now prints its own
  `[varies by target]` tag alongside (or instead of) `[target: ...]`.

- **`ref-depth` no longer double-reports one deep chain under two spellings
  of the same file** (Refs #132 item 4). Deduplication keyed on the
  second-hop link's RAW spelling (`set[tuple[str, str]]`), not its resolved
  path, so `X.md` and `./X.md` - the same file - reported the identical
  chain twice. Now keyed on the resolved second-hop path; the first hop's
  own spelling is kept as-is in the key, since two different first-hop
  spellings pointing at the same second-hop file are still two distinct
  edits, not one. New `controls/ref-depth/bad/duplicate-spelling`, and two
  new pytest cases, verified to report 2 findings (not 1) on the pre-fix
  code.

- **`required-fields` now owns the type of the optional fields it reads, not
  only the required ones** (Refs #132 item 1). `Skill.get` returns `None` for
  any non-string value, so `compatibility:` holding a mapping, `metadata:` a
  bare string, or a `metadata` value like `version: 1.0` (unquoted YAML
  parses as a float) all produced zero findings - the same false green an
  earlier fix closed for required fields. `metadata` must be a mapping whose
  every value is a string (Claude Code drops a `metadata` value that is not
  a map); `compatibility` must be a string. Three new bad controls under
  `controls/required-fields/bad/`, shown silently missed on the pre-fix code
  (`BLIND required-fields silent on 3 of 8 known-bad input(s)`).

- **`materialize`'s discovery canary no longer fails a correctly-installed
  policy-hidden skill, and its planted negative control no longer picks
  one** (Refs #55, folded-in Nit Store item 4). A skill whose own
  `agents/openai.yaml` sets `policy.allow_implicit_invocation: false` is
  correctly absent from Codex's own skill listing by design (verified
  codex-cli 0.157.1, 2026-09-26) - not a discovery failure. The pre-fix
  `discovery_canary` expected every INSTALLED skill to be listed, so this
  exact, correctly-behaving skill read as `installed but not listed`,
  VIOLATED. Separately, `baseline_absence`'s planted negative control used
  `entries[:1]` unconditionally; if that first entry happened to be
  policy-hidden, it was correctly absent from the control arm's own listing
  too, misreporting "negative control failed" for an unrelated reason. The
  policy read (`spec.policy_hidden_cause`, moved out of `exposure.py` so
  both modules share one reading of `agents/openai.yaml` rather than two
  that could drift) now excludes policy-hidden skills from the discovery
  expectation and steers the planted control away from one. Three new
  tests, two verified to fail on the pre-fix code.

- **`exposure._plant_always_loaded` no longer plants a marker past the
  boundary it claims to test** (Refs #55, folded-in Nit Store item 1).
  `room = limit - len(base) - len(inside) - 1` could go negative when the
  real declared file left barely enough space for the inside marker -
  `b"." * room` on a negative `room` silently produces `b""` (never an
  error), so the marker still landed immediately after the real content,
  ending PAST `limit`, while its own note unconditionally claimed it ended
  AT `limit` and should be `EXPOSED`. A conforming client that correctly
  truncates at `limit` then reports the marker `HIDDEN` - a real boundary
  misread as an exposure failure, not a defect in the client under test.
  Now reported the same honest way the already-over-the-limit case already
  was: the note says the boundary is untestable, and makes no `EXPOSED`
  claim. Three new tests at exact real offsets (just enough room, one byte
  too little, already over), each asserting the precise byte positions;
  the one-byte-too-little case verified to fail on the pre-fix code.

- **`exposure.classify_marker`'s `cut_point_bytes` is now a true UTF-8 byte
  offset** (Refs #55, folded-in Nit Store item 3). The truncation search cut
  at a `str` (code point) index, identical to a byte index only while every
  character is ASCII - true of every marker this module plants today, so
  the bug was dormant. Now searches `marker.text.encode("utf-8")` against
  the rendered text's own UTF-8 bytes, never re-decoded; a real client's
  truncation operates on bytes and can legitimately split a multi-byte
  character in half, which a `str` slice cannot even represent. New red
  case with a non-ASCII marker, verified to report a wrong offset on the
  pre-fix code.

- **`exposure` can now model a manifest that declares more skills than a run
  actually found** (Refs #55, folded-in Nit Store item 2). Nothing previously
  compared what `.claude-plugin/plugin.json` DECLARES against what
  `materialize.inventory()` actually found for this run - `subject.select`'s
  own validation only proves every SELECTED name resolves, a claim about a
  smaller population than the manifest as a whole (the ADR 0004 "38 skill
  directories, 25 installed" specimen, issue #53). `ExposureSurface` gained an
  optional `manifest_path`; when set, `check_exposure` reads the manifest and
  reports `declared`/`found`/`missing` skill counts and names alongside the
  existing per-skill verdicts, `None` when no manifest is declared - never
  conflated with "checked, found nothing missing". New tests cover the schema
  (optional, parsed, path-escape refused, non-string type refused) and the
  coverage comparison itself (a declared-but-not-found skill reported by name;
  a fully-covered manifest reporting zero missing); the coverage-gap and
  schema tests verified to fail on the pre-fix code (missing attribute /
  `unknown keys: ['manifest_path']`).

- **`leak-check` no longer false-positives on a linked worktree's `.git`
  pointer file, and now sees a checkout under `/workspace`, `/opt` or
  `/srv`** (Refs #134, items 4 and 5). `SKIP_DIRS` filtered directories
  only, so a worktree's top-level `.git` - a pointer file holding an
  absolute path, never committed - read as a spurious home-path leak on
  every flow:auto run; it is now invisible to the scan the same way the
  ordinary `.git` directory already is. Separately, `home-path` only
  recognized `/home/` and `/Users/`, so every session in this fleet's own
  checkout went unflagged by `skillc leak-check`, the pilot-bundle export
  gate and the judge-input check alike. `leak.default_host_paths()` now
  matches the scanning process's own live `Path.home()`/`cwd` as a new
  `host-path` finding class, wired into all three call sites.

- **Two untested preconditions in `ci/typecheck-control.sh`** (Refs #134,
  item 3): the empty-population guard (no `tests/test_*.py` to plant a probe
  in) and the baseline guard (mypy already fails before any probe is
  planted) were both implemented but had no committed case proving either
  fires. `tests/test_typecheck_control.py` now covers both; neither needed a
  behavior change.

- **`.claude/runs/` is now gitignored** (Refs #134, item 6). A `flow:auto`
  run's `git add -A` committed `.claude/runs/finish-<id>.json` on #127 / PR
  #128, carrying local run detail into the tree.

- **`docs/specs/evaluation-facility/spec.md`'s status section no longer says
  "no trial runner exists"** (Refs #134, item 7). `trial.py`, `verify.py`,
  `lifecycle.py`, `agent_trial.py`, `demo` and `collection-run` all exist
  now (#8, #9, #10, #12); the section names them instead.

- **`collection-run` reported the declared pin as an attempt's revision,
  never what was actually acquired** (Refs #150-B2). Found while wiring
  `--degraded DIR`: `run_collection_agent_attempt` read
  `acquired.subject.revision` unconditionally, for every run - the acquired
  source's own identity (`acquired.source.revision`, already computed and
  used correctly for `subject.digest` in the plan) was never read for this.
  Every attempt's `CollectionAgentResult.revision`, and every field derived
  from it (the exported `verified-result`'s `revision`, the paste-back), now
  reports what was actually acquired.

- **`ExecuteResult` distinguishes an incomplete capture from a truncated one**
  (Refs #133). `execute()` read `stdout_drain.captured_bytes()`/`total_bytes`
  unconditionally after `stdout_thread.join(timeout=...)`, whether or not
  that join actually confirmed the drain thread had finished - so a subject
  that exits while leaving a descendant holding its stdout/stderr pipe open
  (a gap `ExecuteResult`'s own docstring already named) was silently
  reported as a complete, non-truncated capture. `stdout_incomplete`/
  `stderr_incomplete` are now set from `thread.is_alive()` right after the
  join, independent of `stdout_truncated` (capped-and-discarded is a
  different fact from never-reached-EOF), and propagate through to the
  journal (`observations_incomplete`/`error_incomplete`) alongside the
  existing truncation fields. The red case detaches a real grandchild via
  `setsid` so `os.killpg` cannot reach it, verified to fail on the pre-fix
  code (`AttributeError`, then a hang past the join bound once the field
  existed but was never set).

- **`DockerBackend.prepare()`'s `docker run -d` is bounded, with an explicit
  image precheck** (Refs #133). Every other daemon call in this backend
  carried a `timeout=daemon_timeout`; `run -d` did not, and unlike the
  others it can implicitly PULL a missing image mid-call, which has no
  bound on how long it runs. `docker image inspect` (itself bounded) now
  runs first and refuses outright when the image is not present locally, so
  `run -d` never has a pull to wait on and safely carries the same bound as
  the rest of the module. The best-effort `rm -f` cleanup on a failed or
  timed-out `run -d` is bounded too. Two red cases (a stalled `run -d`, a
  missing image) fail on the pre-fix code.

- **`DockerBackend.install()`'s readiness is per-entry, not all-or-nothing, and
  checks the image's own baseline** (Refs #133). `discovery_canary` used to be
  VIOLATED only when NOTHING installed, so one missing declared entry among
  several successful copies was invisible; `readiness["entries"]` now names
  every declared entry's own outcome (`installed`, `missing`, or
  `not-a-path` for surface metadata never meant to be copied), and
  `discovery_canary` is VIOLATED whenever any entry is genuinely missing.
  `baseline_absence` used to be permanently, unverifiably `SATISFIED`; a
  top-level listing of the container's workspace, taken before any copy,
  now catches a declared key the image already shipped (by name; a
  same-named file whose content differs from the image's own is not yet
  distinguished, see `describe()`'s `unobserved`). Both red cases (a
  partial install, a pre-seeded image skill) fail on the pre-fix code.

- **`check-records` sees what it claims to see: a single file path, and the
  applicable population under `--rule`** (Refs #131).
  - **A single file path.** `records.discover`'s `root.rglob(...)` treats a
    FILE `root` as a directory to search within, so it silently matched
    nothing - `check-records one.json` printed "no record found ... nothing
    was checked" and exited 2, even though the argparse help says "file or
    directory of records". A `root` naming a `.json` file directly is now
    loaded as that one record (`spec.discover`'s own shape, for
    `SKILL.md`); a single bad record file now exits 1, not 2.
  - **A rule's applicable population.** Every `RecordRule` now declares the
    record `kinds` it actually reads - `checks.applicable_population` - so
    `check-records --rule installation-receipt` over a population with no
    installation-receipt record refuses (`skillc: no <rule>-applicable
    record ... - <rule> checked nothing`) instead of running the rule's own
    no-op `record.kind != ...` guard against every record and reporting
    "0 error(s)", indistinguishable from a population genuinely examined
    and found clean. A run scoped by `--rule` now also reports "N of M
    record(s) were `<rule>`-applicable".
  - **`manifest-entry` is reachable by `selftest`.** `check --manifest`
    used to build its `manifest-entry` `Finding` straight in `cli.py`,
    entirely outside `Rule`/`RecordRule`/`BundleRule` and the registries
    `selftest` iterates - so `selftest` could report "N/N rules
    discriminate" while this specific check was never proven able to fail
    at all, and its committed control (`controls/manifest-entry/{bad,good}`,
    renamed from `controls/check-manifest/*` to match every other rule's
    `controls/<rule.id>/` convention) was exercised only by pytest directly.
    A new `ManifestRule` type (subject: a loaded `Manifest`) sits in the
    same `ALL_RULES` registry `selftest` and `ci/negative-control.sh`
    already iterate generically; `cmd_check --manifest` now routes its
    dangling-entry check through the same `checks.manifest_entry` function
    rather than a second, ad-hoc inline check.

  Each fix's own red case is committed and verified to fail on the pre-fix
  code.

  Found running the full suite rather than only the touched files:
  `test_agent_trial.py`'s own `_store_is_clean` helper iterated every
  evidence rule expecting exit 0, with no allowance for a rule whose kind
  genuinely has zero records in a particular store (e.g. an
  installation-receipt on an attempt blocked before any install
  happened) - exactly the case item 2's refusal now reports, correctly,
  as exit 2. Fixed to accept that refusal too, but only when its own
  message says "checked nothing", never a blanket "exit 2 is fine" that
  would also swallow a real bug. Confirmed failing on the pre-fix helper
  (3 tests, the same `AssertionError: installation-receipt` each time)
  before the fix, passing after.

- **The three records #12 could not yet prove** (Closes #12).
  - **The image that ran.** A Docker attempt journals a `backend-identity`
    event with the image id its container was created from, beside the
    ledger's planned digest and whether they match. A floating or
    republished tag is no longer assumed to be what ran.
  - **The judge's model, not its server.** `verdicts.<tier>.judge.model` is
    now the LLM that answered (the real `mcp-second-opinion` reply's
    `model_used`, a fallback included), and the MCP server's own identity
    moves to `judge.server`. Two tiers on one server now record two models.
    The adapter also reads the real server's reply shape: the verdict array
    lives inside `analysis`, and before this every criterion from a real
    server came back UNKNOWN. A reply with `success: false` is the tier
    being unavailable, not a verdict.
  - **Concurrent attempts.** Grading holds an experiment lock that capture,
    finalize, retry and stored records also take, and its tamper snapshot
    leaves out only unfinished planned siblings' journal and spool. A
    sibling running and being captured mid-grade no longer refuses the
    grade; every other write still does.

### Added

- **`skillc degrade-subject`, an operator-expressible degraded CPP subject**
  (Refs #150). Before this, a degraded subject - "the same collection with
  one or more skills mutated or removed" - was expressible only as a
  Python/test-only parameter or by hand-editing an untested revision into a
  `subject.json`. `degrade-subject <subject> (--checkout PATH | --revision
  SHA) [--remove-skill NAME]... [--remove-file SKILL:PATH]...
  [--override-file SKILL:PATH=LOCAL_FILE]... --out DIR` now builds one from
  an alternate source plus zero or more whole-skill removals and single-file
  removals/overrides across several skills in one declared mutation, and
  persists BOTH a `receipt.json` (the recorded identity - always a
  `degraded:` label, never the pin - and every location the mutation
  touched) and the installable tree itself at `DIR/skills/`, so a future
  runner can install exactly what the receipt describes and verify it first
  (`verify_persisted_skills`, a digest check that refuses a tampered or
  corrupted tree). A degradation whose recorded identity would be
  indistinguishable from a normal, undegraded acquisition is refused.
  Full design: `docs/specs/evaluation-facility/degraded-subjects.md`.

- **`skillc collection-run --evidence DIR`, publishing a verified-result to a
  behavioral-eval consumer** (Refs #150). CPP's `scripts/check-behavioral-
  eval.py` had a producer half but nothing that wrote to it -
  `collection-run` already stored a `verified-result` per graded attempt
  (#139) with nowhere to publish it. `--evidence DIR` now exports it into a
  named, operator-chosen LOCAL directory: the verified-result(s) flat at
  `DIR`'s top level (what the consumer's non-recursive glob reads) and the
  full skillc bundle (ledger, manifest, receipts) under `DIR/bundle/` for a
  future bundle-rule reader, gated by the same leak-check-then-check-records
  discipline and lock-and-atomic-replace `pilot-run`'s own evidence export
  already uses. A degraded-arm export is refused unless `--evidence-role
  control` is given explicitly - CPP's gate reports any declared FAIL as an
  error, so a degraded arm's expected failure must never land in a real
  measurements directory by habit. A vendored, pinned copy of the real
  consumer (`tests/fixtures/cpp-behavioral-eval-consumer/`) drives a contract
  test against real exported output. Full design:
  `docs/specs/evaluation-facility/behavioral-eval-export.md`.

- **`skillc collection-run --degraded DIR`, installing a persisted degraded
  subject instead of the pinned one** (Refs #150, acceptance item 3 (wiring
  half); Refs #150-B2). Before this, `degrade-subject --out DIR` produced a
  persisted, digest-verifiable tree that nothing read. `--degraded DIR` now
  re-verifies `DIR/skills` against its own `receipt.json` before installing
  anything, and the run records the degraded identity throughout - never the
  pin. Original `select` is dropped for the degraded install
  (`acquire_degraded_collection`): re-applying it would refuse the very
  shape a skill removal produces (`materialize.inventory` requires every
  selected name present); what remains after degradation installs in full.

- **`pytest-timeout`, a 120s per-test default, and a fuller CI log** (#148). A
  stalled test used to hang the `gate` step without limit - Woodpecker
  pipeline 258 ran 35+ minutes past a blocking write before anyone noticed -
  and a one-off red left nothing to diagnose after the fact (CI sighting). A
  stall now fails in minutes and names the test (`@pytest.mark.timeout`
  raises it for a test that legitimately needs longer); the gate step now
  also runs `pytest -rA`, so every outcome survives in the CI log even when
  the run as a whole passes - the log is what actually persists, there is no
  separate uploaded artifact. `tests/test_pytest_timeout_control.py` is the
  committed negative control: a test that sleeps past its timeout, skipped in
  the normal suite, shown to be reported as a timeout failure when run; a
  second assertion reads pytest-timeout's own session header to prove the
  *configured* default is what is applied, not just that the plugin can fail
  a test when told to per-test (a marker-only control cannot tell a
  misconfigured key from a working one - confirmed by breaking the key and
  re-running, see the PR). #134's `make verify` covers this issue's other,
  LOCAL sighting (flow:auto #12's flaky test, never captured after a `uv
  sync`).

- **The #12 matched pilot, re-run under the pinned `gpt-6-astra` declaration,
  as a new experiment with its own evidence** (Refs #147, #12, #139). The
  run and its results are in `evals/matched-pilot/evidence-2026-09-27-gpt-6-astra/`.
  The first run's bundle in `evidence/records/` is unchanged. The live run is
  also the first to prove that codex-cli 0.157.1 honours both
  `-m gpt-6-astra` and `-c model_reasoning_effort="high"`.
- **`skillc pilot-run` / `pilot-report` refuse to replace another
  experiment's published bundle** (Refs #147). Replacing a destination is
  now only a re-export of the SAME experiment (read from the bundle's own
  `ledger.json`). A different experiment's bundle, or one whose ledger can't
  be read, is refused with exit 2 and left byte-identical. Before this, a
  default `pilot-run` would have deleted #12's first-run bundle.

- **`skillc pilot-run` pins the declared model at launch and fails a run
  that did not use it** (Refs #141). #12's run declared `gpt-5.1-codex`. Nothing
  passed that to the client, so all six attempts ran codex's own default,
  `gpt-6-astra`.
  - A new dated declaration,
    `evals/matched-pilot/run-manifest-2026-09-27-gpt-6-astra.json`, declares
    `gpt-6-astra` at effort `high`. It is now the default
    (`matched_pilot.CURRENT_MANIFEST_PATH`), and it names the run it
    supersedes. #12's `run-manifest.json` is not edited.
  - The launch argv is built from the declaration
    (`-m <model> -c model_reasoning_effort="<effort>"`). A `--client-argv`
    that chooses the model or its effort itself is refused before any run
    directory is made. So is a declaration with no effort to pin.
  - After each attempt, the model in the client's rollout must equal the
    declared one. A different model, or none, makes the attempt
    `model_eligible: false`. The attempt is left out of the matched pairs and
    listed under `model_ineligible`, and the run exits 1 after publishing.
  - `pilot-report` scores a run against the model the run recorded at
    launch. A run from before this change recorded nothing, so it needs an
    explicit `--manifest`.

- **A graded agent-trial attempt now stores its `verified-result`** (Refs
  #139). `agent_trial.run_one_attempt` grades through the verifier's result
  assembler (`verify.grade_agent_attempt`) instead of `verify.grade_files`
  alone. So the result keeps the ledger's grader pin, the capture check, the
  store snapshot and the frozen-digest checks, and `attempt-accounting` no
  longer reports every captured agent attempt as "grading is still owed".
  - **The receipt question.** The agent path writes no installation receipt:
    the baseline arm installs nothing, which the receipt contract refuses, and
    nothing on the path establishes that a client discovered what was
    delivered. The attempt's `agent-observation` record stands in for the
    receipt in ATTEMPT ACCOUNTING only. The result declares it
    (`verification.readiness_source: agent-observation`), and the verifier's
    `installation-ready` criterion is always UNKNOWN on this path, so
    readiness still gates PASS: a task PASS is stored as INCONCLUSIVE, and a
    task FAIL is still FAIL. The driver's returned `graded.status` stays the
    task grade, with `result_status` beside it.
  - `attempt-accounting` accepts a receiptless graded result only when it
    declares the stand-in, keeps `installation-ready` as exactly one MANDATORY
    UNKNOWN, and the bundle holds that attempt's observed, grading-eligible
    `agent-observation`. A result declaring the stand-in is held to that even
    when a receipt also exists. New controls: `good/agent-observation-stands-in`,
    `bad/stand-in-without-observation`, `bad/stand-in-claims-readiness`,
    `bad/stand-in-optional-readiness` and
    `bad/stand-in-with-receipt-claims-readiness`.
  - `verify.regrade` of an agent-path result reads the stored observation. It
    must be valid and bound to that attempt and trial. The regrade also needs
    an explicit grading `backend`, and is refused without one: agent-written
    code is never regraded as a bare host process.
  - Agent-trial ledgers now pin the grader's digest (`matched_pilot.plan_pilot`,
    `collection_conformance.plan_collection_attempt`), which the verifier
    requires. The collection plan used to pin revision `g1` of a grader at
    revision `2`.
  - `pilot-run`/`pilot-report` export `observation-*.json` into the bundle.
    The #12 bundle's known-gap tolerance is narrowed to that one pre-fix
    experiment (`matched-pilot-6ab82dc6`). Its ledger pins no grader digest,
    so its results cannot be stored after the fact, and a clean bundle is owed
    to a new #12 run.

- **`skillc selection-probe [--detection-control]`: the operator command for
  #26's live run** (Refs #26). It runs every predeclared case through
  `selection_probe.agent_trial_runner`, one attempt per arm, and exits 1
  unless every attempt was captured. A report of `unknown`s is not a
  measurement. With `--detection-control` it runs the predeclared control
  instead (`evals/selection-probe/detection-control.json`): the intended-use
  case only, with the canary naming `qa-test`. That exits 1 unless the
  treatment arm reads `selected` and the empty baseline does not. A runner
  whose canary names a skill is refused for a selection run, and an unnamed
  one for a control. A non-captured attempt's report now keeps the record's
  own `reason`. The `SKILLC_ALLOW_REAL_AGENT` pytest harness is removed:
  `tests/conftest.py` keeps every test away from a real credential, so it
  could never launch, and it passed on six `unavailable` attempts.

  Cross-model review found two defects, both fixed here. First, the control
  accepted any baseline that was not `selected`, even one never observed, or
  one whose failed named canary hid an invocation. A baseline must now be
  observed with no invocation, and an inconclusive attempt keeps the
  invocations its transcript recorded. Second, the command printed raw
  details that the report file's leak check had refused. The console output
  is now redacted and leak-checked as a whole. Both are confirmed red on the
  unfixed code. A re-review found two more, also fixed. An empty, malformed
  or unrelated transcript counted as "observed"; an observation now also
  requires this attempt's own prompt to have been delivered, which binds the
  transcript to the attempt. And the leak refusal printed the refused value on
  stderr; it now names only the finding categories. The live runs, the
  selection run and the detection control, are recorded in
  `evals/selection-probe/evidence/README.md`.

- **Every real-agent attempt now persists its observation as an
  `agent-observation` record** (Refs #106). `agent_trial.run_one_attempt`
  writes `observation-<attempt>.json` beside `lifecycle-<attempt>.json` on
  every path: `observed`, `unknown` (the transcript hook failed), or
  `not-observed` (blocked before launch). It holds:
  - prompt delivery, the canary, skill invocations and listed skills;
  - the transcript census;
  - the credential's delivery, remaining life and in-container refresh;
  - the grading account: eligible, blocked reason, or an audit copy of the
    grade with its criteria.

  Before this, these facts existed only in memory and a printed paste-back.
  When a field misprinted, the value was unrecoverable, and #124 repeated two
  live runs for that reason.

  `skillc check-records` validates the new kind with the `agent-observation`
  rule:
  - the schema is closed;
  - eligibility is exactly prompt AND canary;
  - a supplied grader either graded or was blocked, never both or neither;
  - a PASS or FAIL agrees with its own criteria.

  It is attempt-bound, so `ledger-binding` and `unique-ids` cover it. The
  record is redacted, then leak-checked (strings and serialized text); a
  failing record is not written, and the attempt reports
  `observation_record: refused-leak`. Controls: `controls/agent-observation/`.

- `skillc demo --control` seeds the two failure paths most likely to differ on
  a real Docker daemon ([#122](https://github.com/cooneycw/skillc/issues/122)):
  a **timeout** (an exec sleeping past its limit must stop as `timeout`,
  confirmed from `docker inspect`, `inconclusive`, and leave nothing behind)
  and an **operator cancellation** (a real SIGINT to a child `skillc demo`
  process group mid-exec must print the fixed interrupt line, exit `1`, clean
  up only its own attempt, and leave a foreign skillc-owned container
  running). Each has a committed red case: disabled timeout enforcement, and
  an unscoped interrupt sweep.
- `--control` now prints a leak-checked paste-back block with one
  `CAUGHT`/`NOT CAUGHT` line per seed, instead of a single aggregate line.
  #122 closes only on the operator's live run of it against a real daemon.
- **`skillc pilot-run` and `skillc pilot-report`: the first bounded matched
  pilot, run on its predeclared schedule** (Refs #12; one disclosed protocol
  deviation, the model - see `evals/matched-pilot/evidence/README.md`). `skillc/matched_pilot.py` reads
  `evals/matched-pilot/run-manifest.json` and runs its schedule: codex on
  the Level 1 `slug-small-fix` task, with the whole cpp-codex pack installed
  (treatment) or nothing (baseline), 3 repeats interleaved T,B,T,B,T,B. Both
  arms go through one path, `collection_conformance.run_level1_agent_attempt`,
  and differ only in what is installed.
  - The declared pins are checked before anything runs: the subject
    revision, the client version, and the image digest, which must equal the
    declared one. Containers run by that digest, never the tag. A mismatch
    refuses the run. The declared model is not enforced at launch; every
    report entry compares it with the observed model, and the summary lists
    any mismatch as a protocol deviation.
  - Each attempt's agent limit is the smaller of the 900 s per-attempt cap and
    what remained of the 5400 s total when the attempt started, so only the
    last attempt's own setup can carry it past the total (nit-stored: an
    absolute deadline into `execute()`). An attempt with nothing left is
    finalized `not-run` and still reported. Caps must be positive and finite.
  - Every attempt the ledger planned is reported. An interrupted run's
    missing attempts are reconciled from the ledger, never dropped. The
    bundle is built in a fresh staging directory, then leak-checked and run
    through `check-records`. It replaces the previous bundle only if both
    pass. The one tolerated finding is the named gap that the agent-trial
    path stores no `verified-result`.
  - The `pilot-report` gives each attempt's disposition, per-criterion
    outcome, uncertainty, interventions, a setup/agent/grading time split
    (agent time from the trial journal), observed model, CLI version and
    tokens. Agent dollar cost is `UNKNOWN` (subscription login, ADR 0005
    rule 6), and so is claim accuracy until a reviewed claims file is merged
    with `pilot-report --claims`. Claim accuracy is `true`/`false` only
    against a PASS or FAIL grade. A reviewed `asked-clarification` counts as
    an intervention.
  - Raw evidence stays in a private run directory; the exported bundle is
    leak-checked and removed again on any finding.
- **`transcript_adapter.codex_run_metadata`**: the observed model, reasoning
  effort, CLI version, cumulative token usage and closing message from a
  real codex rollout, surfaced as `observation.run_metadata`.
  `agent_trial.run_one_attempt` also returns `grading_seconds`.
- **`selection_probe.agent_trial_runner`: the real `AttemptRunner`**
  (Refs #26): each planned attempt becomes one `agent_trial.run_one_attempt`
  in skill-free canary mode (`skill_name=None`), with the declared collection
  delivered through `extra_home_files` into the TREATMENT arm's home only -
  the baseline arm receives nothing extra whatever the caller passes,
  enforced by the runner rather than trusted to it. The prompt is the task's
  own `goal.md` plus the case's `prompt_addendum`. `transcript_from_record`
  reads selection from the record's `skill_invocations` alone (never the
  canary), sets `codex_best_effort` when detection is `"heuristic"`, and
  reports a captured attempt whose prompt delivery or canary was not
  confirmed as `"inconclusive"` - neither a selection nor a graded outcome.
  `run_planned_selection_probe` runs an already-planned experiment (the real
  runner needs it before running), and both entry points take a
  `grading_backend`, so a real agent's output is probed in a separate
  container, never on the host. Proven end to end on the fake `docker` CLI
  and the scripted fake client across all six planned attempts; confirmed
  red when the collection reaches both arms, when the `grading_eligible`
  check is dropped, and when `skill_invocations` is ignored. A live run is a
  `SKILLC_ALLOW_REAL_AGENT=1`-gated test, owed to the operator.

  Cross-model review of this change found four defects in the driver, all
  fixed here: with no `grading_backend` the candidate ran as a host
  subprocess (now refused before any attempt unless `allow_host_grading=True`,
  for trusted fixtures only); a repeated attempt passed attendance and was
  then dropped from the report (repeats are now refused up front); an
  `INCONCLUSIVE` grade was reported as task failure (now `None`, with the
  grader's reason); and selection was judged against the supplied case file
  rather than the frozen planned configuration (now the plan decides, and a
  case revision that differs from the plan is refused). A re-review found two
  more: the agent's own backend could be passed as the grading backend,
  carrying its network egress into grading (the runner now exposes
  `.backend`, and reuse or a grading backend with egress is refused), and a
  plan missing a declared case or arm produced a report that read as
  complete (the plan must now cover every declared `(case, arm)`). Each is
  confirmed red on the unfixed code.

- **`skillc.selection_probe`: the run driver for #26's three predeclared
  cases** (Refs #26): plans both arms of every case
  (`evals/selection-probe/cases.json`) through the real controller (reusing,
  never duplicating, the shape `tests/test_selection_probe.py`'s own no-run
  deliverable already proved), runs every planned attempt through a pluggable
  `AttemptRunner` seam, grades the same public `slug-small-fix` task outcome
  independently of what it observed about selection, and reports both side
  by side. Nothing runs for real: `lifecycle.py`'s own existing guard already
  refuses to launch `claude`/`codex` without `SKILLC_ALLOW_REAL_AGENT=1`, and
  every test of the driver's own logic uses a FAKE runner that never calls
  `execute()` at all.

  Selection vocabulary: `"selected"`, `"not-selected"`, `"unknown"` - a
  non-`"captured"` disposition (`"unavailable"`, `"not-run"`,
  `"inconclusive"`) is ALWAYS `"unknown"`, never `"not-selected"`, per #26's
  own decision-traceability rule ("do not substitute prompted invocation").
  The baseline arm's `applicable_skills` is always empty by construction, so
  `"selected"` there is exactly this probe's own contamination signal -
  `CaseResult.baseline_contaminated` is a named alias of that same result,
  one mechanism rather than two. `run_selection_probe` refuses
  (`SelectionProbeRefused`) if any planned attempt is missing from the
  results - `AttemptRunner` may return `None` for an attempt that could not
  even be launched, distinct from an `AttemptTranscript` reporting a real,
  non-captured disposition (which is a result, not an absence). Every
  acceptance path named above has a committed test confirmed red on its own
  mutation before being added: dropping the disposition check, disabling the
  attendance check, and breaking `baseline_contaminated` each turn a
  passing suite red.

  Building this against the real `trial.plan()` output (not a hand-written
  fixture) surfaced a real bug before it ever reached a real driver: a
  planned trial's `config` is stored as a content-addressed digest reference
  (`trial.py`'s own "the resolved configuration is stored as an object and
  the ledger binds its digest"), never the literal `arm`/`prompt_addendum`/
  `applicable_skills` dict - reading `trial_dict["config"]["arm"]` directly,
  as an early draft did, raised `KeyError` the first time it ran against a
  real plan. Fixed by resolving each trial's config back through
  `experiment.object_path(digest)` (the same pattern `verify.py`'s own
  `_read_frozen` already uses) before handing it to any runner.

- **The Claude Code agent arm: a `claude-code-skills` surface and a
  per-collection Level 1 run on Claude Code** (Refs #124).
  `materialize.SURFACES` declares two surfaces, each bound to one client
  and one install directory: `codex-skills` (codex, `~/.codex/skills/`) and
  `claude-code-skills` (claude, `~/.claude/skills/`). A surface/client
  mismatch is refused by name. `skillc collection-run` takes its client and
  default argv from the subject (`DEFAULT_CLIENT_ARGVS`; claude runs
  `claude -p --dangerously-skip-permissions` as the non-root trial user).
  Claude Code has no model-free listing, so discovery is read from the real
  agent transcript's `skill_listing` attachment
  (`transcript_adapter.claude_code_skill_listing`, recorded as
  `observation.skills_listed`). Each selected skill is reported `listed` or
  `not-listed`, labelled `source=transcript skill_listing`. When no listing
  was observable, including every codex run, discovery is `UNMEASURED` with
  the reason; it is never a borrowed canary result. `collection-run` now
  exits 1 when a selected skill is measurably `not-listed`, even on a PASS.
  `skillc demo --subject` installs a Claude subject under `.claude/skills/`
  and reports its discovery NOT EXERCISED. The host-local
  `skillc materialize` refuses a Claude subject by name. New subjects are
  `cpp-claude-code` (CPP's native `.claude/skills`, 18 skills) and
  `mattpocock-skills-claude-code` (`tdd`, `diagnosing-bugs`). Live evidence
  is in `evals/claude-code-agent-arm/`; its first runs printed the blind
  `refresh_observed_in_container=None` fixed under #106 and were repeated on
  the fixed key (both read `False`).

- **`skillc collection-run` keeps evidence for #106's live run** (Refs #106).
  The paste-back is grouped into prompt delivery, canary, credential,
  outcome, cleanup and transcript format:
  - the credential's remaining life at launch;
  - the operator's host credential before and after (a digest comparison;
    the bytes are never read into the record);
  - a daemon snapshot diff of skillc-owned containers around the whole run;
  - the stop reason and exit code, per-criterion grades, and the refusal
    reason;
  - the journal's own workspace `cleaned` event;
  - a census of the real transcript: client version, model, line types, and
    the codex `response_item` types the adapter does not know.

  An evidence envelope is written into the kept store, holding the record and
  every observation above. It is leak-checked both as its string leaves and
  as the serialized text, because `json.dumps` escaping hid an embedded
  OAuth-shaped token from a text-only scan. A PASS now exits 1 if teardown
  was not confirmed, or if a container labelled with one of this run's own
  attempt ids (agent or grading probe) remains. The daemon-wide diff is
  context only, since it cannot attribute. A transcript with no response
  items reports its drift as not assessed. `--minimum-credential-seconds`
  runs the below-threshold control.
  Live evidence: `evals/agent-trial-live/`.

### Fixed

- **A declared run state could hide a failed result**
  ([#130](https://github.com/cooneycw/skillc/issues/130)). `derive_status`
  honoured a declared `UNAVAILABLE`/`NOT_RUN` before it looked at criteria. So a
  result with a mandatory `VIOLATED` criterion could be relabelled
  `UNAVAILABLE` and pass `check-records`. protocol.md section 4 forbids that.
  The violation is now tested first, so such a record derives FAIL.
  `derived-status` also refuses a run state its criteria contradict. The
  records.md Derivation now agrees with the protocol. Three related record-shape
  gaps from the same reassessment are closed:
  - a `run_state` outside `UNAVAILABLE`/`NOT_RUN` (`result-evidence`);
  - a criterion with no `id` (`criterion-vocabulary`);
  - a null artifact `path`, `type` or `size` beside a valid digest
    (`artifact-digest`).

  Each has a committed bad case, and every one of those cases was silent on the
  unfixed code. New good twins cover a legitimate UNAVAILABLE and a legitimate
  NOT_RUN.

Five honesty gaps in `skillc demo` and `--control`, folded into #122 from the
Nit Store ([#20](https://github.com/cooneycw/skillc/issues/20)), each with a red case:

- **The reply-only control accepted any failure.** A launch failure or a
  timeout that never exercised the canary counted as caught. It now requires
  an exit-0 run whose canary was never touched.
- **The fleet check could be silently omitted.** With the daemon unreachable
  the item was left out and the demo could pass without it. It is now always
  emitted, `NOT EXERCISED` when the snapshots are incomparable.
- **A neighbour's change failed the run.** Only a new container named for one
  of this run's own attempts now fails it. Other fleet changes are counted
  as observations, with no container names printed.
- **The reap sweep missed the grading probe's attempt.** `verify.grade_files`
  takes `recorded_attempt_ids` and reports the probe's id before `prepare()`.
  The demo sweeps it, and an interrupt during grading can reach it.
- **A second Ctrl-C during the interrupt sweep escaped** as a raw traceback.
  SIGINT is ignored for the sweep's own bounded duration, then restored.
- **Every backend attempt's lifecycle record said its workspace was never
  cleaned up** (#127): `lifecycle.run_through_backend` finalized before
  cleaning, so the persisted `cleanup` read `partial` even when the journal
  said `removed`. That included #11's live PASS runs. The workspace is now
  cleaned first, so the record reports what cleanup did. The container's
  `destroy()`/`confirm_absent()` outcome is journalled as a `backend-teardown`
  detail event, even when `execute()` raises. `collection-run`'s
  `workspace_cleanup(record, at finalize)` line (#136) now agrees with its
  `workspace_cleaned(journal)` line.
- **`--client <bare name>` was resolved against the cwd, not PATH** (Refs
  #124, folded in from the Nit Store). `materialize.find_client("codex")`
  reported a client on PATH as not found. A name with no path separator is
  now looked up with `shutil.which`; a path is still a path.

- **`skillc collection-run`'s paste-back printed `refresh_observed_in_container=None`
  on every run** (Refs #106). It read `refresh_observed_in_container`, but the
  driver writes `credential_refresh_observed_in_container`. #11's live
  evidence therefore showed "not observed" for a comparison that had actually
  been made. The earlier test hand-built its record with the same wrong key;
  the new one reads a record produced by the real driver.

- **The mcp-second-opinion judge could block past its write deadline**
  (#129): `_write` polled `select` and then made a BLOCKING 64 KiB
  `os.write`. A pipe reads as writable when any space is free, so a child
  that stopped reading could wedge the write forever, and the deadline was
  never checked again. This intermittently hung CI's required `gate` step
  in `test_a_stalled_reader_is_a_write_timeout`. The write loop now runs
  on a non-blocking fd, and a full pipe goes back to `select` and the
  clock. A deterministic regression test pre-fills the pipe.


## [0.2.0] - 2026-09-27

Refs [#10](https://github.com/cooneycw/skillc/issues/10) (a real Docker
trial end to end, now closed) and [#80](https://github.com/cooneycw/skillc/issues/80)
(the support matrix restated from that run, now closed). The operator ran `skillc demo`,
`--control` and `--subject` for both collections on a real Docker daemon at
commit `8e06030`: all four commands exited `0`, every acceptance item read
`MET`, and the three seeded `--control` failures were all caught (evidence:
[#10's live-run comment](https://github.com/cooneycw/skillc/issues/10#issuecomment-5855368984),
restated in [support-matrix.md](docs/specs/evaluation-facility/support-matrix.md)
and the coverage ruling in
[ADR 0005 rule 6](docs/decisions/0005-runtime-scope-and-cost-rulings.md)).
That run covers `skillc demo`'s own scripted lifecycle proof, grading run
and three seeded negative controls on a real daemon - not an independent live
re-run of every case in the conformance table or failure-path matrix, most
of which stay proven against the fake `docker` CLI, per the owner's own
ruling; the two paths judged most likely to differ on a real daemon
(timeout, operator cancellation) are tracked for a real-daemon seed under
[#122](https://github.com/cooneycw/skillc/issues/122). [#11](https://github.com/cooneycw/skillc/issues/11) (a second
independent collection) also closed in this release: the operator's live
Level 1 agent run, once per collection with the same codex client, fixture,
contract and grader, captured and graded `PASS` for both `cpp-codex` and
`mattpocock-skills` (evidence: [evals/second-collection-conformance/evidence/README.md](evals/second-collection-conformance/evidence/README.md)). By owner ruling recorded
on #11, the agent container runs on the bridge network; the grading
container stays `network=none`. Still owed: the Claude Code agent arm under
[#124](https://github.com/cooneycw/skillc/issues/124), skill-selection measurement
under [#26](https://github.com/cooneycw/skillc/issues/26), and the judge-call
cost ceiling under [#12](https://github.com/cooneycw/skillc/issues/12).

### Fixed

- **`skillc collection-run` could not complete a real agent attempt: no
  network, a refused workspace, a 30-second agent limit, and colliding
  scratch paths** (Refs #11): all found on the first live runs, none of
  which reached a model. The trial machinery reported every one truthfully,
  as `inconclusive` and never graded.
  1. The agent container ran `--network none` (the `DockerBackend`
     default), so codex could not reach its provider. By owner ruling,
     recorded on #11, the agent container now runs on the bridge network
     (`collection_conformance.AGENT_NETWORK`, with a reversal trigger). The
     grading container keeps `network=none`. `DockerBackend.describe()` no
     longer lists "network egress actually blocked" as a claim for an open
     network, and the paste-back prints `agent_network=`.
  2. The default `--client-argv` lacked `--skip-git-repo-check`, and codex
     refuses the non-git `/work` without it.
  3. `--timeout` (30 s) bounded both each docker call and the agent. The new
     `--agent-timeout` (default 900 s) bounds the agent.
  4. Fixed `<base>/<subject>-checkout|-staging|-store` paths made a re-run
     of the same subject fail at `git clone`. Each run now gets its own
     directory, and its checkout and staging copies are removed.

  Each fix has a test that fails without it. The live evidence is in
  `evals/second-collection-conformance/evidence/README.md`: both collections
  were captured and graded PASS, and the missing-credential control was
  `unavailable`.

- **`skillc demo` on a real daemon: a traceback leaked host paths, a fixed
  scratch path collided across runs, the exit-code contract was broken, and
  two acceptance items were vacuously MET** (Refs #118, Refs #81, Refs #10,
  Refs #101): found on the operator's first live run of `skillc demo`
  against a real Docker daemon - the image build failed, and that alone
  exposed four independent defects.
  1. `demo --control` and `demo --subject <name>` died with an uncaught
     `BackendUnavailable` from `DockerBackend.prepare()` in `run_control`
     and `run_subject_demo`, and the raw traceback printed the operator's
     own home directory and username - "the paste-back is leak-checked
     before printing" held only on the happy path. Both call sites now
     catch the failure and report it through the normal, leak-checked
     result (a NOT-EXERCISED `SubjectResult` for the subject leg; the
     seeded orphan read as NOT caught for `--control`, never a raised
     exception). `skillc/cli.py`'s `cmd_demo` also gained a top-level
     `except Exception` guard - a second, independent layer - that scrubs
     ANY unanticipated exception through `demo.describe_error_safely`
     (replaces the message with the exception's type name alone if the
     message itself fails its own leak-check) before printing one line to
     stderr, never a traceback. Also found in review: `PasteBackRefused`'s
     own message is built from `leak.scan_text`'s findings, which NAME the
     leaked value found - `cmd_demo` printing `str(exc)` for that specific
     exception would have been the exact leak this whole mechanism exists
     to prevent, one level up; it now prints a fixed, generic message
     instead.
  2. `--subject` cloned into a FIXED `base / "subject-checkout"` path - a
     second run against the same `base` (the operator's own sequence: the
     first crashed before cleanup) could be handed a directory an earlier,
     hard-crashed process had already touched and never got to clean up.
     `run_subject_demo` now uses a fresh `tempfile.mkdtemp` per call for
     both the checkout and the staging directory, removed in `finally` -
     never a name any other call, past or concurrent, could already hold.
  3. The exit-code contract (the runbook's own `0`/`1`/`2` meanings) was
     broken: a refused subject exited `2`, which the runbook reserves
     exclusively for a leak-check refusal. `SubjectRefused` (along with
     everything else the top-level guard now catches) exits `1` - "could
     not run" - never `2`.
  4. With no image reachable at all, `demo` correctly reported the lifecycle
     as unavailable and grading as inconclusive, but still reported `[MET]`
     for "cleanup sweep confirms no owned container left running" and
     "declared host paths unchanged" - true only because nothing ever
     started, not a real claim about a demo that ran. `AcceptanceItem`
     gains an `exercised` flag; both main-demo items read `NOT EXERCISED`
     (never `MET`) whenever the lifecycle leg's own disposition is
     `"unavailable"`, and all five of a not-exercised subject leg's items
     read the same way, with the failure reason as evidence.

  Every item has a mutation-confirmed test reproducing the operator's own
  symptom before the fix: a raw exception (with a planted home path)
  propagating uncaught through `cmd_demo`; the seeded orphan step raising
  instead of reading as not-caught; a second `run_subject_demo` call
  failing when handed a directory a simulated prior crash left non-empty
  at the old fixed path; `SubjectRefused` exiting `2`; and both "vacuous
  MET" items reading `MET` against a trivially-clean (nothing happened)
  reap report and host diff.

  Independent review of the fix itself found three more real gaps, folded
  into the same PR before merge:
  - `KeyboardInterrupt` is a `BaseException`, not an `Exception` - the
    top-level guard never saw it, and Ctrl-C on a slow real daemon is
    exactly what an operator does, so #118's leak came back through that
    one route (Python's own default traceback, naming the installed
    `skillc` paths). `cmd_demo` gains its own `except KeyboardInterrupt`:
    a fixed line, no exception text at all, then a best-effort cleanup
    sweep.
  - The acquisition-failure catch around `acquire_subject_checkout(...)`
    was itself untested - every existing test either supplied an explicit
    `checkout=` (bypassing acquisition) or monkeypatched the function away
    entirely, so deleting the catch left all 56 tests green. A new test
    makes the underlying `git clone` SUBPROCESS call fail for real,
    exercising the function's own exception-wrapping.
  - `describe_error_safely` only scrubbed what `leak_check_text` recognises,
    and that check's home-path pattern only matches `/home/<user>/...` - a
    checkout under `/opt`, `/srv`, or any non-`/home` layout sailed through
    completely unscrubbed (reproduced live: an unreadable `subject.json`
    outside `/home` printed its own absolute path, twice, unscrubbed).
    `demo.redact_known_host_paths` replaces every occurrence of a host path
    this process already knows (`REPO_ROOT`, `Path.home()`,
    `tempfile.gettempdir()`, the run's own `base`) with a generic
    placeholder, longest match first, BEFORE the leak-check ever runs - in
    both `describe_error_safely` and the two places `run_subject_demo`
    builds a `not_exercised_reason` that flows into the paste-back. The
    leak-check remains the second, independent layer for anything this
    substitution does not name; `leak.py`'s own pattern was deliberately
    left unwidened, since a bare "any absolute path" rule would
    false-positive on legitimate container paths like `/work` and
    `/home/candidate`.

  A second review pass, against a real SIGINT this time, found the interrupt
  sweep above still wrong: its first cut used `reap.reap_all_owned` - every
  skillc-owned container on the daemon, regardless of which run started it -
  and it reaped a container from an unrelated, concurrent attempt.
  `reap_all_owned` is removed (nothing else called it); `cmd_demo` now builds
  a `recorded_attempt_ids` list before calling `run_demo`/`run_control`, and
  each records its own attempt id the instant it exists - before the backend
  call that could hang - so the interrupt handler can scope the sweep to
  `reap.reap(docker_bin, recorded_attempt_ids, ...)`, the existing,
  already attempt-scoped function, and sweep nothing at all if nothing was
  recorded yet. Confirmed red against the removed function: two owned
  containers, one carrying a recorded attempt id and one foreign; after the
  interrupt the foreign one survives and only the recorded one is reaped,
  which fails on the host-global sweep (both are gone there).

### Added

- **`skillc collection-run <subject>` (issue #11's remaining acceptance
  bullet, "the same client, Level 1 fixture, contract and grader")**: one
  real agent attempt against `evals/level1/slug-small-fix`, per declared
  skill collection (`cpp-codex`, `mattpocock-skills`), driven through
  `skillc/agent_trial.py` (#106) in `agent_trial.py`'s skill-free canary
  mode (issue #26: the instruction names no skill, so any skill the agent
  invokes on its own is an observation, never an artifact of the prompt).
  `skillc/agent_trial.py`'s `run_one_attempt` gains a new `extra_home_files`
  parameter that delivers a declared collection's own selected skill files
  into the SAME container the agent runs in, alongside the credential and
  seed - reusing `demo.load_demo_subject`/`materialize.acquire_snapshot`/
  `demo.subject_surface_files` (issue #101) rather than a second
  subject-loading path. The prompt and starting fixture default to the
  task's own fixed data (`goal.md` verbatim, `fixture/src/` only - never
  the sibling `fixture/expected.json`, the grader's own ground truth for
  it). Paste-back per collection: `disposition`, `prompt_delivered`,
  `canary_satisfied`, `graded.status`, `refresh_observed_in_container`,
  `skill_invocations`, `skill_invocation_detection`. Missing-credential
  control: `disposition == "unavailable"`, BLOCKED before any container
  launches. Structurally unable to launch a real agent without
  `SKILLC_ALLOW_REAL_AGENT=1` (`lifecycle.py`'s own existing guard; this
  command adds no gate of its own), funded per
  [ADR 0005](docs/decisions/0005-runtime-scope-and-cost-rulings.md) rule 6
  ("Normal Claude and codex" - the operator's own subscription login, not
  metered spend). Built and proven entirely against the fake `docker` CLI
  (`skillc/collection_conformance.py`, `tests/test_collection_conformance.py`);
  the operator's own real run is still owed, exactly like every other
  real-Docker leg in this repository.

- **`tests/conftest.py`: no test can reach a real credential by default**
  (Refs #106): cross-model review of PR #117 found that a test passing
  `credential_explicit_path=None` with no override of its own resolved and
  READ the operator's real Claude subscription credential on the host that
  ran it - `credential.resolve_path` did exactly what it is documented to
  do (fall through to the standard, documented location), and that location
  happened to hold a real, live credential on that particular machine. CI
  (no real credential at that path) failed the test; the local run passed
  it, silently. Nothing was committed, but a suite able to reach a real
  secret at all is a standing hazard independent of whether a run actually
  leaks one. `_no_real_credential_defaults`, autouse for every test, points
  `HOME` and `CODEX_HOME` at fresh empty per-test directories and sets both
  named credential env-var overrides to explicit, guaranteed-nonexistent
  paths - set, not merely deleted, so an ambient export from an unrelated
  shell session cannot leak through either. `tests/test_conftest_hermeticity.py`
  proves it both ways: `resolve_path(client, explicit=None)` refuses for
  every client under the fixture, confirmed red (found the real credential,
  did not raise) when the fixture's own body is disabled on the exact host
  that produced the original leak; and a second test proves the underlying
  check CAN see a reachable default when one is deliberately planted at the
  standard location with the redirect undone - the positive control for the
  first. The one offending test in `test_agent_trial.py` now passes an
  explicit fake credential like every other test in that file.

- **`agent_trial.py` exposes which skills a real attempt actually invoked,
  and a skill-free canary mode** (Refs #106, Refs #26): found while wiring
  #26's run driver against the real, merged interface - `record` exposed
  only whether ONE pre-named `skill_name`'s own canary fired, never which
  skill(s), if any, a transcript actually showed invoked. The events
  `_make_observe_before_teardown` already parses to check that canary were
  computed and discarded every time; a selection probe with two applicable
  skills (or zero, for its near-miss/baseline arms) cannot be answered by a
  single yes/no about one pre-chosen name at all. `TranscriptObservation`
  gains `skill_invocations` (every invoked skill's name, in order, empty
  when no single transcript file was found) and `skill_invocation_detection`
  (`"structural"` for Claude Code's dedicated `Skill` tool call,
  `"heuristic"` for Codex's SKILL.md-read inference, #107) - both flow
  through to `record["observation"]` unchanged for every existing caller.

  Second, sharper finding: the existing canary instruction names the skill
  it wants invoked ("invoke the '<skill>' skill, then..."), which is prompt
  contamination for a SELECTION probe - every "selected" result would be an
  artifact of the instruction, not a measurement of what the agent chose.
  `skill_name` is now optional through `run_one_attempt`,
  `compose_canary_instruction` and `check_agent_canary`: `None` composes an
  instruction naming no skill at all (only the tool write), and the canary
  then requires just a confirmed, error-free tool use - selection becomes
  purely what `skill_invocations` observes, never a canary requirement.
  The named-skill mode (#106/#107's own liveness proof) is unchanged; #26
  and #12 use skill-free mode.

  `tests/fixtures/agent-trial/fake_agent_client.py` gains `--plant-skill`
  (repeatable), letting a test control which skill(s), if any, the fake
  transcript shows invoked independently of the prompt's own named skill -
  defaults preserve every existing test's behavior exactly (the prompt's
  named skill in named-canary mode, none at all in skill-free mode). Every
  acceptance path has a mutation-confirmed test: a skill name leaking into
  the skill-free instruction, a failed tool call still refusing in
  skill-free mode, `skill_invocations` collapsing to empty, and
  `skill_invocation_detection` collapsing to one value for both clients each
  turn a passing suite red.

- **`skillc demo --subject <name>`: install a declared skill collection into
  a real container's home, re-check its digests in-container, and observe
  the client's own discovery of it** (Refs #101, Refs #11, Refs #81, Refs
  #10): a THIRD demonstration, alongside (never replacing) the lifecycle and
  grading demos - #97's own removed narrower flag only materialized a local
  snapshot, which would have misled the operator about what `--subject`
  actually proves. This version acquires the collection from its pinned
  revision via a real `git` clone forced to that exact commit
  (`acquire_subject_checkout`), then hands the checkout to
  `materialize.acquire_snapshot` - never `materialize.acquire_git`, whose own
  git-archive verification needed a real `git` binary inside `materialize.py`
  itself and made this module's tests require one too, undetected locally
  (where `git` is always present) until Woodpecker's own gate image
  (`python:3.12-slim`, no `git`) turned 7 tests red with `FileNotFoundError:
  'git'` - cross-model review caught it, and the fix is git-free tests, never
  a skip: `tests/fixtures/` gained a plain, committed skill-collection
  fixture the tests materialize from directly, no git repository involved.
  Known, accepted tradeoff of snapshot mode: the acquired `Source`'s own
  `revision` reads `snapshot:<digest>`, never the real commit SHA - so the
  paste-back's `revision` is read from the subject's own DECLARED pin
  instead, never from acquisition mechanics. Also closes a second review
  finding: `_subject_acceptance_items`'s discovery check redundantly gated on
  `discovery_reason is None` alongside its own `all(... == "discovered")`
  clause - redundant given `run_subject_discovery`'s own invariant, but
  `SubjectResult` enforces neither by construction, so a directly-constructed
  input combining "discovered" with a set reason went undetected by every
  existing test; a mutation-confirmed test now covers it as defense in depth.
  And a third: `attempt_id` for this leg's container was `subject-<name>`,
  colliding across concurrent runs of the same subject - now
  `subject-<name>-<nonce>`. Copies every selected skill's files into
  `/home/candidate/.codex/skills/<dir>/...` one
  `DockerBackend.deliver_home_file` call per file (never bind-mounted), reads
  every installed file's bytes back out of the running container and
  re-hashes them (`matched`/`mismatched`, naming the file), and runs the
  client's own listing (`codex debug prompt-input`, the same argv convention
  `skillc.exposure`'s Codex arm already uses) INSIDE the container via
  `execute()` - never `materialize.run_client`'s host-local subprocess,
  which never touches a container at all. A listing that cannot complete at
  all reports every selected skill `UNMEASURED` with the reason, never
  dropped, and flips the exit non-zero. `materialize.inventory`'s own check
  refuses a `--subject` whose `select` names a skill absent from the source
  before any Docker work starts. Every acceptance item has a committed red
  case that flips it to NOT MET, confirmed against the exact mutation that
  would otherwise leave it blind - #97 shipped three items no test could
  fail; this one does not repeat that. The default subject name is read from
  `evals/subjects/DEFAULT_SUBJECT` (data), never a literal, so the
  genericity guard (#94) has nothing to flag. Extended the fake `docker` CLI
  fixture's absolute-path remapping to cover `CONTAINER_HOME`
  (`/home/candidate`) as well as `CONTAINER_WORKSPACE`, and as a substring
  inside a larger token (`env CODEX_HOME=/home/candidate/.codex ...`), not
  only a whole-argv-element match - needed once an exec'd argv referenced the
  container's home rather than its workspace for the first time. The runbook
  gains a `--subject` section with the required "what this shows and does
  NOT show" text verbatim, and a table of each subject's pinned revision and
  install location.
- **`skillc/agent_trial.py`: the agent trial driver, one real-agent attempt
  end to end** (Refs #106): composes the subscription credential (#98), the
  per-trial home and onboarding seed (#78), the real transcript - discovered
  via a new `DockerBackend.read_home_tree` (bounded, in the spirit of #102;
  a missing directory is an empty result, never an error, since neither
  client's transcript filename is known in advance) and normalized through
  the per-client adapter (#107) - and grading through `verify.grade_files`
  with a SEPARATE backend instance (interfaces.md's step 8). Wires into
  `lifecycle.run_through_backend`'s two new hooks: credential delivery and
  seed composition happen in `before_execute` (a failure BLOCKS the attempt
  before `execute()` ever runs); reading the transcript and credential back,
  and checking prompt delivery and the liveness canary against them, happens
  in `observe_before_teardown` (a failure is recorded as an unknown
  observation, never blocking the attempt itself). Grading is a separate,
  later gate this module owns on top of `lifecycle.py`'s own disposition -
  a captured-but-unconfirmed attempt (prompt-delivery mismatch, or an
  unsatisfied canary) is real data, kept in the record, but never handed to
  the verifier.

  ONE nonce and ONE instruction serve both of the canary's independent
  proofs, not two (cross-model review: minimizing prompt contamination in
  the very behaviour being measured) - `lifecycle.run_through_backend` gains
  an optional `nonce` parameter so a caller composing a real agent's prompt
  (fixed as part of `argv`, before that function ever runs) can supply the
  SAME nonce the backend will independently plant and verify via its own
  file-content canary after `export()`. `trial_bootstrap.compose_canary_instruction`
  gains a `result_filename` parameter pointing the agent at that same file
  (`docker_backend.CANARY_RESULT_FILENAME`) instead of inventing a second
  artifact. A new `trial_bootstrap.check_agent_canary` answers the narrower,
  transcript-side question - a confirmed skill invocation plus a confirmed
  tool call, never inspecting output content, since neither a real Claude
  Code `Write` result nor a real Codex `exec` result echoes a written file's
  content (confirmed empirically, #107) - while `disposition == "captured"`
  already carries the backend's own content proof; named red case: the file
  can be correct while the transcript shows only a failed tool call or no
  skill invocation at all, and the transcript proof must still refuse. This
  closes the gap `skillc/demo.py`'s own docstring named as "real follow-up
  work, owed to a future issue" - that issue was #106.

  Structurally unable to launch without `SKILLC_ALLOW_REAL_AGENT=1`
  (`lifecycle.py`'s own existing guard, unchanged) and no real model call
  anywhere in `tests/test_agent_trial.py` (an AST scan of the test file's
  own argv-shaped literals, mirroring #96's judge test) - every test runs
  against the fake docker CLI and a scripted fake client
  (`tests/fixtures/agent-trial/fake_agent_client.py`) that writes a
  realistic transcript for each client format and reads back a `--home`
  path, since the fake CLI runs a real host subprocess with no chroot. A
  full happy path grades PASS against the real, certified
  `evals/level1/slug-small-fix` task, reading the exported candidate from
  the attempt's frozen, content-addressed evidence
  (`trial.frozen_artifacts`) rather than a live workspace directory -
  `run_through_backend` removes the raw workspace unconditionally before
  returning, so nothing else is reachable by the time a caller gets the
  record back. The record and the transcript are both leak-checked
  (including the credential-token class, #98/#105), with a committed
  planted-token negative control proving the check is not vacuous.

- **`lifecycle.run_through_backend` gains two generic, optional hooks,
  `observe_before_teardown` and `before_execute`** (Refs #106, split of the
  agent trial driver's own PR): `observe_before_teardown` runs once, after
  `confirm_stopped()` and before `export()`/`destroy()` - while the
  backend's resources are still alive, which matters because `export()`
  structurally cannot reach a container's home directory. `before_execute`
  is its symmetric counterpart on the OTHER side of the attempt - after
  `install()` succeeds and before the liveness baseline/`execute()` - for
  the same structural reason: `install()`'s own `surface` argument can only
  ever reach `CONTAINER_WORKSPACE`, never a backend's home directory, so
  delivering something there (a credential, #98) has no other seam to run
  from. `lifecycle.py` itself stays subject-agnostic throughout: both hooks
  are plain callables with no knowledge of clients, transcripts, or skills.
  `observe_before_teardown`'s result is recorded verbatim under the
  returned record's `observation` key, and a raise there never blocks
  teardown - the record instead carries `{"status": "unknown", "reason":
  str(exc)}` under the same key. `before_execute`'s failure is NOT
  survivable in the same way: nothing has been dispatched yet, so a raise
  there reuses the exact same `unavailable` path `install()`'s own
  `BackendUnavailable` already takes - the attempt is finalized
  `unavailable` with the hook's exception as the reason, and `execute()`
  never runs; teardown still happens regardless. Omitting either argument
  (every existing caller) changes nothing - both records stay
  byte-identical to before these parameters existed, confirmed by dedicated
  tests and by four hand-verified negative controls (an unhandled
  `observe_before_teardown` exception; an always-present `observation` key;
  an unhandled `before_execute` exception; and the guard that stops
  `execute()` from running after a `before_execute` failure) - each made
  the guarantee fail on cue before restoring the real code. The actual
  client-specific implementation (credential + seed + transcript-adapter +
  canary via a container read-back) is `skillc/agent_trial.py`, a separate
  PR still to come under the same issue.
- **The trial image had no `python3`, undetected by any existing check**
  (Refs #78, Refs #81, Refs #10): `skillc-trial`'s Dockerfile only
  apt-installed `ca-certificates` and `git`, while `skillc.verify.PROBE_INTERPRETER`
  and `skillc.demo`'s scripted lifecycle subject both invoke `python3` inside
  the container - every check that would have caught this ran against the
  fake `docker` CLI, which never looks inside an image. Fixed by
  apt-installing the full `python3` package (not `python3-minimal`, whose
  stdlib subset could not be verified against a real daemon from this
  session). `docker/trial/check_interpreters.py` is the committed, no-daemon
  control: it parses the Dockerfile's own apt-get install list as text and
  refuses when a required interpreter (derived from `skillc.verify.PROBE_INTERPRETER`,
  never a second hardcoded literal) is missing - confirmed red against a
  copy of the Dockerfile with `python3` removed before being added.
  `demo.py`'s own `python3` argv literals now reference
  `verify.PROBE_INTERPRETER` directly rather than duplicating it. The
  operator runbook gains a "Before you run" section (clone, `uv sync`, build
  the image) noting the build itself is one of #78's own live checks
  (`verify_codex_sidecar.js` fails the build, never a later trial, if the
  Codex sidecar is missing), and its stale "why no real agent" paragraph is
  updated for #106's transcript adapters.

- **Per-client transcript adapters, grounded in real transcripts rather than
  guessed** (Refs #106, split 1 of 2 - the driver loop itself is a separate
  PR under the same issue): `skillc/transcript_adapter.py` translates a real
  Claude Code transcript (`~/.claude/projects/.../*.jsonl`) or a real Codex
  rollout (`~/.codex/sessions/.../*.jsonl`) into the normalized event shape
  `skillc/trial_bootstrap.py`'s `verify_first_user_message`/`check_canary`
  already consume. Every shape implemented was read directly from a real
  Claude Code transcript and three freshly-run, live `codex exec` transcripts,
  never invented from documentation alone - the same discipline that caught
  #98's credential-schema bug. Notable findings folded into the design: a
  real Codex transcript's first `user`-role message is always a
  harness-injected `<environment_context>` wrapper, never the real prompt,
  and must be skipped; a real Codex tool result carries no explicit
  success/failure field at all, only a doubly-JSON-encoded `exit_code`
  embedded in one of its own output blocks; and Codex has no distinct
  "skill invocation" transcript event the way Claude Code's dedicated
  `Skill` tool call does, so that detection is a named, explicitly
  best-effort heuristic. An undeterminable result (an unparseable exit code,
  a non-`exec` tool call with no observed success convention) is always
  treated as a failure, never assumed successful. Hand-verified negative
  controls confirm three real regression classes: assuming every Codex
  `exec` call succeeded, skipping the environment-context filter, and
  ignoring a Claude Code tool result's `is_error` flag - each sabotaged,
  confirmed red on the exact test it should break, restored, confirmed
  green. What this does NOT do, stated in the module's own docstring: pair a
  tool call's confirmed result with a live file read-back, which needs a
  running container and is explicitly the driver-loop half's job, not this
  one's.
- **A trial container carries the operator's subscription login, never a
  long-lived key, never mounted or exported, with a leak-check for token
  material** (Refs #98, Refs #10): the owner's ruling, quoted verbatim (from
  issue #98), is that agent runs use "Normal Claude and codex" - the
  operator's own Claude Code and Codex subscription logins, inside the
  normal usage budget, not metered spend and not a cloud secret store.
  `skillc/credential.py` resolves exactly one documented standard location
  per client (an explicit path, then a named environment variable, then the
  client's own standard file), refusing rather than scanning a home
  directory for one it wasn't told about; reads it fresh on every trial,
  never caching a copy; and refuses to start a trial whose access token's
  remaining life is below a stated threshold (or cannot be determined at
  all - including a `NaN`/`Infinity`/boolean expiry value, which Python's
  own JSON parser otherwise accepts silently), because a refresh happening
  INSIDE the container can rotate the refresh token and invalidate the
  operator's own host copy, with no write-back protection here. Codex's own
  `~/.codex/auth.json` has no `expires_at` field anywhere at the path this
  module first guessed at - found by cross-model review against a real file
  on the host, which would have made a genuine fresh Codex login always
  read as undeterminable and always refused; the expiry now comes from
  decoding the `exp` claim of the JWT already sitting at
  `tokens.access_token`. `docker_backend.DockerBackend.deliver_home_file`
  copies the credential into the candidate's home directory (never `/work`,
  never a bind mount, never baked into the image, never in argv) using the
  same candidate-owned tar-stream mechanism `install()` already uses for the
  workspace; because `export()` only ever reads from the workspace, a
  credential delivered here cannot appear in an exported trial BY WAY OF
  `export()` itself - narrower than "can never leak into an export": a
  running candidate process can still read its own home directory and copy
  those bytes into the workspace on purpose or by accident (cross-model
  review), which is exactly why the leak-check below scans exported content
  independently rather than relying on delivery placement alone; a
  committed red case proves the copy-out case does reach export.
  `read_home_file` is the read-side counterpart, letting a caller observe
  (when it chooses to compare) whether an in-container refresh changed the
  delivered bytes before `destroy()` discards the container and the fact
  along with it - documented as a byte-difference signal, not proof of a
  real token rotation, since any rewrite of the file reports the same way
  (`credential.refresh_observed`). `CredentialUsage` builds a record's
  fields from what the caller already knows (the client, "subscription",
  whether delivery succeeded, whether a refresh was observed) and has no
  field a token value could occupy. `skillc/leak.py` gained a fifth
  detection class, an OAuth-shaped token value or a recognizable API-key
  prefix, each requiring the actual value rather than a bare field name; a
  finding never repeats the matched value itself, so the detector does not
  create a second copy of a real secret at the moment it detects one
  (cross-model review). A committed planted-fake-token fixture pair
  (plain text, not JSON - an earlier JSON-wrapped version force-escaped its
  own quotes and left the OAuth half of the pair silently undetected, also
  found by cross-model review) proves it discriminates, checked for both
  patterns independently. Checking whether the operator's own HOST login
  still works after a trial is explicitly NOT done here; that is owed to the
  operator's own live run, for both clients, as issue #98 states.
- **The second-collection conformance manifest states its own scope boundary
  and the owner's funding ruling explicitly** (Refs #11): review found the
  manifest needed to say plainly that its own two runs - installation,
  discovery, an in-container digest check - satisfy acceptance bullets 1
  and 3 but NOT bullet 2 ("the same client, Level 1 fixture, contract and
  grader"), which needs an agent actually working Level 1 with each
  collection installed. Added
  `acceptance_status` (bullet-by-bullet, plus what remains after this
  manifest's own runs execute) to `run-manifest.json`, with a test proving
  it says so. That remaining agent run's funding basis is quoted verbatim,
  not paraphrased: the operator's ruling ("Normal Claude and codex") puts it
  on the normal Claude Code/Codex subscription login, inside the normal
  usage budget - NOT metered spend, and NOT gated by the #12 $5 cost stop
  (which covers judge calls only). Also corrected: `--subject` is being
  split out of PR #97 into its own follow-up PR under #11 (PR #97 carries
  an earlier, materialize-only shape built before the fuller install+
  discovery+digest design was settled, and is not being widened to match
  it) - the manifest previously attributed the flag to #81 directly.
- **The second-collection conformance run, prepared** (Refs #11):
  [`evals/second-collection-conformance/`](evals/second-collection-conformance/README.md)
  states the exact command per subject (`skillc demo --subject cpp-codex`,
  `skillc demo --subject mattpocock-skills`), against the fuller
  install+discovery+digest-check design for `--subject` (materialize the
  named subject, install it into the real container via
  `DockerBackend.install()`, observe client-side discovery with no model
  call) that a follow-up PR under #11 will deliver - PR #97's own
  `--subject` is host-materialize-only today, and this manifest states
  that distinction explicitly rather than conflating the two. The expected
  paste-back shape per subject (an installation-receipt summary matching
  each subject's already-recorded host evidence, plus a `discovered` field
  explicitly marked `owed to the follow-up` rather than invented), and the
  bounded compatibility statement #11's own text asks for - what is and is
  not shown compatible between the two collections. Cites, rather than
  re-proves, two acceptance bullets already closed by existing work: no
  project-name branch (the genericity guard, #94) and unsupported formats
  refused before selection (`test_a_malformed_subject_declaration_is_refused`'s
  10 parametrized cases, generic to both subjects). Prepared, not run - like
  the matched pilot (#12/#89), execution needs a capability (#81's demo,
  #10's live daemon) that does not exist yet. Cross-model review found a
  real overclaim (the compatibility statement blurred "materialize.py was
  actually run against both subjects" together with "trial.py/verify.py/
  docker_backend.py carry no subject-name branch" into one "proven end to
  end" claim - only the first is execution evidence, the second is a static
  guarantee, and neither shows a full trial has ever run for either
  subject; rewritten to keep the three kinds of claim separate), an
  arithmetic error (11 model-invoked skills total, of which 2 are selected,
  leaves 9 unselected, not 11), and a vacuous-pass bug in the new test
  (`"" in summary` is `True` unconditionally, so an empty evidence
  observation would have passed silently - fixed with an explicit
  non-empty check and its own negative control).
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
- **The operator demo command** (#81, Refs #10, #10 closes only on the
  operator's own live run of this command, never on CI green): `skillc demo`
  drives two independent, real-Docker-backed demonstrations through the
  merged `DockerBackend` (#77) with no paid model call - a scripted-subject
  lifecycle proof via `lifecycle.run_through_backend`, and a real grading run
  via `verify.grade_files(..., backend=...)` against the already-certified
  `evals/level1/slug-small-fix` task. It snapshots the fleet and a fixed set
  of host paths before and after, reaps its own attempt(s), and reports the
  four distinct outcomes (`reaped`/`already-absent`/`left-running`/`unknown`)
  rather than collapsing them. The paste-back block it prints (skillc
  version/commit/dirty, per-item acceptance evidence, the image digest that
  actually ran) is run through `leak-check` before printing and refuses to
  print if it finds anything. `skillc demo --control` runs four seeded
  negative controls instead - a reply-only subject, a container deliberately
  left running, a known-bad grading candidate, and a leaky paste-back - and
  exits non-zero unless every one was caught. The transcript-based real-agent
  canary check (`trial_bootstrap.check_canary`, #78) is deliberately not
  wired into this command: a real `Write` tool result never echoes file
  contents, so that check cannot pass against a genuine transcript without an
  adapter that re-reads the file back, which is real follow-up work rather
  than something this issue's scope covers - `demo.py` uses `lifecycle.py`'s
  own file-content-based canary instead, which does not have that gap.
  Building this surfaced two previously-undiscovered integration bugs
  between already-merged #76 and #77: `DockerBackend.install()` silently
  dropped `bytes`-valued surface entries (verify.py's own probe-surface
  convention), and `DockerBackend.execute()` discarded the exec'd subject's
  stdout entirely instead of writing it back as `observations`
  (verify.py's documented convention for a probe-serving backend). Both are
  fixed, each with a regression test confirmed to fail on the pre-fix code.
  The fake docker CLI test fixture had a third, related bug of its own - it
  only remapped a `cwd=`-relative argv path into the simulated container
  filesystem, not an absolute one, and `verify.py`'s own probe-invocation
  convention always passes an absolute path - also fixed and regression
  tested. Cross-model review found the recorded image digest wasn't bound to
  the image either backend actually ran: it used to resolve after both
  demonstrations, so a mid-run rebuild or retag of the image tag would
  silently record the replacement instead - now resolved once, before either
  `DockerBackend` is created. The review also found two of `_acceptance_items`'s
  three checks were blind: dropping `reap_ok`'s `not reap_report.unknown`
  clause, or `host_ok`'s `not host_diff.unresolved` clause, or replacing
  `digest_ok` outright with `True`, left every existing test green. Three new
  tests, each confirmed red on its own mutation before being added, close all
  three. An earlier draft of this command also carried a `--subject <name>`
  flag materializing a second declared skill collection (#11) alongside the
  lifecycle/grading proofs; pulled back out before merge on review - it only
  materialized into a local snapshot rather than installing into the real
  container, which would have misled the operator about what the flag
  actually proved. The full version (real installation, in-container digest
  re-verification, client-listing discovery) is real follow-up work for #11,
  not silently dropped.

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
- **Subscription-login agent runs are not dollar-metered; judge calls still
  are** (Refs #26, Refs #12): [ADR 0005](docs/decisions/0005-runtime-scope-and-cost-rulings.md)
  rule 6 records, verbatim and dated, the owner's ruling that #26's and
  #12's agent attempts (treatment/baseline) run under the operator's normal
  Claude Code/Codex subscription login - the normal rotating OAuth login,
  never a long-lived key - not a pay-per-use API key, so their token/price
  figures are a usage quota, not a dollar charge. The ruling does NOT cover
  judge calls (`mcp-second-opinion`, #69, uses provider API keys and stays
  dollar-metered). `skillc.cost_estimate.RunCostEstimate` gains
  `judge_estimated_usd`, the judge-only slice of `estimated_usd`, and
  `authorize()` gains `agent_uses_subscription_login` (default `False`,
  fully backward compatible): when `True`, it gates on `judge_estimated_usd`
  alone rather than the combined total - a large agent quota needs no
  approved budget by itself, and a subscription-login run with no judge tier
  enabled needs no budget at all, while judge spend over the $5 ceiling is
  still refused regardless of the agent quota's size, exactly as before.
  Both `evals/selection-probe/run-manifest.json` and
  `evals/matched-pilot/run-manifest.json` (and their READMEs) record the
  ruling and relabel their agent-attempt figures as a quota/usage indicator,
  reference issue #98 (the in-container credential path) as the actual
  remaining prerequisite for a live run, and drop every private
  fleet-message-number citation the two files carried, replacing each with
  a reference to ADR 0005's own section - skillc is public, and a message
  number is a channel no outside reader can resolve. Two committed controls
  (`tests/test_cost_estimate.py`) prove the split: a plan with an enormous
  agent-side figure and under-ceiling judge spend is authorized, and one
  whose judge spend crosses the ceiling is refused regardless of the agent
  figure's size - each confirmed to fail on the pre-fix `authorize()`
  (temporarily reverted to gate on the combined total regardless of the new
  flag).
- **skillc stands alone: owner rulings are cited by ADR section, issue or PR
  - never a private fleet message number or a worker name** (#100): found
  reviewing PR #99, which does not itself carry the pattern in its tracked
  files - the same pattern was in its PR body and therefore its squash-commit
  message on `main`, which cannot be rewritten after the fact. [ADR
  0005](docs/decisions/0005-runtime-scope-and-cost-rulings.md) rule 6 gains
  the credential rule (the operator's normal, rotating, on-machine OAuth
  login, never a long-lived key - issue #98's comment thread), completing the
  three facts the rule needed recorded durably. The remaining `msg NNNN`/bare
  worker-name citations in tracked files (`skillc/lifecycle.py`,
  `skillc/provenance.py`, `skillc/verify.py`, and their tests, plus
  `docs/specs/evaluation-facility/verification.md`) are replaced with the PR
  whose review actually found the thing (`PR #70`, `PR #76`, `PR #88`) or,
  where the citation was a work-split note rather than a review finding, a
  plain description with no fleet identity attached. A new guard test
  (`tests/test_private_citations.py`) fails the whole suite if any git-tracked
  file (outside `docs/research/`'s dated historical documents and
  `tests/test_leak.py`'s/`tests/fixtures/leak_seeds/`'s deliberately-seeded
  examples) cites `msg NNNN` or a bare `w<digit>` token, with five committed
  controls including one built directly from a red case the guard's own
  construction surfaced: a citation split across a wrapped Python comment
  line (`skillc/lifecycle.py`'s own original text was exactly this shape) is
  invisible to a per-line search and to a naive newline-to-space join alike,
  because the second line's own `# ` marker still separates the two halves -
  the guard reconnects a citation by stripping each line's leading `#` before
  joining, and this same, more careful check caught a NINTH real offender
  (`skillc/verify.py:993`, a wrapped private-message citation) that an
  earlier manual `grep` sweep over the same tracked population had missed
  for the identical reason. Confirmed to fail
  against every one of the pre-fix files (reverted via `git checkout
  origin/main --`), then restored. `.github/PULL_REQUEST_TEMPLATE.md` (new)
  and README's Contributing section add the rule for PR bodies and commit
  messages, which a file-content guard structurally cannot see - the actual
  gap PR #99's review found. A `/codex:code_review` pass then found and fixed
  four more issues in the guard itself, each with its own committed red case
  confirmed to fail on the pre-fix version: the guard's own new test file and
  new PR template - whose committed examples and checklist wording must
  literally contain the forbidden pattern to describe or test it - were not
  excluded from the scan, so the guard would have failed CI on its own
  committed content forever (now excluded, for the same reason
  `tests/test_leak.py` already excludes itself from `skillc leak-check`); an
  empty or all-unreadable file population reported the same "clean" verdict
  as a real, fully-inspected one, so `_scan` now reports a separate
  `inspected` count the main test asserts is nonzero, alongside a
  minimum-tracked-file-count floor; a tracked symlink would have been scanned
  as its resolved TARGET's content, so an unrelated, untracked file could
  flip this guard's verdict without anything tracked changing at all -
  symlinks are now skipped, matching `skillc/leak.py`'s own handling of the
  identical hazard; and the single-file exclusion entries used the same
  prefix match as the directory entries, so `tests/test_leak.py.bak` would
  have been silently excluded alongside the one file actually meant - now an
  exact match for anything not ending in `/`.
  **Then found in PR review: the guard never ran in CI at all.** It was
  built on `git ls-files` and `pytest.mark.skipif`-skipped whenever `git`
  was not on PATH - true of the CI gate's own `python:3.12-slim` image, so
  both its real tests were silently skipped there (`tests/test_
  private_citations.py s..s.....` in the gate log) on this PR and every one
  after it: a gate that let work through and could not fail where it ran.
  Rebuilt on `os.walk` (sharing `skillc/leak.py`'s own `SKIP_DIRS` rather
  than a second list that could drift from it) - no external binary, so it
  needs no skip and none remains. Reproduced the reviewer's own manual proof
  with `git` unresolvable on `PATH`: a planted message-number citation in
  `skillc/reap.py` fails the guard, cleanly reverted, all nine tests green.
- **`DockerBackend.execute()` bounds captured stdout AND stderr instead of
  buffering either unboundedly** (#102, Refs #77): found by cross-model
  review of PR #97 (the operator demo command) - the stdout drain it added
  appended every chunk to an unbounded `list[bytes]`, so a subject writing
  continuously could exhaust the HOST controller's own memory before
  `Limits.timeout` ever fired, a resource-exhaustion path independent of any
  container-side memory limit. Orchestrator review of the stdout fix found
  the identical unbounded pattern one screen down, already there for
  stderr, and asked for the same class fix. `Limits` gains
  `max_captured_stdout_bytes`/`max_captured_stderr_bytes` (independent
  fields, default 8 MiB each, matching `skillc.trial.Limits.
  max_stream_bytes`'s own default for the same class of bound - a different
  dataclass of the same name for a different stage, not a shared config
  surface); `ExecuteResult` gains `stdout_truncated`/`stdout_bytes`, the
  latter the subject's bytes observed by the time the drain stopped waiting
  - not a guaranteed-EOF total (see "still owed" below). Stderr has no field
  of its own on `ExecuteResult` - `error` is already its only surface - so a
  truncated stderr is folded into `error` as an explicit
  `"(truncated, N bytes total)"` suffix rather than silently showing a
  capped prefix. The new `_BoundedDrain` (one instance per stream) keeps
  reading its pipe to EOF past the cap - discarding, never retaining - so
  the subject can never block on a full, undrained pipe: committed red
  cases write 200,000 bytes against a 100-byte cap on EACH stream and assert
  `reason == "exited"`, not `"timeout"`, with stdout's own case additionally
  confirmed to actually deadlock (`reason == "timeout"`) when the drain is
  mutated to stop reading at the cap instead of only stopping retention.
  `skillc/lifecycle.py` surfaces `observations_truncated`/`observations_bytes`
  on the record itself, not only the raw journal event - the same gap
  `signal` already had to be surfaced past `trial.finalize`'s fixed-key
  filter, closed here for a truncated stdout capture too (stderr's own
  truncation reaches the record through the existing `error`-surfacing path
  unchanged). Seven new tests (two stdout + two stderr in `docker_backend`,
  two in `lifecycle`, plus one for the stdout deadlock mutation) confirmed to
  fail on the pre-fix code first - the stderr case reverts cleanly to an
  unbounded `list[bytes]` and reproduces the unannotated, untruncated
  200,000-byte `error` string exactly. Still owed (Nit Store, skillc#20): the
  timed thread join before reading either drain's own state can't
  distinguish "the pipe reached EOF" from "we stopped waiting for it" - a
  descendant process holding a fd open past the parent's exit could
  understate either stream's reported byte count. Not introduced or
  worsened by bounding retention; pre-existing for both streams alike.

### Fixed

- A non-boolean criterion `mandatory` flag is refused, not silently dropped
  from the derivation (#37).
- `tests/` is inside `mypy`'s scope, with a control that plants a type error
  there and requires it reported (#19).
- The fixture pin is computed without needing a `git` binary at import time
  (#5 follow-up).
- `ci/typecheck-control.sh`'s scratch copy no longer races a parallel gate
  step's `__pycache__` writes, in either of the two shapes that raced on
  main: a rewritten `.pyc` reported as `file changed as we read it`
  (pipeline 209), and a `__pycache__` subdirectory appearing inside a
  directory `tar` was still archiving, reported against that directory
  itself rather than the file (pipeline 140). `find` now builds the exact
  list of `*.py`/`pyproject.toml` files mypy ever reads from the copy, so
  `tar` archives that fixed list rather than walking a tree whose entries a
  parallel step can still be changing (Nit Store, skillc#20; #73). A copy
  that genuinely fails - an unreadable source file - still fails the
  control; that case is now committed alongside the fix.
- `docker/trial/verify_codex_sidecar.js` resolves `@openai/codex`'s platform
  optional dependency the way `codex.js`'s own launcher does, not a bare
  `require.resolve()` from wherever the script happens to run. A real
  operator build failed at `Dockerfile:80` because the Dockerfile `COPY`s
  this script to `/tmp` and runs it from there, where a bare
  `require.resolve("@openai/codex-linux-x64/package.json")` walks up from
  `/tmp`'s own ancestry and never reaches a real npm global install -
  `codex.js` never hits this because it lives INSIDE the installed package
  tree. The fix asks `npm root -g` for the real global root, then resolves
  the platform package via `createRequire` scoped to `@openai/codex`'s own
  directory, exactly where npm nests an optional dependency of a globally
  installed package. #84's own test exercised only the wrong shape
  (`NODE_PATH` pointed straight at a flat fixture, which the real
  invocation never sets and no real npm install ever produces) - the
  rewritten fixture copies the script to a scratch directory unrelated to a
  correctly-nested fake global root and confirmed red on the pre-fix
  script for every case but one already covered. Cross-model review then
  found a second bug in the fix itself: `require.resolve(id, { paths })`
  does not confine its search to the given directory, it walks UP through
  every ancestor's own `node_modules` - so an unrelated `@openai/codex`
  sitting two directories above an otherwise-empty declared global root
  could still resolve, and this check could certify the wrong installation.
  Replaced that first hop with a direct path join against the exact
  directory `npm root -g` names, confirmed the ancestor-contamination case
  now refuses correctly, and confirmed the same case goes red again when
  reverted to the `require.resolve` form (#78, #10).

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
