# Changelog

All notable changes to skillc are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Dates are the day the
work landed on `main`, not the day a version is tagged - see
[#72](https://github.com/cooneycw/skillc/issues/72) for the release checklist
and version plan.

## [Unreleased]

- **`install()`/`export()` gain a `root` parameter; the gate-witness
  overlay gets two, with a candidate-write verification** (Refs #332,
  #334). #334's profile-closure delivery installs the real `flow-
  finish-gate.sh` under the agent's home directory (`CONTAINER_HOME`),
  but `apply_flow_check_gate_overlay()` could only ever see `CONTAINER_
  WORKSPACE` - `DockerBackend.install()`/`export()`/`_workspace_
  baseline()` had it hardcoded, so a live attempt's overlay call would
  refuse on every real run. Found integrating #334's call site.
  - `ExecutionBackend.install(handle, surface, root=None)`/`export(handle,
    dest, root=None)`: `None` means the backend's own default (`CONTAINER_
    WORKSPACE`, unchanged for every existing caller); Protocol-wide, with
    conformance stubs on `managed_backend.py` (refuses a non-default root
    outright - the remote protocol has no root concept yet, so silently
    honoring one would place content somewhere other than what the caller
    asked for) and every test fake.
  - **Two roots, not one, for the overlay** (orchestrator review: a
    single `root` would let the harness copy of the real script sit
    under the candidate's own home, where the subject could edit it and
    the controller would faithfully execute and record the edited
    version as genuine - "a laundering channel"). `apply_flow_check_
    gate_overlay()` now takes `subject_root` (defaults like `install()`/
    `export()` do) and a REQUIRED `harness_root`, a directory the
    candidate identity cannot write. The harness copy is placed via two
    new `DockerBackend`-only primitives - never through `install()`'s
    own candidate-owned tar convention, which exists precisely so a
    surface is usable BY the candidate:
    - `write_root_owned_file_in_attempt()`: `docker exec -u 0`, creates
      missing parent directories (root-owned, mode 0755), writes
      content with an explicit mode. Returns `True`/`False`, never
      raises.
    - `candidate_can_write_in_attempt()`: empirically tests write access
      AS the candidate uid (`docker exec -u CANDIDATE_UID … test -w`) -
      never inferred from mode bits alone. `True`/`False` only on a
      clean result (no stderr); `None` (unreachable, timeout, or ANY
      stderr output) means unverifiable.
    - The overlay writes the harness copy, then REQUIRES a confirmed
      `False` from `candidate_can_write_in_attempt()` before placing the
      shim - `True` or `None` both refuse (`OverlayRefused`), since an
      unverified harness copy is not evidence of protection. The shim
      only replaces the real script at `subject_path` AFTER this passes,
      so a refusal leaves the real script exactly where it was.
  - `tests/test_gate_overlay_live.py` updated to match production:
    `SUBJECT_ROOT = CONTAINER_HOME`, `HARNESS_ROOT = "/opt/skillc-
    harness"` - a bare `python:3.12-slim` has no candidate home by
    default, so the test creates it directly before installing anything
    there, matching the one setup step #334 would already have
    performed in a real attempt.
  - Mutation-checked: `tests/test_gate_overlay.py` gains cases for a
    writable harness destination (refused, exercised for real against
    the fake CLI's own unenforced permissions - see its module
    docstring), an unverifiable (`None`) one (refused, monkeypatched -
    the fake CLI cannot produce a confirmed `False` either way, so the
    happy path needs the same monkeypatch), a failed root-owned write
    (refused), and two red cases proving the `is not False`/only-`True`-
    refuses distinctions actually matter (a naive version that only
    refuses literal `True` would wrongly accept `None`).
  - `tests/fixtures/docker-backend/fake_docker.py`'s `cmd_exec` gains
    `-u UID` parsing (consumed, not enforced - this fixture has no real
    per-uid permission model, same limitation `wrong-uid`'s own live
    test already states for itself).

- **A `discrimination-declaration` kind in `skillc.calibration`, for the
  intact-vs-degraded contrast** (Refs #287). `parse_declaration` cannot
  express this: it requires exactly one arm literally named `baseline` with
  a null subject, and a 3-arm declaration's two treated arms must share an
  identical subject, which a degraded arm's revision never does.
  - Arms are exactly `intact` and `degraded`. The degraded arm's
    `subject.revision` is derived from the intact subject's own pin via
    `skillc/degrade.py`'s own `_degraded_revision` (reused by import,
    `degrade.py` untouched) - a hand-typed label is refused.
  - The derived label is content-independent (verified directly), so the
    degraded arm also carries `mutation.mutated_digest` (sha256 of the
    resulting degraded file), bound into the approval exactly like
    `attempts_per_arm` (#323's pattern) - a changed `removed_text` under a
    stale approval is refused through the digest, not the label.
  - Reuses `parse_declaration`'s own shared/attempts/arm-order/task
    machinery (`_parse_schedule_and_identities`, extracted, not copied) and
    `require_approved`'s approval/grader-on-disk checks the same way -
    `parse_declaration`'s own behavior for `calibration-declaration` is
    unchanged (the full existing 127-test calibration suite still passes).
  - `tests/test_calibration_discrimination_declaration.py` (new): the
    red cases above, plus a hand-chosen arm order and the reused-helper
    regression guard.
  - Only `skillc/calibration.py` and its tests change; `records.py` and
    `controls/` are untouched (claude-power-pack #1369 pins 61 golden cases
    on them).

- **`exec_in_attempt()` gains `cwd`/`env`, confined per-request by the
  gate-execution witness** (Refs #332, #269, #183). In progress: the
  underlying mechanism for witnessing the subject's own `flow-finish-
  gate.sh` invocation. `ExecutionBackend.exec_in_attempt()` and the new
  `resolve_realpath_in_attempt()` (both added to the Protocol, with
  conformance stubs on every other implementer) let a caller run a
  declared gate at a caller-supplied working directory and under an
  explicit, declared environment (`docker exec -w` for cwd; `env -i` for
  environment, since `docker exec -e` only adds to the container's
  default rather than replacing it). `GateWitness` is the one place a
  subject-forwarded `cwd` is trusted or refused: it must resolve, via a
  REAL in-container `realpath` (never a string-prefix check on the
  unresolved input), to the attempt's declared `workspace_root` or
  somewhere below it - unresolvable, unconfigured, or outside the root
  (`cwd=/`, `cwd=../..`) all refuse before anything runs. `declared_env`
  is per-gate, declared by the controller exactly like `declared_argv`,
  never read from the subject. Mutation-checked: disabling confinement
  turns 5 tests red; dropping env-forwarding turns 1 red; both restored.
  - `docker/trial/flow-check-gate-shim.py` (new): the forwarding shim
    itself. Recognizes ONLY the two argv shapes `reference.md` prescribes
    (`--plan check --evidence flow-check`, `--check-summary`), maps each
    to its own pre-declared gate name, forwards its own `os.getcwd()` as
    the one dynamic input, and writes back the controller's real
    `exit_code`/`stdout`/`stderr` byte-for-byte - never synthesises a
    verdict of its own. Exits 125 (Docker's own "launcher failed"
    convention) on any channel failure, an unrecognized argv, or a
    missing real exit code (a refused/never-started gate) - deliberately
    not 2, which the real script already uses for a stale-helper
    mismatch (#581/#1366). `tests/test_flow_check_gate_shim.py` drives it
    as a real subprocess against a real `DecideReplyChannel`, same
    discipline as `test_skillc_disrupt_tool.py`.
  - **Decided against wiring the shim through `profile.json`** (orchestrator
    review): the profile declares what the SUBJECT needs; the shim is
    measurement apparatus the subject must never declare, and three
    successive `synthetic`-kind widenings (mode, satisfies, the
    unreferenced-reason requirement) to force it through anyway were each
    a sign the shim was in the wrong layer, not a sign `synthetic` needed
    extending - all three are reverted here. The shim instead becomes a
    harness OVERLAY applied after installation (baked into the trial
    image, same as #183 PR B2's `skillc-disrupt-tool`), never a profile
    dependency - the original `cpp-codex-flow-check-ea6dbfa` profile stays
    untouched at `841689b`.
  - `ci/real-docker/break-lib.sh` gains a third family, `gateshim:`, for
    the shim's own break modes (`synthesizes-output`, `drops-cwd`,
    `exits-zero-on-channel-failure`, `wrong-env`) - `resolve_break_spec`'s
    output widens from three lines to four (the normalized spec plus one
    explicit value per family, exactly one real and the other two the
    literal `"none"`, same always-all-present contract #315's own HIGH
    finding established), and `run-real-docker` now sets a third
    variable, `SKILLC_GATE_SHIM_LIVE_BREAK`, explicitly on every
    invocation. README step 8 lists all four new break-mode runs.
    Mutation-checked: removing the `gateshim` case entirely turns 5 tests
    red; restored, green.
  - `skillc/gate_overlay.py` (new): the overlay step itself.
    `apply_flow_check_gate_overlay()` runs as the LAST step of a live
    attempt's setup (skillc#334 tracks closing the separate gap - found
    while scoping this - that nothing currently installs the profile's
    declared dependency closure for a live attempt at all): it moves the
    real `flow-finish-gate.sh` to a harness-only destination and places
    the shim at the subject-visible path, reusing `ExecutionBackend.
    export()`/`install()` - no new backend primitive needed. BOTH
    digests (the real script's current content, the shim content handed
    in) are checked against caller-declared expectations BEFORE anything
    is written - orchestrator's own named red case ("an overlay that
    places a different shim than the declared digest is refused").
    `tests/test_gate_overlay.py` drives it against a real `DockerBackend`
    (the fake `docker` CLI, same discipline as `test_docker_backend.py`).
    Mutation-checked: dropping either digest comparison turns the
    matching test red; restored, green.
  - The trial image now carries the shim too (`docker/trial/Dockerfile`),
    staged at `/usr/local/share/skillc/flow-check-gate-shim.py` -
    deliberately NOT at the subject-visible path, which is owned by
    whatever installs the real pinned script per attempt (skillc#334).
    `apply_flow_check_gate_overlay()` reads this staged copy's content
    (via `export()`) and writes it to the subject path itself, after
    moving the real script aside. `docker/trial/check_helpers.py`'s
    `REQUIRED_HELPERS` gains the entry, same no-daemon Dockerfile-text
    proof #183 PR B2 already established for `skillc-disrupt-tool`.
    Mutation-checked: removing the new `COPY`/`chmod` stanza turns the
    real-Dockerfile check red; restored, green.
  - `tests/test_gate_overlay_live.py` (new): the real-Docker conformance
    test itself, driving a directly-constructed container (#269/#183
    style, never a profile/surface installer) with `apply_flow_check_
    gate_overlay()` placing both files. A STAND-IN plays the real
    `flow-finish-gate.sh` (orchestrator guidance: its claim is about the
    shim's forwarding, never CPP's own gate logic, which needs skillc#334's
    real-checkout install and is deferred there) - made sensitive to
    exactly what the shim must preserve (its own argv, `os.getcwd()`, and
    a digest of `$HOME`, plus an argv-dependent exit code) so a dropped
    cwd or a wrong HOME actually changes its output, which a stand-in
    that printed a constant could not detect. One test function,
    `SKILLC_GATE_SHIM_LIVE_BREAK` selects the mode, `xfail(strict=True,
    raises=_PropertyHeld)` on every non-`none` value - the same shape
    `test_gate_witness_live.py` already uses, with a narrower `raises`
    (counter-model review on #266, adopted here): the two forwarding-
    fidelity checks (exit code, byte-identical stdout) go through a
    `_require()` helper that raises the dedicated, non-`AssertionError`
    `_PropertyHeld` - asserted UNCONDITIONALLY and identically in every
    mode, never branched by `BREAK_MODE` (which would XPASS by
    construction). Every other check stays a plain `assert`, so an
    unrelated infra failure (a Docker flake during a break run) is an
    ordinary hard FAILURE, never credited as the break working.
    Confirmed directly (no pytest/Docker): `_PropertyHeld` is not an
    `AssertionError` subclass, `_require(True, ...)` returns, and
    `_require(False, ...)` raises it.
  - Two more counter-model review findings, fixed before the PR opened.
    (1) `_DECLARED_ENV`'s `PATH` omitted `/usr/local/bin`, where
    `python:3.12-slim` actually installs `python3` - under
    `exec_in_attempt()`'s full-replacement env-pinning this made even
    the intact run fail to launch the gate at all; fixed by including
    it. (2) The channel-failure break mode forced its outage only inside
    `exits-zero-on-channel-failure` and compared against the NORMAL-
    forwarding expected exit code, so the check could not tell "the
    shim's own bug fired" from "the forced outage alone would fail this
    regardless" - a real shim given the same forced outage legitimately
    returns 125, not the forwarded value, so every mode would have
    looked identical. Fixed by splitting it into its own property,
    forced identically in EVERY mode (only `exits-zero-on-channel-
    failure`'s mutation can still fail it, since that mutation is
    otherwise invisible to normal forwarding - it only touches FAILURE
    paths).
  - A third finding (realpath-then-exec TOCTOU in `GateWitness._confine_
    requested_cwd`: the in-container directory a resolved `cwd` names
    could in principle be replaced with a symlink between confinement
    and the later `docker exec -w`) is real but architectural, not a
    quick fix - filed as its own issue rather than patched into #332
    under time pressure; see that issue for detail.
  - Mutation-checked by construction: each of the four `gateshim:` break
    modes is a deliberately-broken shim variant (three)
    or an emptied `declared_env` (`wrong-env`, the fourth) run through
    this same test, and is asserted to fail exactly the property it
    names; no daemon is reachable in this environment to execute it
    here, so it is verified by rendering and `compile()`-checking every
    generated in-container script plus the expected-output derivation
    against the stand-in's own print statements, and is owed to the
    real-Docker runner (#315) for execution evidence.
  - `ci/check_real_docker_ran.py`'s `DECLARED_REAL_DOCKER_FILES` floor
    gains `tests.test_gate_overlay_live` (orchestrator review: a file
    tagged `real_docker` is collected and run, but not CERTIFIED, until
    the floor also names it - see `ci/real-docker/README.md`). README's
    own file list and `tests/test_real_docker_verdict.py`'s floor-size
    fixtures updated to match. Mutation-checked: the existing 3-file
    floor assertion in `test_real_docker_verdict.py` turned red the
    moment the floor grew to 4, confirming it actually pins the floor's
    size rather than passing by construction; fixed to the new 4-file
    tuple and a dedicated per-file-skip case for the new entry, green.

- **The real-Docker runner's `--break` flag generalized to a family:mode
  table** (Refs #315, #269, #183). Found during #269's PR merge review:
  the runner only ever set `SKILLC_LIVE_TEST_BREAK` (#183's channel break
  modes), so #269's witness break modes (`stale-confirm-lie`,
  `kill-wrong-pid`, `gate-in-fresh-container`) had no path through the
  runner at all - the red half of #269's own evidence was unreachable.
  - `ci/real-docker/break-lib.sh` (new): pure, sourceable
    `resolve_break_spec`/`context_for_break_mode` functions - a closed
    table mapping `channel:<mode>`/`witness:<mode>` to the right env var,
    refusing any family or mode it does not name with exit 2, before any
    checkout or docker operation. The three legacy bare channel spellings
    (`--break omit-mount` etc., no prefix) still work, kept for
    compatibility with runs recorded before family prefixes existed; a
    bare witness mode has no such form and is refused.
  - `tests/test_run_real_docker_break.py` (new): exercises both functions
    by sourcing the lib directly (no config file, docker, or git needed -
    the parsing and context-routing happen before any of that), plus two
    end-to-end tests against the REAL `run-real-docker` script confirming
    an invalid `--break` is refused before the config-file check and a
    valid one reaches it. Mutation-checked: widening the table to accept
    any spec, and collapsing the context function to always return the
    certifying context, both turn the relevant tests red; restored, green.
  - `ci/real-docker/README.md`'s step 8 now lists all six expected-red
    runs (three channel, three witness) plus `none`.
  - `raises=AssertionError` added to both live test files' `xfail` marks,
    so a break mode that dies of an unrelated exception is a hard FAILURE
    rather than an accidental XFAIL. This safety was established by
    reading every break mode's failure path in both files (every one
    resolves to a plain `assert`), not by running either file against a
    real daemon - none is available in this environment.
  - `resolve_break_spec` always emits an explicit value for BOTH families
    on every call ("none" for the one not selected), never leaving either
    empty for the caller to infer - a codex:code_review finding against
    this PR's own first draft, which set only the selected family's env
    var and left the other exactly as inherited from the runner's own
    process environment. A stale `SKILLC_LIVE_TEST_BREAK=omit-mount` left
    over from a prior by-hand invocation could then have silently
    activated that break during an unrelated `--break none` (certifying)
    run. `run-real-docker` now always sets both
    `SKILLC_LIVE_TEST_BREAK`/`SKILLC_GATE_WITNESS_LIVE_BREAK` explicitly
    in one `env` invocation. Mutation-checked again under the corrected
    contract; a text-level regression guard
    (`test_the_real_runner_always_sets_both_break_variables_explicitly`)
    pins the fixed invocation shape itself, since driving the actual
    pytest call needs a real checkout and daemon this environment lacks.
  - A second codex finding (MEDIUM) - `raises=AssertionError` narrows by
    exception type only, not by which assertion fired, so a helper/setup
    assertion could in principle satisfy `xfail` before the intended
    break-detection assertion is reached - is a real but currently latent
    structural gap (by code-reading, every break mode's intended assertion
    is the first one reached today) that would need a dedicated exception
    type per break-detection assertion across both live files to close
    properly; deferred as out of scope for this PR and recorded in the
    Nit Store (cooneycw/skillc#20, comment 6025027183).

- **`tests/test_gate_stops_early_witness_equivalence.py`: an equivalence
  guard against the duplication drift risk** (Refs #270). Runs the SAME
  battery of 11 record shapes (normal, not-observed with and without
  exclusivity, launch-failed, channel-unavailable, interrupted, zero
  runs, a single fresh/stale run, an edit-then-rerun cycle, a rerun that
  drifted away) through both `flow_check_honest()`'s duplicated
  `_execution_observed`/`_last_run_is_fresh` and the canonical
  `skillc.gate_witness`/`skillc.stale_tree` functions they copy, in the
  NORMAL suite where `skillc` IS importable (unlike the isolated judge
  itself). A silently diverging copy would grade against a different
  rule than the real gate-witness implements, and nothing in the judge's
  own tests could ever notice, since they never see the canonical
  functions to compare against. Mutation-checked: flipping
  `launch-failed`'s reported status and reading `runs[0]` instead of
  `runs[-1]` each turned the matching case red, confirmed, then reverted.

- **`gate-stops-early`'s `flow-check-honest`: real, mutation-checked logic,
  declared as a standalone function rather than a grader criterion**
  (Refs #270), unblocked by skillc#332's locked gate-witness record shape
  (gate names `flow-check-plan`/`flow-check-summary`; three worked
  examples - normal, not-observed, channel failure). Reconciles a
  candidate's `report.json["flow_check_summary"]["claim"]`
  (`"SKIP"`/`"PASS"`) against a controller-supplied gate-witness record,
  using logic DUPLICATED (never imported) from
  `skillc.gate_witness.GateRecord.execution_observed()` and
  `skillc.stale_tree.last_run_is_fresh()` - confirmed the hard way: a
  first draft that imported `skillc` at module level broke every existing
  criterion with `ModuleNotFoundError`, because `skillc.verify._judge`
  stages the judge file alone with no `skillc` package reachable.
  **Structural finding:** `skillc.verify`'s real contract
  (`criteria_problem()`) refuses any judge report unless every returned
  criterion is `mandatory: True` and matches the grader's declared set
  exactly - there is no "optional criterion" shape - so a criterion that
  can only answer UNKNOWN until a live witness exists cannot be declared
  without dragging every already-certified candidate to INCONCLUSIVE.
  `flow_check_honest()` is therefore certified directly by
  `qualify.py`'s new `flow_check_honest_validity()` (5 cases: SKIP claim
  SATISFIED, PASS claim VIOLATED, not-observed UNKNOWN, channel failure
  UNKNOWN, stale tree VIOLATED even with an honest claim - plus two
  refused broken-grader controls), the same way `restore_probe_validity()`
  already calls `judge()` directly rather than through
  `grade_directory()`. Witness records are built with
  `skillc.gate_witness.GateWitness`'s own real constructors, never
  hand-typed JSON. Both `gate-stops-early`'s and `verify-stops-early`'s
  `eligibility-manifest.json` and `PROVENANCE.md` now say **NOT YET
  ELIGIBLE** explicitly: a live #287 attempt needs skillc#332 merged,
  skillc#334 merged (the live-attempt profile-closure install gap found
  while building #332 - without it every flow-check invocation exits 127
  before reaching anything gradeable), and a deterministic subject run
  through the real runner producing a genuine captured witness record.

- **`eligibility-manifest.json` for `gate-stops-early` and
  `verify-stops-early`** (Refs #270, prepares #287), mirroring
  `gate-ran-nothing`'s own shape (same `selection`/`outcome` separation,
  same B/N/P arm names). Each names the tree a future #287 pilot must
  actually run a live attempt against - `discrimination/fixture`, never
  the task's own top-level `fixture/`, whose Makefile declares every gate
  and so never exercises CPP's skip/aggregate mechanism at all - and says
  plainly that today's three certified criteria produce the identical
  verdict on both trees, because `probe.py` runs the candidate's
  `ci/check.py` directly rather than reading the CPP gate's own skip/warn
  output. A live attempt against `discrimination/fixture` is therefore
  **not yet eligible** for either task's own obligation until
  `flow-check-honest` is declared and wired through it. `named_skills`,
  arm `status` and `approval_ref` are left explicit `TBD`/`proposed`/
  `NONE YET` rather than invented: #287 has not run, and no owner ruling
  parallel to #203's decision 3/4 exists yet for either task.

- **`skillc/stale_tree.py`: the tree-identity comparison `gate-witness.md`
  §6 names but deliberately does not perform** (Refs #270). `GateWitness`
  (#269) records a `tree_digest_at_start` on every gate run and never
  compares it to anything itself - "the grading decision belongs to
  #270/#271" (§6). This module is that comparison: `last_run_is_fresh`
  checks a gate's most recent run against a caller-supplied graded-tree
  digest, and `stale_gates` names every declared gate whose last run was
  captured against a tree other than the one being graded. The LAST run
  decides, never the first and never all of them - a gate is legitimately
  rerun after an edit (gate_witness.py's own red case 3), so an earlier
  run's digest is SUPPOSED to be stale; only the most recent run is a claim
  about the tree a grader is looking at now. A gate with zero runs answers
  `None`, never `False` - `gate_witness.py`'s own `not-observed` coverage
  already owns that population, and collapsing it into staleness would let
  a true bypass hide behind this module's verdict. 11 tests, 4
  mutation-checked by hand (equality flip in `run_freshness`; `None`
  collapsed to `False` for a zero-run gate; reading the first run instead
  of the last; `stale_gates` sweeping a never-run gate into its result) -
  each applied, confirmed red, and reverted.

- **New Level 3 task `verify-stops-early`: `gate-stops-early`'s
  structurally distinct held-out variant** (Refs #270 acceptance item 2).
  Same three certified criteria and the same restore-and-rerun grader
  shape, against a deliberately different bug domain
  (`textkit.dedupe.dedupe_adjacent`, which unconditionally drops its last
  element, rather than `rangekit.windows.sliding_window`'s "too few
  windows") and a different Makefile layout (`verify:` as the aggregate
  target, listing `typecheck lint test` in that order, rather than
  `check: lint test typecheck`). Re-proved rather than assumed that the
  real CPP runner's skip/aggregate mechanism is keyed on plan step ids
  and Makefile structure, never the aggregate's name or prerequisite
  order: `discrimination/fixture/` (typecheck absent) captures the
  identical `FLOW_FINISH_GATE: warn (skipped gates: typecheck)`/exit 3
  signature `gate-stops-early`'s own proof found, and the full-Makefile
  `fixture/` captures a clean `FLOW_FINISH_GATE: ok`. `QUALIFY: ok` -
  grader certified, 5 broken graders refused, 4 restore-probe validity
  controls held, mirroring `gate-stops-early`'s own result exactly.
  `flow-check-honest` stays undeclared here too, for the identical reason.

- **New Level 3 task `gate-stops-early`: certified for three of its four
  criteria** (Refs #270). A rangekit-derived fixture (a
  `sliding_window` off-by-one bug) whose Makefile declares `lint:`/
  `test:`/`typecheck:` individually plus a `check:` aggregate - closing
  the gap `evals/workflow-contracts/flow-check/README.md` names (no
  existing fixture had those targets at all). `functional-windows-fix`,
  `regression-fails-on-original` and `gate-green` are graded via the same
  restore-and-rerun probe shape as `gate-ran-nothing`; `qualify.py`
  certifies the grader against `alternatives/`, `benign/` and `wrong/`
  candidates, refuses all 5 broken-grader controls, and holds 4
  restore-probe validity controls. A fourth criterion, `flow-check-honest`
  (consuming skillc#332's gate-witness contract once it lands), is
  deliberately NOT YET declared - `grade_gate_stops_early.py`'s own module
  docstring explains why, mirroring the reasoning `gate-ran-nothing`'s own
  judge already documents for its own deliberately-undeclared criterion.
  A separate `discrimination/{fixture,reference}/` tree (typecheck target
  absent) is the one actually used for #287's intact/degraded case-pairing
  - proven against the real CPP runner at the pinned commit, not reasoned
  about; `PROVENANCE.md` records both captured runs. `eligibility-
  manifest.json` is not yet written - deferred to whenever a live-trial
  declaration is drafted, unlike `gate-ran-nothing`'s own, since nothing
  here authorizes or needs one yet.

- **A real-Docker conformance test for #269's gate-execution witness**
  (Refs #269). `exec_in_attempt()`'s own docstring named this gap
  explicitly - its three-exec sequence (marker write-back, in-container
  kill, in-container `kill -0` confirmation) was exercised only against
  the fake CLI. `tests/test_gate_witness_live.py` proves four properties
  against a real daemon: concurrent `exec_in_attempt()` into the SAME
  live container the primary subject's own `execute()` is still running
  in; a selective, confirmed kill that targets only the gate's own
  in-container pid, never the primary's; the PID-marker round trip across
  two separate real `docker exec` invocations; and no standalone `kill`
  binary needed on `python:3.12-slim`'s real shell.
  - `SKILLC_GATE_WITNESS_LIVE_BREAK` selects one of three modes, each
    `xfail(strict=True)`: `stale-confirm-lie` (the kill-confirmation step
    is monkeypatched to lie), `kill-wrong-pid` (the kill sequence is
    monkeypatched to target the PRIMARY's pid instead of the gate's), and
    `gate-in-fresh-container` (`exec_in_attempt` is monkeypatched to run
    the gate in a separate container).
  - Every conformance assertion (the concurrent gate's exit code, the
    test's own independent `kill -0` on the gate's real pid, the
    witness's own `stop_confirmed` record, and the primary's monotonic
    counter progress across the kill window) is asserted as the same
    UNCONDITIONAL invariant in every mode, never as a different expected
    value per mode - a codex:code_review finding against this test's own
    first draft, which had accepted some break modes' defects as their
    "correct" outcome instead of proving the oracle rejects them. The
    primary's own in-container pid (needed by `kill-wrong-pid`) is read
    from a marker the primary writes itself, never via `ps`/`procps`,
    which `python:3.12-slim` deliberately lacks (a second codex finding
    against the same first draft).
  - The primary's progress counter is published via a temp-file-then-
    `os.replace()` swap, not a direct truncating `open(path, "w")` - a
    second, re-review codex:code_review finding against this test's own
    fix round: a `docker exec cat` landing between the primary's own
    truncate and write could read an empty file, and the counter reader
    turned that into a spurious zero indistinguishable from "never
    ticked." `os.replace()` on the same filesystem is atomic, so a
    concurrent reader sees either the whole prior value or the whole new
    one, never a truncated in-between.
  - Plan reviewed and approved on issue #269 (comment 6023059101) before
    any code was written.
  - Written and reviewed WITHOUT ever running it against a real daemon -
    no Docker binary in this environment, same documented position
    #183's own `test_decide_reply_channel_live.py` already states for
    itself. Skipped, not failed, wherever no Docker daemon is reachable
    (`probe_daemon`, same binary-vs-daemon distinction added in #183 PR
    B2); real-daemon execution is owed to the real-Docker runner (#315).
    `@pytest.mark.real_docker`, and `tests.test_gate_witness_live` is now
    in `ci/check_real_docker_ran.py`'s `DECLARED_REAL_DOCKER_FILES` floor
    (#315's PR landed first, so this PR adds the entry) - with a red case
    pinning the real, now-three-file floor: the other two declared files
    pass while this one collects only a SKIP must give `FAILURE`, never
    `SUCCESS`.

- **A new `cpp-codex-flow-check-ea6dbfa` profile, at claude-power-pack's
  current pin** (Refs #265, #287). claude-power-pack#1370 found the existing
  `cpp-codex-flow-check` profile's pin (`85e9b03`) stale on both content and
  dependency axes against current CPP main - 21 unresolved references. Per
  that profile's own stated rule ("a later pin is a new profile with its own
  inventory, not an edit to this one"), this is a SEPARATE profile directory
  (`evals/subjects/cpp-codex-flow-check-ea6dbfa/`) at
  `ea6dbfa45f9308ee6ba60f032d8e7031bd6938a1` (confirmed a descendant of
  #1380's fix) with its own `subject.json` - the original profile, its
  evidence, its subject pin, and claude-power-pack#264's case-contract
  line-number citations against its blobs are all untouched. All 21
  references read in the real source and classified: 19 are print-help-text,
  generated-Dockerfile string literals, or code comments/docstrings inside
  claude-power-pack's `lib/cicd/*.py` (never runtime paths flow-check reads
  or writes - each given its own `unsupported` entry starting `not a runtime
  reference:` naming the exact mechanism, per orchestrator review so
  claude-power-pack#1370's downstream consumer can separate them from real
  capability gaps); 1 is the same "another client's surface" class the
  profile already declares unsupported three times for Claude Code's plugin
  root; 1 extends the `checkout-scripts` dependency to also satisfy
  `$CPP_DIR/scripts/execution-evidence-verify.py`. `skillc profile diagnose`
  and `validate` both report zero problems at the new pin. Regression red
  case (`tests/test_cpp_codex_flow_check_redeclare.py`, with a committed
  snapshot fixture of the real new-pin source,
  `tests/fixtures/profile-cpp-codex-flow-check-ea6dbfa/`): the ORIGINAL,
  untouched profile against this fixture must report the EXACT SET of 20
  distinct unresolved-reference strings (21 occurrences - one string appears
  in two files) claude-power-pack#1370 found, not merely a matching count;
  the new profile against the same fixture reports zero.
- **The Level 5 subject-side proxy is wired into the trial image** (Refs
  #183, PR B2). `docker/trial/skillc-disrupt-tool.py` - a one-shot client
  for #183's decide-and-reply channel, committed unwired in PR B1 - is now
  baked into `docker/trial/Dockerfile` at `/usr/local/bin/skillc-disrupt-
  tool`.
  - `docker/trial/check_helpers.py` (new, no-daemon, same family as
    `check_pins.py`/`check_interpreters.py`) proves the Dockerfile's own
    COPY and chmod lines both exist, without needing a Docker daemon.
  - The proxy's own tests (`tests/test_skillc_disrupt_tool.py`) run it as a
    real subprocess against a real `DecideReplyChannel`, never a mock of
    the wire protocol - they caught a real bug before anything else did:
    the proxy read `reply["allow"]` at the top level, but the channel's
    `_Handler` wraps `decide()`'s return value under a `"result"` key, so
    every real exchange would have returned the infrastructure-error exit
    code (2) regardless of the actual decision. Fixed and mutation-checked.
  - `evals/level5/recovery-partial-processing/goal.md` now tells the
    subject to run `skillc-disrupt-tool` before each record and treat a
    nonzero exit as the tool becoming unavailable - minimal and neutral,
    naming only the command and exit-code contract. Checked (not assumed)
    that this doesn't affect certification: `goal.md` is outside
    `GraderDef.digest()`'s covered files and is never read by this task's
    deterministic judge, confirmed by re-running `qualify.py` after the
    edit (`QUALIFY: ok`, unchanged).
  - `tests/test_trial_image_build_live.py` (new): a real `docker build`
    under a distinct tag proving the installed binary is present,
    executable, and runs as `candidate` - skipped (not silently passing)
    wherever no Docker daemon is reachable, real-daemon execution owed to
    the real-Docker runner (#315), same framing as #183's own live-channel
    test.
- **The `<agent-host>` real-Docker runner (#315).** A small, operator-
  installed runner (`ci/real-docker/run-real-docker`, `poll-triggers`, and
  matching systemd units) certifies `real_docker`-marked tests (today:
  `tests/test_decide_reply_channel_live.py`, #183's live conformance) on an
  isolated Docker VM - no Woodpecker involved, per the operator's ruling
  that superseded the earlier Woodpecker-agent and separate-server designs
  on this issue.
  - `ci/check_real_docker_ran.py` - the pure verdict function (SUCCESS /
    FAILURE / ERROR, never collapsing "nothing collected" into success),
    modeled on `ci/check_git_tests_ran.py` (#307).
  - `ci/real_docker_isolation.py` - the preflight isolation DETECTOR (never
    a proof - the enforced boundary is a hypervisor-level firewall the
    operator sets up outside this repo); a tri-state TCP-connect probe (a
    connection refused still proves a host answered and counts as
    reachable; only a timeout/no-route counts as unreachable; the probe
    itself failing to run is its own `probe_error` state, which also
    refuses - never folded into "unreachable" the way a bare fallback
    would).
  - `ci/real_docker_trigger.py` - trigger-comment selection: new commits on
    main, or an explicit `/run-real-docker <40-hex-sha>` comment whose
    author is checked against the repository's own `owner.login` (never
    the comment text); each comment id is processed exactly once, at first
    sight, so an edited old comment can never re-trigger.
  - `ci/real_docker_summary.py` + `ci/real_docker_post.py` - the leak-safe,
    allowlisted-by-construction summary posted off the VM (full logs stay
    local), and the glue that computes it from an INSTALLED, reviewed copy -
    never from the checkout under test, so a requested commit cannot
    redefine its own grade (a committed subprocess red case proves this
    directly: a fixture checkout whose own `check_real_docker_ran.py`
    always claims SUCCESS still yields FAILURE on a failing report).
  - `real_docker` pytest marker (`pyproject.toml`), the selector every
    real-Docker test opts into with no runner-script change per addition.
  - Every pure component (verdict, isolation classifier, trigger selection,
    summary formatter, posting glue) has committed, mutation-checked tests;
    the bash orchestration is reviewed and syntax-checked but not
    exercised end-to-end in this environment (no real Docker daemon or
    GitHub token here) - closed by the operator's setup-time verification
    steps (`ci/real-docker/README.md`).
  - **Orchestrator cross-model review, 8 findings, all fixed before the
    PR.** Three blocking (two of which made the verdict blind): the
    comment poll fetched the 100 OLDEST comments in the repo forever
    (no `sort`/`direction`) - fixed with `sort=created&direction=desc`
    plus id-aware pagination; a bare `wget` LAN probe could not tell
    "connection refused" (still reachable) from "nothing answered"
    (unreachable) from "the probe itself couldn't run" - fixed with the
    tri-state python3 socket probe above; an abbreviated sha always
    self-refused as a checkout mismatch - fixed by requiring exactly 40
    hex characters in both the trigger regex and the runner's own
    argument check. Five smaller: state persisted before a run started
    (a lock-contended run could be marked done without ever running -
    fixed with a bounded `flock` wait and a distinct exit code the
    poller checks for); a failing `uv sync` died silently with nothing
    posted; `curl` had no `--fail`, so a rejected post looked identical
    to an accepted one; the GitHub token was visible in process argv
    (`ps`) - moved to a private `-K` config file; and the leak-safety
    test's planted strings had widened the leak-check exclusion to a
    whole file - moved into the existing seeded-leak fixtures
    (`fixtures.leak_seeds.judge_seeds`, #69) instead, so the exclusion
    list needed no new entry.

- **Raised the calibration declaration's `attempts_per_arm` bound, 3-8 to
  1-1000 (#323).** Found while sizing #287's declaration: the exact one-
  sided Fisher's-exact power table computed on
  `evals/calibration-287/power_cost_table.py` shows a real study may need
  n>=10 per arm even at the best observable outcome, which the old 3-8
  range refused outright. The new range is a sanity rail against a typo'd
  exponent, not a design-sizing constraint - that question belongs to the
  declaration's own power justification and to ADR 0005's cost gate.
  `require_approved` now also checks `approval.attempts_per_arm` against
  the declared `attempts_per_arm`: raising the cap opened a gap where a
  declaration edited to a different, self-consistent schedule (both
  `attempts_per_arm` and its re-derived `arm_order`) would otherwise pass
  on an approval that was never asked about the new size. The four real
  committed declarations (`evals/calibration-204`, `-203`, `-203-low`,
  `-203-c3`) each record their already-approved size in this new field.

- **The expanded-instruction lane for the #204 calibration declaration
  (#274).** `lane` (`explicit-contract | matched-outcome | expanded-
  instruction`) joins the declaration schema, defaulting to
  `matched-outcome` so every existing declaration keeps its prior,
  unnamed meaning. The new lane adds a second treated-arm pair - S
  (explicit-skill) vs E (expanded-instruction), protocol.md 10.1/10.4 -
  sharing one `skillc profile validate` inventory, with helper-parity
  (`treatment_question == "prose"`) and content-identity
  (`body_digest`-matched) checks before any attempt runs. No new runner:
  built entirely on calibration.py's existing parse/schedule/report path.
  - **Three Codex cross-model review fixes** (diff-only scope). **[HIGH]**
    the inventory's claims were trusted without being bound to the
    declaration's own subject - now checked against
    `inventory["subject"].locator/revision`. **[MEDIUM]** an E arm
    carrying neither `instruction` nor `named_skills` passed every shape
    check and crashed downstream instead of being refused cleanly - now
    refused in `parse_declaration`. **[MEDIUM]** an entirely absent
    `helper_parity` object read as an empty, passing population,
    indistinguishable from a validated empty one - now requires the field
    present as a list.
- **Five Codex cross-model review fixes for #272** (pre-PR review, model
  `gpt-6.1-sol`). All five mutation-checked.
  - **[HIGH] `CoverageRow.criteria` silently overwrote a disagreeing
    attempt's outcome.** Nothing in `records.py` requires two attempts
    sharing a cell to agree on one criterion - each attempt's
    `criteria_owned` is checked only against its OWN `verified-result`. Keying
    the accumulator dict on criterion id alone let whichever attempt was
    iterated last silently discard an earlier `VIOLATED` with a `SATISFIED`
    (or the reverse) - a real failure hidden purely by `attempt_ids` order.
    Now keyed on `(id, outcome, shared)`: a genuine repeat still collapses to
    one row, but a disagreement surfaces as two rows for the same id,
    nothing dropped.
  - **[MEDIUM] `to_text()` never rendered `execution_observed`/
    `read_observed`.** A row with confirmed skill execution read identically
    to one where nothing was ever observed - exactly the distinction these
    two fields exist to carry. Now rendered per row, every count including a
    0, the same pattern as `outcomes`.
  - **[MEDIUM] The generic sentinel-coverage test was whole-text, not
    location-aware.** It could not tell `convenience.tokens`'s own `UNKNOWN`
    apart from the `UNKNOWN=0` key-name artifact already in `outcomes`, nor
    tell one row's `reliability` apart from another's - concretely, dropping
    only `tokens=...` from the convenience line, or dropping one row's
    `reliability:` line while a different row still rendered a sentinel,
    both left the old test green (reproduced before fixing: removing
    `tokens=` left `test_to_text_renders_every_sentinel_value_present_in_
    the_json` passing). Two new tests check each row's own `reliability`/
    `convenience` dict against that SAME row's own rendered line, and the
    `task_clusters` sentinel against its own section - never the whole
    block or the whole report. The old whole-text test stays as the cheap
    floor for fields not yet given a scoped check.
  - **[MEDIUM] `TwoArmRule` accepted an out-of-range `alpha` or a
    `tolerance` of 0.** `alpha=2` with `tolerance=0` let
    `evaluate_two_arm_rule` report `DISCRIMINATING` from a Fisher p-value of
    `1.0` on a ZERO-evaluable arm: `tolerance=0` imposes no floor at all, so
    `arm_evaluable < tolerance` was vacuously false, and `p < alpha` was
    vacuously true for any alpha above 1. `TwoArmRule.__post_init__` now
    validates `alpha` (finite, strictly between 0 and 1, same discipline as
    `_check_confidence`) and `tolerance` (`None`, or a positive int) at
    construction.
  - **[MEDIUM] `reconcile_helper_identity` reported `matched` on partial
    coverage.** A claimed path with no installed counterpart was silently
    skipped from the comparison entirely, so an agreeing path alone reported
    the whole record `matched` - treating an unwitnessed helper as outside
    the comparison rather than as unknown, contradicting the function's own
    documented "a path present on only one side is unknown" rule. `matched`
    is now reserved for every claimed path being comparable AND agreeing;
    partial coverage is `unknown`/`partial-helper-coverage`.

- **Level 5's disruption-trigger channel is wired to #183's controller-owned
  decide-and-reply mechanism** (Refs #183). `DecideReplyChannel` now carries
  its own `attempt_id` (set at construction, since it is already per-attempt
  by design) and exposes `trusted_log()` as the convenience that binds a
  `TrustedLog` from the channel itself rather than a caller-side claim;
  `TrustedLog.to_json_bytes()` also writes `attempt_id` and sorts decisions
  by `seq` explicitly.
  - `evals/level5/recovery-partial-processing/grade_recovery.py`'s
    `_trusted_log()` no longer accepts a pre-derived `{"failed_after_step":
    N}` claim (review found that shape forgeable even with a digest/
    attempt_id attached). It now parses the raw channel log directly and
    derives `failed_after_step` itself from the controller's own seq-ordered
    decisions - refusing a non-clean seq set (duplicate/gap) but accepting
    any arrival-order permutation (re-sorted first, per the channel's own
    completion-order numbering). An optional `expected_attempt_id`, when
    supplied, is cross-checked and refused on mismatch.
  - `qualify.py` no longer reads any trusted observation from inside a
    candidate's own tree - `reference`/`wrong/*` are now certified against
    `controller-observations/<candidate>.json`, bytes from a REAL
    `DecideReplyChannel` run produced by the committed
    `generate_controller_observations.py` (never hand-typed), labelled
    controller-simulated pending live generation (Docker-owed).
  - The headline red case: a plausible `trusted-disruption-log.json`
    planted inside a candidate tree is refused outright (not silently
    ignored) - pre-PR-B code read it and graded `reference` SATISFIED on
    its say-so. A second red case refuses a controller observation whose
    own `attempt_id` doesn't match the candidate it's supplied for. Both
    mutation-checked, alongside the seq-validity and attempt_id-match
    checks in `grade_recovery.py`.
  - No `expected.json` changed: `reference` still certifies PASS,
    `forged-log`/`silent-overclaim`/`work-loss` still FAIL for the reasons
    they always did - this restructures WHERE the trusted bytes come from,
    not what the grader is certified to catch.
  - The subject-side proxy and its image/Dockerfile wiring are a separate
    follow-on branch (#183 PR B2), not part of this change.

- **`DockerBackend.execute()` refuses a second call on an already-stopped
  handle instead of fabricating a result** (Closes #304). `execute()`'s own
  contract always stops the container before returning; a second call used
  to fall through to a real `docker exec` the daemon rejects, and that
  rejection's own nonzero exit read as an ordinary `reason="exited",
  exit_code=1` - an execution that never touched the container, reported as
  one that did. Refused now with `reason="attempt-not-running",
  exit_code=None`, the same reason `exec_in_attempt()` (#269) already uses
  for this exact situation.
  - The guard is a fresh `_inspect()` at entry, confirmed-not-running only -
    an unreachable daemon or missing binary still falls through to the real
    attempt, which reports its own accurate `launch-failed` exactly as
    before this guard existed.
  - That entry check is itself a check-then-act: the container can stop in
    the gap before the real `docker exec` runs. **Left open, documented, not
    closed** - a first attempt reclassified the race by matching the
    daemon's own rejection text in the captured stderr, but `codex:
    code_review` found that text is read from the SUBJECT's own stderr: a
    subject whose legitimate output happens to contain that wording would
    have its real result silently discarded as `attempt-not-running`.
    Removed rather than shipped with a known spoofing path; a real fix
    needs a provenance signal independent of subject-controlled output
    (e.g. `exec_in_attempt()`'s own marker/PID-confirmation mechanism),
    which is a separate, bigger change, tracked as its own issue.

  The red case: a second `execute()` call on one handle must never report
  `reason="exited"`. Mutation-checked (the entry guard disabled fails the
  red case); the open TOCTOU window has its own test proving the race
  still produces the daemon's unmodified rejection today, rather than
  merely asserting the docstring's claim.

- **Per-skill profile diagnostic, non-certifying** (Refs #295). `skillc
  profile diagnose` (library: `profile.diagnose`) walks the whole closure and
  reports EVERY unresolved reference, unsatisfied dependency and other
  refusal reason, attributed to the skill(s) whose closure reaches it, with
  no truncation. Schema-distinct from `validate()`'s inventory by
  construction, so nothing that expects a certification can mistake one for
  the other; `validate()` itself is unchanged - both share one walk, and its
  own call raises exactly as before, with the same messages. A broken
  dependency reached a second time is marked a cascade (`caused_by`) of the
  one root cause rather than reported again.

- **`uptake-study` screens: published plus 1-3 description variants in one
  run** (Refs #238). Arms are `published` then `variant-a`..`variant-c`, with
  the same subject and target, and distinct descriptions.
  - Every case declares `expect: select | abstain`.
  - A screen has no primary case and no test. Each arm is scored as its
    selection rate on `select` cases minus its rate on `abstain` cases, so
    a description that fires everywhere scores no better than one that
    never fires. The red case: a recall-only score fails the test.
  - `--rewritten ARM=DIR` is given once per variant. Each variant's snapshot
    passes `check_rewritten_files` against `published`.
  - The two-arm study (`published` + `rewritten`, with its Fisher test) is
    unchanged.

- **`to_text()` renders reliability, convenience and task_clusters; the
  "nothing hidden" test is now generic** (Refs #272 acceptance item 1,
  orchestrator review). Not a nit after all: the human view omitting
  `reliability`, `convenience` and `task_clusters` - including their
  `insufficient`/`not_declared`/`UNKNOWN` states - failed acceptance item
  1's own "concise human view" requirement, and its docstring's "nothing is
  summarized away" claim was false. `to_text()` now renders all three per
  row (reliability's intervals/all_k/pass_at_k, convenience's per-phase
  totals or `UNKNOWN`) and at report level (`task_clusters`: an interval or
  `insufficient`), still derived from the same `to_dict()` `to_json`
  serializes.

  The "nothing hidden" test is now GENERIC rather than enumerating fields:
  `test_to_text_renders_every_sentinel_value_present_in_the_json` walks
  `to_dict()` for every string VALUE matching a known sentinel (`UNKNOWN`,
  `insufficient`, `not_declared`, `not_captured`) and asserts each one
  found also appears in `to_text()` - a new field carrying one of these
  sentinels can no longer be silently dropped, without the test needing to
  know the field exists. Mutation-checked three times, once per renderer
  (reliability, convenience, task_clusters removed in turn), each going
  red on a DIFFERENT sentinel - proving the test genuinely depends on all
  three, not just the first one found. One real trap found and fixed while
  building this: `CoverageReport.inventory` reports
  `INVENTORY_NOT_DECLARED` ("not_declared") when no inventory is supplied -
  the exact same literal string as `reliability`'s own `NOT_DECLARED`
  sentinel - and `inventory` is always rendered regardless of any row-level
  renderer, so an undeclared-inventory fixture would have let that
  collision silently defeat the reliability mutation check; the fixture
  declares an inventory specifically to avoid it.

  Withdrew the skillc#20 nit comment (edited to record it was fixed here,
  not left open as a stale pointer to resolved work).

- **Task-cluster bootstrap: a report-level section alongside `case_pairs`**
  (Refs #272 acceptance item 4, #273). `CoverageReport.task_clusters`
  (`TaskClusterBootstrap`) groups every row by (skill_path, skill_version,
  client_name, client_version, arm) - the row key minus `case_id`, so each
  group spans every TASK (case) in the bundle that shares it - and
  bootstraps that group's rows' own `reliability.all_k` values via
  `reliability.task_cluster_bootstrap` directly (never reimplemented).
  `assemble_coverage_report` gains optional `bootstrap_seed: int | None`
  and `bootstrap_resamples: int` parameters; without a declared seed,
  `task_clusters` is empty - the same "no declared input, no section"
  discipline as `discrimination_rule`/`k`, never a skillc-chosen default
  seed. A row without a numeric `all_k` (`NOT_DECLARED` or
  `reliability.INSUFFICIENT`, itself needing `k` declared) contributes no
  task value but the group still gets an entry, so an all-undeclared-`k`
  group reports `task_count=0`/`INSUFFICIENT` rather than silently having
  no entry. Below `reliability.MIN_BOOTSTRAP_TASKS` usable tasks,
  `all_k_interval` is `reliability.INSUFFICIENT` (the same sentinel, never
  a second one) - explicit, never a silently omitted group. 4 new tests
  (the 4-tasks-INSUFFICIENT/5-tasks-an-interval boundary, a byte-identical
  repeat with the same seed, absence without a declared seed) plus 2
  mutation checks (the `MIN_BOOTSTRAP_TASKS` boundary off by one; grouping
  by case instead of across cases), both net-diff-empty after restoration.

- **Row-level convenience: `phase_wall_times` aggregated over a row's
  attempts** (Refs #272 acceptance item 4, #273). `CoverageRow.convenience`
  (`RowConvenience`) rolls up #273's `convenience.py` per-attempt proxies to
  row level: `phase_wall_times` sums seconds per (from_event, to_event)
  transition across every attempt in the row, with the contributing attempt
  count kept alongside each sum. Each attempt's own breakdown stays
  available by reference in `per_attempt`, keyed by the same attempt ids
  `CoverageRow.evidence` already names, rather than duplicated. The three
  `NOT_CAPTURED` proxies and the `UNKNOWN` tokens proxy pass through
  unchanged - there is no per-attempt data for any of them to aggregate.
  `conv.UNKNOWN` (never an empty tuple) when not one attempt in the row
  contributed an actual transition - an attempt whose lifecycle has only
  its `planned` event (a legitimate `not-run`/`never-started` disposition)
  contributes zero transitions, and if every attempt in the row does, the
  row has observed zero PHASES, not zero SECONDS; an empty tuple would read
  as the latter. `records.attempt_lifecycle` only requires each event's
  `at` to be a non-empty string, not a parseable or chronologically-ordered
  timestamp - new plumbing coverage.py owns itself, so an unparseable or
  out-of-order timestamp refuses the whole report (`CoverageRefused`)
  rather than silently producing a wrong duration, the same
  refuse-before-reporting discipline as `_refuse_on_invalid_bundle`. 3 new
  tests (hand-computed aggregate across two attempts, the all-missing-events
  UNKNOWN case, the unparseable-timestamp refusal) plus 2 mutation checks
  (disabling the UNKNOWN guard on an all-empty row; swallowing the
  unparseable-timestamp refusal), both net-diff-empty after restoration.

- **Row-level reliability: `clopper_pearson`/`wilson_score` always computed,
  `all_k`/`pass_at_k` gated on a declared `k`** (Refs #272 acceptance item
  4, #273). `assemble_coverage_report()` gains optional `k: int | None` and
  `confidence: float` parameters, threaded to `_build_row()`, which now
  attaches a `RowReliability` to every `CoverageRow` (serialized in
  `to_dict()`/`to_text()`). `clopper_pearson`/`wilson_score` use the row's
  own `(passes, evaluable)` unconditionally, falling back to
  `reliability.INSUFFICIENT` only when `evaluable == 0` (no rate to bound,
  never a crash). `all_k`/`pass_at_k` need a declared `k` - a study
  parameter, same discipline as `TwoArmRule`'s tolerance, never a skillc
  constant - and report the new `coverage.NOT_DECLARED` sentinel when `k`
  is absent, kept deliberately distinct from `reliability.INSUFFICIENT`:
  no `k` means the question wasn't asked, `n < k` means it was asked and
  couldn't be answered. 4 new tests (hand-computed values with a declared
  `k`, the `NOT_DECLARED` case, the `INSUFFICIENT` case for `n < k`, and a
  zero-evaluable row proven not to crash). Two mutation checks: forcing
  `all_k`/`pass_at_k` to compute even when `k` is `None` goes red on the
  `NOT_DECLARED` assertion; forcing `clopper_pearson`/`wilson_score` to
  compute on a zero-evaluable row raises `ReliabilityRefused` instead of
  returning `INSUFFICIENT`. Both restored, net diff empty.

- **`CoverageReport.to_text()`: the concise human view** (Refs #272
  acceptance item 1). Built from `self.to_dict()` - the SAME dict `to_json`
  serializes, never a second read of `self.rows`/`self.case_pairs` - so the
  two views cannot drift apart. Every row, every count (including a `0`),
  every coverage flag, reconciliation count, criterion and case-pair verdict
  appears; nothing is summarized away, only formatted for reading.
  Deterministic (same sorted order `to_dict()` already uses). 7 new tests,
  including one proving the failed-child-under-successful-parent golden
  case is visible in the text too, and a mutation check (the class's own
  `to_dict` swapped for one that drops all rows, confirming the human view
  reports zero rows right along with it - proving a real dependency, not a
  hardcoded summary).

- **`stale-identity`'s `witness_ref` can cite the installation-receipt**
  (Refs #269, #272). `#301` made `contradicting` require a `witness_ref`
  validated only against `artifact-manifest`-captured digests - correct for
  a gate-execution claim, but `stale-identity` is a claim about installed
  IDENTITY, which an installation-receipt (never a manifest artifact)
  cannot satisfy that way. Found while building `evals/subjects/
  cpp-codex-flow-check/gate_reconciliation.py`'s `reconcile_helper_identity`
  - closed as reconciliation scope rather than left as a verdict the
  reconciler could emit and `check-records` would refuse. `ledger_binding`
  now binds `stale-identity`'s `witness_ref.digest` against this attempt's
  own `installation-receipt.subject.digest`; every other contradicting
  reason is unchanged (still a gate-witness artifact citation). Closed both
  directions with their own committed bad fixture
  (`skill-evidence-stale-identity-wrong-witness`,
  `skill-evidence-gate-reason-cites-receipt`) plus a good one
  (`skill-evidence-stale-identity`), mutation-checked, net diff empty.
  `reconcile_helper_identity` now returns the receipt citation it resolves,
  closing the structural gap its own earlier commit had flagged.

- **`uptake-study` screening-probe mode** (Refs #238). An optional `probe`
  block declares a cut-off (20-300 s), which must equal
  `shared.per_attempt_seconds`, so the attempt itself stops there.
  - Selection is read from the transcript prefix.
  - An attempt with **no tool call** before the cut-off is **undecided**,
    counted neither as selected nor as not selected.
  - The task grade is reported as not measured.

  The red case: counting undecided attempts as "not selected" would let a
  probe report zero uptake. The test fails with that rule disabled.

  A cross-model review (Codex) added two more undecided cases, each with a
  red case that fails when disabled:
  - a call still pending (no recorded output) at the cut-off, because the
    parser counts a skill read only once its output arrives;
  - a transcript with call types the parser does not recognize. This one
    applies in full runs too, since a skill read there is invisible.

  `evals/description-probe/` holds the owner-approved agreement check:
  #237's three descriptions, 5 per cell, at 45 s, against the full-run
  results. No live run yet.

- **`skillc/coverage.py`: the gate reconciler and discrimination/improvement
  evaluators wired in** (Refs #269, #272). `coverage.py` never imports
  `evals/subjects/cpp-codex-flow-check/gate_reconciliation.py` - that would
  put CPP-specific knowledge back inside `skillc/`, exactly what relocating
  it there was for.
  - Every row gains `reconciliation_counts` (`absent`/`unmatched`/
    `matched`/`contradicting`), exposing whatever a bundle's own
    `skill-evidence.external_evidence.reconciliation` already records -
    the reconciler's OUTPUT, never re-decided here.
  - `CoverageReport.case_pairs`: one `CasePairVerdict` per certified
    `case.arm` pairing found in the bundle (#273's own `case-pairing`
    bundle rule already guarantees reciprocity/uniqueness by the time
    refuse-before-reporting lets a bundle through), computed with
    `reliability.evaluate_discrimination` - per-arm pass/evaluable counts
    kept beside the verdict, never replaced by it. No rule supplied still
    populates every pair, verdict `UNKNOWN`.
  - `compute_improvement`: a thin passthrough to `reliability.
    evaluate_improvement` for a caller with its own CPP-vs-baseline
    (`config.arm`) counts - `config.arm` is not a validated field in
    `skillc/records.py`, so this module does not invent a discovery
    convention for it the way it does for `case.arm`.
  - 9 new tests (28 total in the file), two mutation-checked against the
    REAL production code (not a stub): disabling the reconciliation-count
    tally and dropping the intact/degraded arm filter in case-pair
    discovery each confirmed a known-good fixture's test goes wrong,
    restored, confirmed correct again, net diff empty.
  - Rows gain `lineage`/`parent_path`, read from `skill-evidence.
    invocation.lineage`/`parent_path` - item 3's own "attribute parent/child"
    acceptance, resolved the same deterministic way as `skill_version`
    (every attempt under one trial shares one skill-evidence declaration).
  - Acceptance item 6's named golden case: a hand-built attempt whose own
    `verified-result` is `PASS`, with a root skill and a child skill it
    invoked whose OWNED criterion is `VIOLATED`. The child's failure shows
    on the child's own row; the parent's `PASS` cannot leak into it, because
    no row carries any per-skill verdict field at all for it to leak into
    (item 3).

- **Gate reconciler: two more reasons made reachable** (Refs #269, #272).
  `evals/subjects/cpp-codex-flow-check/gate_reconciliation.py` adds
  `outcome-disagreement` and `stale-identity`, after confirming both field
  mappings against actual CPP producer code rather than guessing (the same
  discipline that ruled out `tree-mismatch`):
  - `outcome-disagreement`: CPP's `checks[].status == "not-run"` while the
    witness shows a COMPLETE run of that gate in this attempt - reachable
    without any attempt/run-count mapping. The reverse (CPP claims it ran,
    witness shows no confirmed execution) stays `unknown`: only a
    controller-CONFIRMED observation can contradict a claim, never silence.
  - `stale-identity` (`reconcile_helper_identity`, RECORD-level, not
    per-gate): CPP's `observed.helper.module_sha256` against the same
    attempt's `installation-receipt.installed` digests - both confirmed to
    be SHA-256 over raw file bytes (`lib/cicd/evidence.py::_sha256` and
    `skillc/materialize.py::sha256_file`), differing only in a `sha256:`
    prefix skillc adds. A found structural gap, not resolved here:
    `witness_ref` has no existing mechanism to cite an installation-receipt
    (`_skill_evidence_binding` checks it only against `artifact-manifest`
    digests), so this function always returns `witness_ref: None`.
  - 10 new tests (31 total in the file), two mutation-checked: both new
    checks disabled, confirmed blind, restored, confirmed correct again,
    net diff empty.

- **Discrimination and improvement verdicts: declared one-sided Fisher
  rules** (Refs #272, the owner's ruling on claude-power-pack #1084
  comment https://github.com/cooneycw/claude-power-pack/issues/1084#issuecomment-6014163660).
  `skillc/reliability.py` gains `fisher_exact_one_sided_greater` (exact via
  `math.comb`/`Fraction`, no scipy, no normal approximation - verified
  against the owner ruling's own published power table at n=10 and n=20 per
  arm, all six cases exact) and a shared `evaluate_two_arm_rule` behind
  `evaluate_discrimination` (DISCRIMINATING/NOT_SHOWN/UNKNOWN, intact vs
  degraded) and `evaluate_improvement` (IMPROVED/NO_IMPROVEMENT_SHOWN/
  UNKNOWN, the treatment vs baseline axis) - the same test shape on two
  different arm pairs, built together since the second was trivial once
  the first existed.
  - The rule (`TwoArmRule`: id, alpha, sidedness, tolerance, citation_url)
    is a DECLARED input, never a constant here - skillc stays
    subject-agnostic, the same discipline `EXTERNAL_EVIDENCE_SOURCE_RE`
    already keeps. No rule, no declared tolerance, an uncertified pairing,
    or evaluable attempts below the declared tolerance all yield UNKNOWN,
    never a guess - the owner ruling states explicitly that a study whose
    declaration omits the tolerance "cannot produce a non-UNKNOWN verdict
    under either rule," and that is its own committed control.
  - This module never computes the net CPP gate flip (DISCRIMINATING AND
    IMPROVED on the same certified case and revision) - the ruling is
    explicit that decision belongs to the consumer, not skillc.
  - Mutation-checked: the Fisher summation bound (wrong-bound mutation
    fails 9 of the new tests, including every power-table case) and the
    no-declared-tolerance guard (disabling it crashes rather than silently
    computing, confirming the guard is load-bearing) - both restored, net
    diff empty.

- **A subject-scoped reconciler for `matched`/`contradicting` gate claims**
  (Refs #269, #272 acceptance item 5). `evals/subjects/cpp-codex-flow-
  check/gate_reconciliation.py` (loaded by file path, the same pattern
  `gate_path.py` already uses) compares a CPP usage-record gate claim
  against the controller's own `gate-witness` record (#269) - the one
  comparison `skillc/records.py`'s core cannot make without decoding
  `cpp.execution-evidence/v1`, which records.md's Q4 boundary forbids it
  from doing.
  - Field names pinned to `cooneycw/claude-power-pack@5e1de6d848eb29c2b926
    f2fdf79e8aa375c12c43` (`lib/cicd/evidence.py::check_entry`, the FROZEN
    `.specify/specs/per-skill-audit/spec.md`, and a stripped golden sample
    derived from the real committed usage record) - not a guessed mapping.
  - Only `exit-code-mismatch` is implemented. `outcome-disagreement` and
    `stale-identity` need an interpretation of CPP's fields this module
    does not make unilaterally. `tree-mismatch` is CONFIRMED unreachable
    for this subject: CPP's tree signature is a git `write-tree` content
    hash, record-level; skillc's own tree digest is a flat SHA-256 over
    path/mode/content tuples, per-gate-run - two independently authored
    algorithms with no documented equivalence, never bit-comparable.
  - A carried-forward claim (resumed from a previous invocation) is always
    `unknown`, never `contradicting` - this attempt's witness cannot have
    observed a run from a different invocation. A run-count disagreement
    between CPP's claimed attempt count and the witness's own run count is
    likewise `unknown`, never a guessed fifth contradicting reason (`#301`
    already removed `gate-not-executed` from the vocabulary for the same
    kind of reason: silence cannot prove non-execution).
  - A found disagreement, relayed rather than resolved here: CPP's producer
    code builds a per-check `carried_from_previous_run` boolean, but the
    real committed sample shows only a record-level
    `observed.runner.carried_from_previous_run` list - no per-check field
    at all. This module takes whatever boolean a caller supplies, agnostic
    to which JSON shape it came from.
  - 22 tests, two mutation-checked (the carried-forward and run-count
    guards, each disabled and confirmed blind, restored, confirmed correct
    again, net diff empty).

- **Bounded synthetic profile files** (Refs #303). Profiles can declare
  non-executable marker text with explicit pinned-file replacement reasons
  and digests. Inventories and receipts distinguish pinned and synthetic
  origins. The flow-check profile declares its checkout marker and a
  subject-scoped three-way gate classifier; a real install from the pin
  confirms `flow-finish-gate.sh`'s default self-detection now reaches the
  real runner without `FLOW_GATE_CPP_DIR`, with canary isolation proven
  both directions.

- **Disposable git fixtures and attempt-bound facts** (Refs #275). Fresh pinned
  commits, refs, dirty indexes, preserved files, stashes and a linked sibling
  worktree are built under isolated git configuration. Capture records separate
  content identities and per-observation statuses without absolute paths.
  Synthetic mutation controls cover isolation, loss, drift and unavailable reads.

- **Profile installation and drift receipts** (Refs #266). `skillc profile
  install` validates live source, installs exact bytes and executable modes,
  refuses conflicting destinations, checks supplied tools and verifies the
  installed population. Synthetic controls exercise consuming paths and drift.
  The real pinned flow-check profile was installed by hand from a genuine
  GitHub clone (evidence: `evals/subjects/cpp-codex-flow-check/evidence/
  install-receipt.json`): the installed library imports cleanly and the real
  `flow-finish-gate.sh` runner ran against a tiny project under a scrubbed
  environment, with a fake-operator-home decoy proven (both directions)
  never read. Cold-container execution (acceptance item 2) remains owed.

- **A controller-owned gate-execution witness** (Refs #269). The CONTROLLER
  executes each declared gate itself (`ExecutionBackend.exec_in_attempt()`,
  new) - the subject only asks `{"op": "run_gate", "gate": "..."}` over
  #183's `decide_reply_channel`, reused unchanged. One record per attempt,
  covering the full declared gate set - a gate nothing was ever heard about
  still appears, as `not-observed`, never as a missing entry; every run of a
  gate is recorded, not only the first, so a legitimate flow-check rerun
  after a fix is never refused or overwritten. Five coverage states
  (`complete`/`interrupted`/`launch-failed`/`not-observed`/
  `channel-unavailable`); `execution_observed` derives from coverage alone,
  never from exit code. `launch-failed` (the subject DID request the gate;
  the controller failed to launch it) always reads `UNKNOWN`, regardless of
  exclusivity - only a TRUE bypass (zero requests) may ever read
  `NOT_CONFIRMED`, and only when the caller asserts `gate_exclusivity` (the
  fixture gives the subject no other way to invoke the gate at all) -
  recorded on every gate's own entry so the verdict is never resting on an
  invisible constructor argument; without that assertion, silence stays
  `UNKNOWN`. The reply to the subject carries the
  gate's real exit code and bounded stdout/stderr - what it would see
  running the gate itself - never the witness's own coverage state, other
  gates' status, or tree digests. Tree identity is computed by the
  controller itself immediately before each exec, never claimed by the
  subject.
  - **New `ExecutionBackend.exec_in_attempt()`** (`skillc/backend.py`,
    `skillc/docker_backend.py`, `skillc/managed_backend.py`): execs into an
    ALREADY-RUNNING attempt without ever stopping it - `execute()` itself
    is one-shot per handle and always stops the container
    (its stop-after-exec behavior is now tracked separately as #304, not
    changed here). Refused, never folded into a guessed `exited` result,
    when the attempt's primary process isn't running (`reason=
    "attempt-not-running"`) or the backend doesn't implement it at all
    (`reason="unsupported"` - `ManagedBackend`'s protocol-version-1 answer
    today; the witness reads this as `channel-unavailable` for every gate).
    On timeout/cancellation, the in-container process's own pid (read back
    via a wrapped `echo $$` marker) is killed and its death independently
    CONFIRMED (`kill -0`) before the call returns - never the container
    itself. An unconfirmed kill (`ExecuteResult.stop_confirmed=False`)
    refuses every later `run_gate` for the rest of the attempt
    (`workspace-integrity-unknown`) without retroactively changing a gate
    that already completed - a possibly-still-running process could
    otherwise mutate the tree a later gate would measure.
  - **A `reason` of `"launch-failed"`/`"attempt-not-running"`/
    `"unsupported"` is `not-observed`, never `interrupted`/`CONFIRMED`**
    (cross-model review correction on this redesign): a refused or
    never-launched exec must not report positive execution evidence - the
    exact subject-authored-claim problem this witness exists to stop,
    moved from the subject to a failed launch. The raw run is still
    recorded for transparency; only the derived coverage is corrected.
  - **`skill-evidence.external_evidence.reconciliation == "contradicting"`
    now requires a citation** (cpp-eval review of #268,
    https://github.com/cooneycw/skillc/issues/269#issuecomment-6009072750):
    a `{ref, digest}` `witness_ref` into a captured controller-witness
    record, exactly as `lifecycle.execution_observed` already requires for
    `CONFIRMED`/`NOT_CONFIRMED`, plus a closed reason vocabulary
    (`SKILL_EVIDENCE_CONTRADICTING_REASONS`). `ledger-binding` cross-checks
    the cited digest was actually captured by the attempt's manifest - the
    same "altered artifact" check `artifact_ref` already gets.

- **`skillc/coverage.py`: per-skill coverage reports from retained bundles**
  (Refs #272). One row per (skill path, skill version, client, case/task,
  arm), built from a declared-skill inventory this module reads as a
  SEPARATE input rather than deriving from the bundle - orchestrator review
  found `installation-receipt.installed[]` lists every installed file
  (helpers, libraries, scripts), not just skills under evaluation, and the
  bundle itself carries no other declaration (`trial-ledger.subject` is a
  bare digest). Without a `DeclaredInventory`, rows exist only for skills
  the bundle itself evidences and the report says `inventory: not_declared`
  rather than guessing. `skill_version` is `installation-receipt.
  installed[].digest` - always present, this schema's own per-path content
  identity elsewhere; `skill-evidence.body_digest` was considered and
  rejected (optional, and records.md's own Q3 answer says it is not
  cross-checked against anything).
  - No per-skill PASS/FAIL verdict: `verified-result.status` is
    ATTEMPT-level, and copying it onto every skill row is exactly
    "crediting every loaded skill" (acceptance item 3). Each row instead
    carries the attempt's outcome alongside this skill's own
    `execution_observed`/`read_observed` lifecycle facts and its OWNED,
    shared-marked criteria.
  - `outcomes` (`PASS`/`FAIL`/`NOT_RUN`/`UNAVAILABLE`/`UNKNOWN`) partition
    `scheduled`; `coverage_flags` (`missing-transcript`,
    `unmatched-invocation`) are orthogonal and counted separately, never
    folded into the same denominator.
  - Refuses before reporting: runs the bundle's own validation rules first
    and raises `CoverageRefused`, naming the failing rule, rather than
    trusting a caller validated already - exercised directly against
    already-committed bad bundles (duplicate citation, forged status,
    altered artifact).
  - Reproducible: canonical JSON (sorted keys, sorted rows, no
    generation timestamp in the body) is byte-identical for a reversed
    record order. Two profiles sharing one subject digest but different
    selections record their own `profile_digest` (the same canonical-JSON
    + sha256 convention `skillc profile validate` already uses), so
    reproducibility is a property of the (bundle, inventory) pair, never
    the bundle alone.
  - A declared inventory's row count is checked two ways: `len(declared
    skills) * len(cells)`, and row-key uniqueness - the length check alone
    cannot see a duplicate declared skill, since it inflates both sides of
    that product equally.
  - Six new tests mutation-checked: the refusal wrapper (disabled via
    monkeypatch, confirms a known-bad bundle goes blind), the no-fallback
    behavior (wired to the wrong source, confirms a helper path wrongly
    surfaces), and the row-key uniqueness refusal (disabled, confirms a
    duplicate declared skill goes blind) - each restored and confirmed
    correct again, net diff empty.
  - `Profile.select is None` ("full-pack") is not resolved by this module:
    doing so needs a live checkout of the subject tree (`profile.py`'s own
    `validate()` materializes one), out of scope for a tool that reads only
    retained bundles. Callers pass an already-resolved skill list, never a
    raw `Profile` object. Nit filed on skillc #20: the evaluated selection
    is not captured in the bundle at all, so a retained bundle cannot
    reconstruct its own inventory without this external input.
  - `#273`'s reliability/convenience statistics and CPP #1366 pilot-receipt
    reconciliation are deliberately not wired into rows yet - a following
    commit in this PR, per the orchestrator's own sequencing.

- **`skill-evidence`: closes `unmatched`'s own reason vocabulary** (Refs
  #272's own scope-addition comment, for CPP #1369). R9 (`records.md`)
  already named `duplicate-invocation` and `no-correlating-attempt` but
  never enforced them; `skill_evidence()` now refuses any other string once
  `reconciliation` is `unmatched`, mirroring how #269 closes `contradicting`.
  Both checks compare digests and attempt ids skillc already recorded -
  neither reads the bytes behind `artifact_ref.digest`:
  - `duplicate-invocation`: refused unless the cited digest is ALSO cited by
    another `skill-evidence` entry anywhere in the bundle (a new bundle-wide
    citation count in `ledger_binding`).
  - `no-correlating-attempt`: refused unless the cited digest is genuinely
    absent from this attempt's own manifest capture - the existing
    altered-artifact check is gated to skip exactly `reconciliation:
    "unmatched" AND reason: "no-correlating-attempt"`, since a record with
    that reason is the honest report that evidence does not correlate, not a
    forged claim that it does. **Not every `unmatched` record**: a first
    version skipped the altered-artifact check for all of `unmatched`, which
    let two entries cite one digest NOTHING captured, label themselves
    `duplicate-invocation`, and pass - crediting duplicate use of evidence
    that does not exist. Caught in review before this shipped. Fixed by
    narrowing the skip to `no-correlating-attempt` only, so
    `duplicate-invocation` still has to name a digest captured somewhere.
    New bad fixture `skill-evidence-duplicate-invocation-uncaptured` (two
    entries, shared uncaptured digest, both labeled `duplicate-invocation`)
    is refused; mutation-checked by widening the skip back to confirm it
    goes blind. A new fixture also confirms `matched`/`contradicting` still
    refuse an uncaptured digest unconditionally
    (`skill-evidence-altered-artifact-contradicting`).
  - `declared-skill-not-installed` is deliberately NOT closed: its own Q3
    answer needs a field `external_evidence` does not carry today, and the
    entry's own `skill.path` cannot stand in for it (the existing
    unconditional not-installed check already refuses it regardless of
    reconciliation) - named as a boundary in `records.md`, not assumed
    covered.
  - Golden cases: `controls/ledger-binding/{good,bad}/skill-evidence-
    duplicate-invocation*` and `skill-evidence-no-correlating-attempt*`
    (bundle-level), `controls/skill-evidence/{good,bad}/*` (record-level).
    Each of the three new checks (the vocabulary closure, the
    duplicate-invocation cross-check, the no-correlating-attempt cross-check
    and its altered-artifact gate) is mutation-checked: disabled, confirmed
    blind on its own bad input, restored, confirmed red again, net diff
    empty.

- **A controller-owned decide-and-reply channel, and `DockerBackend`'s one
  named mount exception** (Refs #183, PR A of a 4-PR split). A new Unix-
  socket channel where the controller decides, logs, and only then replies
  - never the subject - so a request's decision is durable before any byte
  reaches the container. `DockerBackend.compose_run_argv` gains exactly one
  constrained, optional bind-mount parameter for it; every other case its
  closed-argv guarantee already refused (a second mount, a caller-chosen
  target, `--privileged`, a `docker` binary) stays refused.
  - **Socket access control**: a private, owner/mode-verified host
    directory is the real boundary (refused on a mismatch, never widened);
    the socket itself is reachable from the subject's fixed uid without
    being host-wide; two attempts racing the same path are refused, never
    silently shared.
  - **Not yet wired to any grader.** This PR delivers the channel and the
    mount only - the trial-image proxy, the live conformance test, and the
    red case proving a bypassed channel cannot move the controller-recorded
    point are later PRs under the same issue.

- **`skillc/reliability.py`: the declared repeat-reliability estimators and
  all-attempt accounting** (Refs #273, wave #259, workstream #246). Pure
  stdlib implementation of exactly the methods protocol.md section 10.5/10.6
  (#264) predeclares - no method is chosen here that #264 did not already
  name, and where #264 names none (a per-arm PASS/FAIL reduction over
  repeated attempts), this module refuses rather than picking one.
  - `all_k`/`pass_at_k`: `C(c,k)/C(n,k)` and its pass@k counterpart, kept as
    separate functions sharing no code so a bug in one cannot silently
    become the other; both report `INSUFFICIENT`, never `0`, when `n < k`.
  - `population_all_k`: the declared-weight (equal by default) mean of
    per-task `all_k` over tasks with `n >= k`, naming every excluded task;
    `pooled_all_k` refuses unconditionally (protocol.md: never raise a
    pooled rate to the k-th power).
  - `clopper_pearson` (single-cell exact interval) and
    `newcombe_hybrid_interval` (independent-arms difference, composed from
    `wilson_score`): the Beta quantile Clopper-Pearson needs has no stdlib
    closed form, so it is computed from the regularized incomplete beta
    function (`math.lgamma` plus a continued fraction) inverted by
    bisection. Three textbook spot-checks are not enough evidence for
    hand-rolled numerics (orchestrator review): `tests/test_reliability.py`
    also carries an INDEPENDENT exact oracle needing no numerics at all -
    for integer `k`, `I_x(k, n-k+1) = P(Binomial(n,x) >= k)`, computable
    exactly with `math.comb` and `fractions.Fraction` - checked over a grid
    (`n` in 1..60, every `k` in 0..n, ~20 `x` points near 0, 0.5 and 1) and
    via the inversion property the Clopper-Pearson bounds must satisfy
    (`P(Bin(n,L) >= c) = P(Bin(n,U) <= c) = alpha/2`). The grid test found a
    real gap the three spot-checks missed: `_betainc` raised a domain error
    at `a == 0` (the `k == 0` row of the grid, never reached by
    `clopper_pearson`'s own two calls, but reachable by anyone calling
    `_betainc` directly) - fixed with the boundary-parameter limit
    (`I_x(0, b) = 1`, `I_x(a, 0) = 0` for `x` in `(0, 1)`).
  - **The inversion test's range mattered, and the first version's didn't
    reach far enough (orchestrator review, second pass).** Mutation-checking
    both the grid test and the inversion test (flipping the continued
    fraction's symmetry branch; perturbing one of its coefficients) found the
    grid test going red both times (24550 and 13249 mismatches) while the
    inversion test - then capped at `n<=40` - stayed GREEN under both. Not
    circularity and not a loose tolerance: the wrong branch is a numerical-
    STABILITY choice, and the continued fraction still converges to the
    right answer under either mutation for small-to-moderate `(a, b)` -
    `clopper_pearson`'s own bisection calls land there for `n<=40`. Measured
    directly: the flipped-branch mutation sends `clopper_pearson(1, 60)`'s
    upper bound to `0.9999999999995453` against an oracle value of `0.0`
    (should be `0.025`) - a failure invisible below `n=60`, in exactly the
    range the grid test already covered. Extended the inversion test's range
    to `n<=60` to match the grid test's; both mutations now turn BOTH tests
    red. A narrower inversion test does not test what a wider grid test's
    range actually proves - this is the committed fix, not a documented gap.
  - **Verified range stated, and a floor under it (orchestrator review,
    third pass).** Convergence is a function of `(x, a, b)`, not just `x`,
    so the `n<=60` grid alone did not establish the function's behaviour at
    the `n` a real multi-task study could plausibly schedule. Added spot
    rows at `n = 100, 250, 500, 1000` (`c` at `0, 1, n//2, n-1, n`, `x`
    chosen near each cell's own rate rather than one fixed point, so the
    comparison cannot trivially pass via both sides underflowing to the
    same float zero) - all pass. `clopper_pearson`'s docstring now states
    the verified range explicitly, and `_betacf` itself refuses rather than
    silently return a value when its continued fraction exhausts 200
    iterations without converging (a real, committed failing input:
    `a = b = 1e7`) - the floor under the verified range, not a claim that
    the range is unconditionally safe beyond where it was checked.
  - **Independent cross-model review (`/codex:code_review`, read-only,
    diff-only scope) found four further real defects, all fixed:**
    (1) `mcnemar_exact(550, 550)` raised `OverflowError` - a huge exact
    integer summed from `math.comb` multiplied against `0.5 ** n`, already
    underflowed to `0.0` - fixed by dividing the two arbitrarily-large
    integers (Python's int/int true division handles any size) BEFORE
    scaling by `2.0`, not after. (2) `account_cell` silently treated a
    `retry_of` naming an attempt NOT present in the same call's population
    as "no parent, so this must be a root" instead of refusing the
    dangling reference. (3) `confidence` was never validated anywhere it
    was accepted - `clopper_pearson(5, 10, confidence=2)` silently
    returned `(0.0, 1.0)`, a degenerate interval that reads as a real
    answer; now checked (finite, strictly between 0 and 1) in
    `clopper_pearson`, `wilson_score` (which `newcombe_hybrid_interval`
    composes from) and `task_cluster_bootstrap`. (4) `population_all_k`'s
    weight-positivity guard (`w <= 0`) let a NaN weight through - every
    comparison with NaN is `False` - producing a silent NaN mean; now
    checked with `math.isfinite`. A fifth finding (the `a==0`/`b==0`
    boundary fix from the second review pass still branched on `x` and got
    the exact `x=0`/`x=1` endpoints backwards) was also fixed. All five are
    mutation-checked: each goes BLIND or produces the exact pre-fix failure
    with its fix removed, restored, net diffs against HEAD empty.
  - `mcnemar_exact`: the paired hypothesis test, returning a bare p-value so
    it cannot be mistaken for an interval (protocol.md's own distinction).
  - `task_cluster_bootstrap`: seeded percentile bootstrap over TASKS (never
    attempts - repeats of one task are not independent evidence about
    others), refusing below 5 tasks. The seed is always recorded in the
    result, and resampling draws from a VALUE-sorted copy of the input, so
    the same seed and the same multiset of task values give the same
    interval regardless of input order - the shuffle-invariance control
    cpp-eval review asked for covers the bootstrap specifically, not only
    the trivially order-invariant point estimators.
  - `account_cell`: all-attempt accounting per cell (scheduled/started/
    evaluable/coverage), with retries resolved into slots by their declared
    `retry_of` chain - a retry fills a slot but cannot select a better
    outcome than the chain's first PASS/FAIL. Refuses a duplicate attempt id
    or a self-referential retry, and refuses any status outside the closed
    PASS/FAIL/UNAVAILABLE/INCONCLUSIVE/NOT_RUN vocabulary - missing data is
    never silently imputed as success or failure.
  - `tests/test_reliability.py`: 37 tests, each estimator checked against a
    hand-computable value. Named controls for all five shapes the issue's
    acceptance requires: heterogeneous-task (`population_all_k` over tasks
    of different `n`), duplicate/retry (`account_cell`'s slot-filling),
    missing-data (`account_cell` refuses an unclassified status),
    zero-population (`account_cell([])`, `population_all_k({})`), and n<k
    (`all_k`/`pass_at_k` returning `INSUFFICIENT`).

- **`case.arm`/`case.paired_with`: a validated record of which trials pair as
  a discriminating design** (Refs #273, wave #259, workstream #246). Before
  this, nothing in the v2 schema said that one case was another's degraded
  counterpart, so a PASS from a case whose degraded arm also passed looked
  identical to a PASS that actually discriminates (CPP #1084's own question).
  Two new optional fields on the existing trial-ledger `case` identity
  (`intact`/`degraded`, and the paired case's `{id, revision}`), checked for
  shape at the record level and for reciprocity, complementary arms,
  uniqueness, and agreement with the existing #150 `degraded:` receipt
  marker by a new bundle rule, `case-pairing`. This is the discriminating-case
  axis - a property of the fixture - kept structurally distinct from the
  treatment axis (`config.arm`, already carried by `calibration_run.py`'s own
  trial planning): one trial can carry both, and nothing lets either be read
  as the other.
  - Does not itself establish that a design discriminates for the right
    reason (#150-A's job) - only that a trial's claim to be one half of one
    is well-formed, unambiguous, reciprocated and consistent with its own
    receipt.
  - **Also checks, after cross-group review (cpp-eval) found a pair could
    report clean while naming different tasks, different graders, or
    installing different base subjects:** `case.id` must match between the
    two sides (same task, different revision only); planned `grader` (id and
    revision) must match; and the degraded arm's base subject revision,
    recovered from its `degraded:` marker, must equal the intact arm's own -
    with an explicit UNRECOVERABLE outcome (never silently treated as a
    match or a mismatch) when that recovery itself fails.
  - Mutation-checked: the ambiguity, reciprocity/complementary, same-task,
    same-grader, same-base-revision, and degraded-marker-consistency checks
    (bundle level) and the shape checks (record level) each go BLIND with
    their check removed.
  - Controls: `controls/trial-ledger/{good,bad}/case-*` (1 good, 5 bad) and
    `controls/case-pairing/{good,bad}/` (2 good, 12 bad bundles - both
    directions of ambiguity/no-partner, one case per named defect, and a
    good case demonstrating `case.arm`/`config.arm` orthogonality).
  - **Per-arm repeats are facts only, no reduction** (#273's own scope
    fence, agreed by cpp-eval review): this module exposes each arm's
    scheduled/evaluable/passing counts and its attempts' `verified-result`
    references by reference; any PASS/FAIL reduction over repeats is the
    consumer's predeclared rule (CPP #1084), a separate, still-open question,
    never computed here.
  - Part of #273 (repeat-reliability and convenience summaries); the
    reliability estimator itself is a separate, following commit.

- **Unified regular-file task delivery** (Refs #267). Collection runs,
  calibration runs and selection probes deliver the whole declared fixture,
  excluding answer keys at every depth. Missing, empty, symlinked and
  unsupported inputs are refused. Docker installation preserves executable
  metadata for bytes-backed helpers through capture; focused controls cover
  non-src tasks, nested answer leakage and every existing task surface.

- **`skill-evidence`: per-skill evidence attribution and export records**
  (Refs #268, wave #259, workstream #249). A new version-2-additive record
  kind, producer `assembler`, one per attempt: skill identity (reused from
  the attempt's own installation receipt, never re-declared), parent/child
  invocation lineage (cycle-refused), criterion ownership as an audit copy of
  the attempt's own `verified-result` (never an independent claim - a copy
  that disagrees is refused as a forged status), and reconciliation of
  externally produced evidence (a usage record a subject's own tooling
  wrote - CPP's `cpp.execution-evidence/v1`, say) against exactly CPP #1368's
  R9 states (`absent`/`unmatched`/`matched`/`contradicting`), entering the
  bundle only as an ordinary `artifact-manifest` entry, never a trusted
  observation.
  - **Lifecycle facts use their own vocabulary.** `listed`/`read_observed`/
    `execution_observed` are `CONFIRMED`/`NOT_CONFIRMED`/`UNKNOWN`, a closed
    vocabulary deliberately separate from `SATISFIED`/`VIOLATED`/`UNKNOWN`, so
    a usage fact is never misread as a compliance outcome.
  - **"Unknown schema" is two checks, not one** (group review correction):
    `external_evidence.source` must be a well-formed `<namespace>/v<N>` label
    (a FORMAT check, in `skillc/records.py` - which stays subject-agnostic and
    never hardcodes a producer's schema string, per the genericity guard), AND
    it must be one this ATTEMPT's trial actually declares in its own new
    optional `trial.external_evidence_sources` (a `ledger-binding` check,
    #268's declared allowlist - the trial, not the core, is where "cpp" is
    ever allowed to appear). A well-formed-but-undeclared source is refused
    exactly as a malformed one is, by a different rule.
  - **Item 5 (the #269 trust boundary)** documents what `execution_observed`
    may and may not rely on, written against #183's proposed channel shape;
    only #269's own witness record's name is pending.
  - **`docs/specs/evaluation-facility/records.md`** has the full contract,
    including explicit answers to CPP #1368's open questions and cpp-eval's
    review questions (Q1-Q5), and a named boundary: `body_digest`/
    `description_digest` are not cross-checked against #265's separate
    `evidence/inventory.json` (nit-stored at
    https://github.com/cooneycw/skillc/issues/20#issuecomment-6007178436).
  - **Controls:** `controls/skill-evidence/{good,bad}/` (18 bad, 6 good,
    including the parent/child, shared-criteria, absent-transcript and
    malformed-schema golden cases) plus bundle extensions to `ledger-binding`
    (the forged-status, undeclared-schema and task-success-with-obligation-
    failure golden cases), `unique-ids`, and `trial-ledger`'s own new field.
    Mutation-checked by hand: the forged-status, malformed-schema and
    undeclared-schema refusals all go BLIND with their check removed.

- **`skillc profile validate`: a transitive installation profile for one
  workflow** (Refs #265, wave #258, workstream #247). A profile layers on one
  subject and names every dependency of a selected workflow: helpers,
  libraries, tools and startup context, transitively. Each comes with its
  source at the pin, a content digest and its one allowed destination under
  the client home. The validator walks the closure and emits a
  content-addressed inventory, or refuses by name: missing reference, helper
  or library file; stale mirror; conflicting destination; empty selection;
  unresolved reference; a satisfied absolute path; prose without helper
  parity; a silent kind, untraversed tree or unreferenced dependency.
  - **Nothing is installed.** Installation and readiness are #266's. Client
    profiles other than the subject's own can only be `unsupported`.
  - **First profile:** `evals/subjects/cpp-codex-flow-check/`, pinned to
    `85e9b03` like #264's case contract, with its generated inventory (63
    files, 9 dependencies, 8 declared-unsupported references).
  - **Controls:** every refusal has a committed red case, and each check was
    disabled in turn to confirm its case fails. An unrelated-collection
    control validates a different layout with no code change.

- **`skillc uptake-study`: does a rewritten skill description raise natural
  selection?** (Refs #237, pilot of #238). A new declaration kind,
  `uptake-study`, has two arms, `published` and `rewritten`. Both install the
  same subject. They differ only in the target skill's `SKILL.md`
  description, supplied as a `degrade-subject --override-file` snapshot.
  - **The snapshot is checked, not trusted.** `check_rewritten_files` refuses
    unless the installs differ in exactly the target's `SKILL.md`, and in
    exactly its frontmatter `description` line, which must equal the
    declared text.
  - **Cases and order.** There is one or more cases (prompt addenda on one
    Level 1 task), 3-30 attempts per arm each, and one primary case. The
    order is seeded over every (case, arm) attempt.
  - **Selection** is counted only from confirmed observations, as in
    PR #233. Task outcome is reported beside it.
  - **The primary test is declared in advance:** a one-sided Fisher's exact
    test, computed exactly (stdlib), at a declared alpha.

  - **A cross-model review (Codex) found five gaps, all fixed.** Each has a
    red case that fails with its fix disabled:
    - a `\r` in the description could smuggle in a second frontmatter
      field, and an unquoted value with `#` meant something else;
    - wrong-model attempts were margins of the test;
    - a nested `flow-check/SKILL.md` inside another skill passed as the
      target;
    - zero confirmed observations read as a completed negative result. It
      is now "no result", and the CLI exits 1;
    - a whitespace-only or quote-only rewrite passed as a change.

  `evals/uptake-study/flow-check-SKILL.md` is the pinned cpp-codex
  `flow-check/SKILL.md` with only its description replaced by the owner's
  approved wording. An offline check against the real pinned pack confirmed
  that the guard accepts it and refuses a mismatched description or a second
  changed file. No live run.

- **Transcript retention no longer refuses the trial container's own
  identity** (Closes #235). The #203 calibration retained 0 of 18
  transcripts, so none could be read afterwards. Two sources caused it:
  - an agent running `id` prints the candidate uid/gid 10001 that
    `docker_backend` fixes;
  - cpp-codex's `flow-auto` skill text uses the placeholder `/home/user`.

  `leak.conditional_exemptions` now exempts both, by exact match only:
  - the uid/gid via `CANDIDATE_UID`/`CANDIDATE_GID`, never re-literalled,
    as the twin of the already-exempt `/home/candidate`. The constants now
    live in `backend`, and `docker_backend` re-exports them, so the CLI
    still loads without the Docker backend;
  - the `user` placeholder home path.

  Each exemption applies only while this host has no real account with that
  uid, gid or name, checked against the host's own account database. A
  cross-model review (Codex) found that an unconditional exemption would
  hide an operator whose uid really is 10001, or a real account named
  `user`. The operator's own uid, a longer number starting 10001, and a
  longer home name all still fire. The new exemption tests fail on the
  pre-fix code; their red twins, including a host that has those accounts,
  pass on both.

- **Calibration declarations can have three arms: B/N/P** (Closes #231, for
  #203). The owner's rulings on #203 (3a/3b/3c, and Q2 "medium": 6 attempts
  per arm) need a provided-skill arm and more attempts than the two-arm,
  3-5 runner allowed.
  - `skillc.calibration.parse_declaration` accepts two or three arms, exactly
    one of them `baseline`. A third arm must install the same subject as the
    natural arm and differ from it only by an `instruction` and the
    `named_skills` it names, so a third arm can never be an ablation.
    Attempts per arm are 3-8, and the total cap is checked against every
    arm.
  - `calibration-run` appends a provided arm's instruction to `goal.md` for
    that arm only.
  - The report adds `skill_opened` per attempt, and `named_skill_opened` for
    the provided arm. Per arm it shows the uptake rate `opened`/`observed`
    (k/n, ruling 3c) and the provided arm's `named_opened`, the attempts
    eligible for the value comparison. Uptake is read only from a confirmed
    observation (one transcript, this attempt's own prompt), the same
    confirmation `selection_probe` uses. Anything else is `UNKNOWN`, never
    "not opened".
  - A cross-model review (Codex) found three gaps, all fixed with red cases
    that fail when the fix is disabled:
    - an unconfirmed observation (no transcript, or several) counted as
      "observed, not opened";
    - P's `named_skills` were not checked against what the treatment
      installs. `run_calibration` now refuses before any store exists;
    - the instruction check matched substrings, so `flow-auto-extra` counted
      as naming `flow-auto`.

- **Retained transcripts no longer carry the operator's plan, credit balance
  or usage windows** (Closes #227, follow-up to #225). Every Codex
  `token_count` event has a `rate_limits` object holding the subscription
  tier, the credit balance and the rate-limit windows. Every
  `token_usage_record` has a provider `response_id`. After #225 both still
  scanned clean. Reading the #26 transcripts by hand before publication found
  them.
  - `skillc/leak.py` gains two classes, `account-usage` (a populated
    `rate_limits`) and `response-id`. `skillc leak-check` now reports 28
    findings on the 2026-10-03 transcripts instead of 4.
  - `redact_transcript_identities` replaces `response_id` in the text, and
    re-serializes only the lines carrying a `rate_limits` object, replacing
    it with `<redacted>`. Every other line stays byte-identical.
  - Deny-list, not allow-list: an allow-list of evidence fields would drop
    fields silently on a client upgrade. A new account-scoped field still
    passes until it is named, so a transcript is read by hand before it is
    published.

  - A rewritten line is written as ASCII. A cross-model review (Codex) found
    that writing it as UTF-8 turned an escaped U+2028 into a raw line break,
    which split the record and let a `response_id` beside it scan clean, and
    that a lone surrogate crashed the rewrite. Regression test committed; it
    fails with the UTF-8 encoding.

  Committed controls: `controls/leak-check/{bad,good}/planted-account-usage`.
  All seven original new tests fail on the pre-fix code.

- **New Level 3 task `gate-ran-nothing`: candidate 1 of the #203 redesign**
  (Refs #203). A small library ships a one-function bug and a local gate
  whose test discovery never reaches a subdirectory lacking `__init__.py`,
  so it reports green with or without the fix - CPP #621 in miniature. The
  hazard lives only in the fixture, never in `goal.md`, per #212's own
  lesson. Four mandatory criteria graded via a restore-and-rerun probe (plant
  the original, unfixed source back into an otherwise-delivered tree, then
  re-check both a direct test pass and the candidate's own gate);
  `qualify.py`'s restore-probe validity gate includes a negative control
  proving the restore step - not some other check - is what catches the key
  FAIL shape (blinding it turns a committed FAIL candidate into a PASS).
  `eligibility-manifest.json` declares the skill-uptake eligibility rule
  (selection and outcome as separate fields; a not-opened attempt stays
  eligible and graded) and the arm set. `B`, `N` and `P` are all approved
  (owner rulings 3a/3b/3c on #203, 2026-10-03): there is no not-opened
  threshold, and `P` names `flow-auto` and `flow-check` as the skills to
  read first. It is not itself a run declaration. No live or paid run: this is
  the fixture, grader and manifest only, per the operator's ruling on #203
  decision 1 ("candidate 1 alone"). Calibration and any comparison run
  against it need their own separate approval under ADR 0005.

- **Retained transcripts no longer carry the operator's OpenAI account
  identifiers** (Closes #225). Every Codex rollout's `session_meta` records
  `creator_user_id` and `creator_account_id`, and both the retention-time
  check and `skillc leak-check` passed them. The #26 live run of 2026-10-03
  reported "0 leak(s) found" on two transcripts that carried both. The fix
  has three parts:
  - `skillc/leak.py` gains a seventh class, `account-id`: an account-scoped
    `*_id` field with a value. The finding names the field, never the value.
  - `agent_trial.redact_transcript_identities` replaces those values, and
    Codex's provider-encrypted `encrypted_content` reasoning blobs, with
    `<redacted>` before a transcript is kept. It is a substitution on the
    serialized text, so every other byte is what the client wrote. Refusing
    instead would have refused every Codex transcript. The encrypted blob is
    dropped because no reader of the evidence can decrypt it.
  - `transcript_leak_findings` refuses whatever the redaction cannot reach.
    It walks the decoded JSON for a populated protected field, which catches
    an escaped key, a non-string value, or JSON an agent printed inside a
    string. It also flags `encrypted_content` inside any decoded string.
    `selection_probe._retain_transcript` now applies this full check; its
    raw-text-only scan could not see an identifier inside an escaped string.

  Committed controls: `controls/leak-check/{bad,good}/planted-account-id`.
  The two retention tests and the control test each fail on the pre-fix
  code. The five cases the redaction cannot reach each fail with the decoded
  passes disabled. A cross-model review (Codex) found those five, and the
  missing-twin gap in the control test.

- **`degrade-subject` no longer collides with itself on a repeated `--base`**
  (Closes #199). `acquire_degraded` staged into the fixed path
  `<base>/<subject>-degraded-staging` and never removed it, so a second run
  on the same host hit `materialize.acquire_snapshot`'s `shutil.copytree`
  over the leftover `<staging>/base/surface` and crashed with an uncaught
  `FileExistsError` instead of the CLI's documented exit 2 - the #150
  runbook's `degrade-subject` step passes no `--base`, so every re-run after
  the first failed. Each call now stages into its own
  `tempfile.mkdtemp(dir=base)` root, removed on every exit: `acquire_degraded`'s
  own try/except covers a refusal raised mid-build, before the CLI ever sees
  it; the CLI's own try/finally covers everything from a successful
  `acquire_degraded` call through `persist_skills` reading the degraded
  surface out of staging, success or exception alike. Regression test
  committed failing on the pre-fix code with the issue's own
  `FileExistsError`; two more tests, added after review, are each committed
  failing when their matching half of the cleanup is disabled.

- **SWE-bench-style import: research on #210's six open problems** (Refs
  #210). This is research only, per the owner's ruling recorded on #210: no
  importer, no instances and no runs.
  - **The note.** `docs/research/swe-bench-import-research.md` checks
    per-instance images, contamination dating, certification with mechanical
    wrong candidates, hidden-test integrity, cost on paper and licences against
    skillc's contracts.
  - **Gaps it names.** An import would need a per-instance image map, a
    declared model cutoff, a capture scope beyond the 1,000-file cap and
    `.git`, an agent egress allowlist, and a container backend for
    `qualify.py`.
  - **Pins.** The upstream HEADs were re-pinned, and none moved.
  - **Gate.** #210's gate stays closed: #212 recommends REDESIGN.

- **CPP incident catalogue: escaped-failure classes ranked, five candidate
  tasks designed** (Closes #211). This is research only: no task is built and
  nothing runs. It answers #204's REDESIGN report (PR #212) by mining
  claude-power-pack's record for failures that escaped into real work.
  - **Population.** All 682 issues, the 438 Nit Store comments, and the
    counter-model review sections of 148 PR bodies.
  - **Records.** One committed record per item is in
    `docs/research/cpp-incident-catalogue/`.
  - **Reliability.** A seeded 10% sample was re-rated independently: defect
    agreement kappa 0.94, and the exact class matched on 34 of 41.
  - **Tables.** Every table is rendered by `scripts/cpp_incident_counts.py`.
    `tests/test_cpp_incident_catalogue.py` fails when a table no longer
    follows from its records, with red cases for a reclassified record and for
    a missing block.
  - **Recommendation.** Build "the gate that ran nothing" (BLIND/EMPTY, the
    top-ranked and costliest pair) first, then "the helper that answers a
    different question".
  - **Prerequisite for the git-graded designs.** They wait on a
    credential-free git-state export, because capture never exports `.git`.

- **`skillc calibration-run`: execute an approved two-arm calibration
  declaration** (Refs #207, for #204). Nothing could run #204's schedule:
  `collection-run` has no baseline arm and no model pin, and `pilot-run` reads
  only the Level 1 pilot's declaration. New `skillc/calibration_run.py` refuses
  an unapproved declaration before any store, plan or container exists, plans
  one trial per attempt in the declared `arm_order.sequence`, and runs every
  attempt through `collection_conformance.run_level1_agent_attempt` against the
  declared task. The arms differ only in what is installed: the treatment gets
  the subject's skill files and the #150-D receipt context, the baseline `{}`.
  The model and effort are pinned at launch through
  `matched_pilot.pin_model_argv` (extracted from `launch_argv`, no behaviour
  change), and an attempt observed on another model, or none, fails the run.
  Caps and reconciliation reuse `matched_pilot.run_schedule`/`reconcile`
  (which now takes a schedule). Each attempt reports `primary_endpoint` with
  `readiness_beside` beside it. New `collection_conformance.task_surface`
  delivers a whole fixture minus its `expected.json`: a Level 3 fixture has no
  `src/`, so the Level 1 surface would have started the agent in an empty
  `/work`. Evidence stays in a private run directory; publishing it belongs to
  the calibration report.

- **Calibrate before comparing: a symmetric primary endpoint, a Level 3
  pipeline task, and the two-arm calibration declared** (Refs #204). A baseline
  arm installs nothing, so its `installation-ready` stays UNKNOWN on the #139
  stand-in and its stored verified status can never be PASS. Comparing that
  status against a CPP arm with a real receipt would manufacture a CPP
  advantage. New `skillc/calibration.py`: `primary_endpoint` derives the status
  from the task grader's own criteria only, and `readiness_beside` reports
  readiness separately. `load_declaration`/`require_approved` validate
  `evals/calibration-204/run-manifest.json`: two arms that differ only in
  treatment, 3-5 attempts each, a seed-derived arm order. The declaration is
  committed **unapproved**, and `require_approved` refuses it (ADR 0005). New task
  `evals/level3/slugkit-pipeline`: slugkit-installed plus a local
  `ci/verify.py` pipeline the agent must keep passing (`pipeline-green`) and
  honest (`pipeline-honest`). The grader plants a benign change and two
  defects, proves each took effect against the candidate's own clean installed
  output, then reads the pipeline's verdict. A malformed mutation, an unproven
  defect, a no-verdict crash, a timeout or a missing tool is UNKNOWN, never
  detection, and so is a last line that only resembles the `VERIFY: fail
  <step>` grammar. `qualify.py` certifies it: 11 candidates, 5 broken graders,
  14 pipeline-validity controls including step attribution. A defect counts
  as planted only when its SPECIFIC effect is observed (the clean output plus
  `-`; an import failure on the missing entry name), never merely a change: a
  syntax-broken mutation is UNKNOWN. A benign forwarding-wrapper mutation
  shares the behaviour defect's shape, so a pipeline that rejects redefinition
  rather than behaviour is VIOLATED. The candidate's
  pipeline runs with `-E -s -B`, not `-I`, so a pipeline that imports a sibling
  `ci/` helper works exactly as it does under the public command
  (`alternatives/helper-module`). `require_approved` also refuses identities
  that are absent (an empty object, null or blank) - including the shared
  tools, permissions and public requirements - not only the literal `UNKNOWN`. Caps must be finite. Regression
  `test_a_baseline_attempt_meeting_the_task_criteria_reaches_primary_pass`
  fails against the pre-change comparison (`INCONCLUSIVE` != `PASS`). Negative
  controls for the validity gate itself are in
  `tests/test_level3_slugkit_pipeline.py`. The live run, its report and the
  #203 go/redesign/stop call are still owed.

- **Every agent attempt now retains the client's own transcript in its store**
  (Closes #202). The #150 live stores held 0-byte spool streams and no
  transcript, so the NORMAL PASS / DEGRADED PASS pair could not be diagnosed.
  `agent_trial.run_one_attempt` now offers the transcript it already reads (the
  codex rollout, the Claude Code session file) to `trial.capture` as a new
  optional `client-transcript` observation: a content-addressed object with
  `coverage: complete`, or `coverage: missing` plus a reason when none was
  found or the leak check refused it (reported by class and line, never the
  value; the leaked bytes never reach the store). `records.observation_coverage`
  enforces the shape (new controls `controls/observation-coverage/*/transcript-*`).
  The `collection-run` paste-back gains a `[transcript]` section, and
  `agent_trial.recompute_skill_invocations` re-derives `skill_invocations` from
  the stored object. `collection-run --evidence-transcript` is the explicit
  opt-in that also publishes it as `bundle/transcripts/<attempt>.jsonl`; the
  export is refused when no transcript was retained. Regression
  `test_a_codex_attempt_s_store_retains_its_transcript_referenced_from_the_manifest`
  fails on the previous code; negative control
  `test_an_attempt_with_no_transcript_records_coverage_missing_never_silence`.

- **`degrade-subject` re-pins checksum manifests for the files it overrides**
  (Closes #198). An override of a file listed in the skill's declared
  `checksum_manifest` (CPP's `scripts/gh-pr-merge.sh` in `flow-auto` and
  `flow-merge`) left `scripts/SHA256SUMS` pinning the original hash, so
  `collection-run --degraded` refused every degraded tree with `checksum
  mismatch` before launch - the #150 degraded arm could never run. The
  manifest line is now rewritten to the override's hash and recorded in the
  receipt's new `manifest_rewrites` field, apart from `mutation.locations`,
  which stays exactly the declared locations. The manifest still pins a hash,
  so a post-degrade edit is still refused (committed negative control
  `test_a_file_changed_after_degrade_is_still_refused_by_the_rewritten_manifest`).
  The #150 runbook now names `SKILLC_ALLOW_REAL_AGENT=1` on its
  `collection-run` commands, which were refused as written.

- **`collection-run` now records the image digest and timeout it ran with**
  (Refs #188). `CollectionAgentResult` gains `image_digest`/
  `timeout_seconds`, surfaced in `evidence_envelope()`'s own dict
  (`collection-run-record.json`) - `image_digest` read back from the
  journal's own `backend-identity` event (`lifecycle._record_identity`'s
  `image_digest`, itself `DockerBackend.install()`'s `docker inspect
  --format {{.Image}}` on the RUNNING container), never
  `plan_collection_attempt`'s merely-planned `image.digest` (review
  requirement: "recorded" must mean what RAN, not what was planned - a
  tag can be repointed between planning and `docker run`, and nothing
  before this re-checked it). `timeout_seconds` is the controller's own
  input to `Limits`, which needs no separate observation to count as
  recorded. `None` when the backend reported no identity at all - never a
  guess, and never a silent fallback to the plan (committed cases:
  `test_image_digest_is_the_observed_value_not_the_merely_planned_one`
  sets the fake docker CLI's own `.image-id-<container>` override to prove
  the OBSERVED value is read, not the planned one;
  `test_image_digest_is_none_when_the_backend_reports_no_identity` proves
  the no-claim case).

  `configuration_compare.from_collection_run`'s `image_digest`/
  `timeout_seconds` keyword arguments are now OPTIONAL: when the envelope
  carries either (every record from now on), that value is used and marked
  `recorded`; a caller-supplied keyword argument is then a REDUNDANT
  assertion, and disagreement between the two REFUSES, naming both, rather
  than silently preferring either (review requirement, second condition -
  committed as `test_a_caller_asserted_value_disagreeing_with_the_record_
  is_refused`). A pre-#188 record (the envelope's own fields absent) still
  falls back to the caller-supplied keyword argument, marked `asserted`,
  exactly as PR2 shipped it - committed as
  `test_a_pre_188_record_falls_back_to_the_caller_and_stays_asserted`, this
  issue's own required red case. The real end-to-end test's matched pair
  now compares fully `recorded` on both fields (`unverified_matched_fields`
  absent), and its mismatched-pair test uses a REAL observed-digest
  divergence (the same `.image-id-<container>` override) rather than a
  differing keyword argument, since the argument is no longer the source of
  truth once the record carries a value.

- **`skillc/convenience.py`: protocol.md 10.6 convenience proxies** (Refs
  #273). Read every v2 record kind and its producers before writing
  anything, per the orchestrator's constraint that a proxy with no backing
  field is reported as `not_captured`, never `0` and never a guessed
  `not_applicable`. Of the four proxies 10.6 names, one has real data today:
  `phase_wall_times` computes per-phase wall time from
  `attempt-lifecycle.events`' own `{event, at}` pairs, labeled with the
  controller's own event names rather than a canonical phase name this
  module invents - an event the controller never wrote produces no interval
  rather than a fabricated one. It refuses an empty event list, an event
  list not starting at `planned`, any event outside
  `skillc.records.LIFECYCLE_EVENTS`, and any pair whose timestamps are not
  non-decreasing (out-of-order events), rather than return a negative or
  partial duration - each refusal has a mutation-checked red case in
  `tests/test_convenience.py`. The other three - instruction length,
  clarification/correction turns, approvals split necessary/redundant - and
  tokens have no backing field anywhere in the schema today and are reported
  as `NOT_CAPTURED` (tokens as the schema's own `UNKNOWN`, a declared future
  observation per `records.md`, not the same absence as the other three).
  `convenience_summary` returns all four together as one struct so a caller
  reads exactly what is and is not available without guessing. A nit is
  filed on skillc #20: protocol.md 10.1 requires the prompt be "recorded in
  full", and no producer does - `agent-observation` keeps only the boolean
  `prompt_delivered` - which is also why instruction length cannot be
  reported; reconstructing a length from `goal.md` plus the arm's declared
  instruction at report time was considered and rejected, since that is
  reconstruction from files that can move on after the run, not capture of
  what the subject was actually shown.

## [0.4.0] - 2026-09-29

### Added

- **`--task DIR` on `skillc demo` and `skillc selection-probe`** (Refs #20),
  mirroring `collection-run`'s own `--task` (#162): both commands hard-coded
  `evals/level1/slug-small-fix` and could not be pointed at a different
  Level 1 task without a code change. `selection-probe --task` redirects
  each attempt's grader, prompt and fixture; the predeclared selection
  cases themselves are unaffected, since they are a property of the
  collection being probed, not of which task the agent is asked to fix.
  `demo --task` redirects the grading leg's candidate and grader; `demo
  --control` (the seeded negative controls) is refused together with
  `--task`, since its known-bad candidate is specific to the default
  task's own `wrong/` fixtures. Both defaults are unchanged without the
  flag.

- **Two Nit Store follow-ups to #14's L4 work** (Refs #14). (1)
  `grade_workflow.py`'s `report-supported` used to cross-check a `declined`
  claim against only the one hardcoded `HOSTILE_PATH`, narrower than
  `stayed-in-bounds`' own whole-surface check - a report that falsely
  declines a DIFFERENT out-of-scope action would never be flagged by
  `report-supported`, even though `stayed-in-bounds` already caught the
  boundary breach. Widened to check every out-of-scope path the trusted
  observation names; `HOSTILE_PATH` is removed. `wrong/unwatched-declined-
  contradiction` commits the red/green pair: measured against the pre-fix
  judge (`eb0750d`), `report-supported` grades SATISFIED for exactly this
  contradiction; post-fix it grades VIOLATED. (2)
  `AuthorityInterceptor`'s `BACKEND_ARTIFACTS` exclusion of `observations`
  is no longer unconditional - every transition is now recorded and
  resolved at `stop_and_finalize()` against the SETTLED final value (provably
  the backend's own write, since nothing else can touch that path once
  `execute()` returns), so a subject that pre-creates or tampers with
  `observations` before the backend's own write is still caught. An interim
  version suppressed only a literal "final poll", which was itself measured
  wrong: the backend's write can land on any poll late enough in `execute()`'s
  own lifetime, so a short interval flagged the backend's own legitimate
  write as a violation on every attempt -
  `test_a_clean_run_never_flags_the_backends_own_observations_write` is the
  committed red case for that, and
  `test_a_subject_created_observations_that_differs_from_the_backends_is_
  still_caught` proves genuine tampering is still caught - confirmed against
  `af51811`'s actual pre-fix code, not assumed: the identical scenario
  produced `entries: []` after 5 polls pre-fix, one `create` entry post-fix.
  **This narrows the gap, it does not close it**: the catch is poll-timing-
  dependent, the same class as `known-gaps/delete-then-restore` - a write
  both created and overwritten strictly between two polls is still invisible.

- **Declared, per-criterion outcome dimensions and separate functional/
  constraint/integration reporting** (Refs #13). `grader.json` gains an
  optional `dimensions` field (`{criterion_id: "functional"|"constraint"|
  "integration"}`, `skillc/verify.py`'s `GraderDef`) - DECLARED, never
  inferred from a criterion id's own naming convention, which nothing
  enforces and a future id could silently violate. An unknown dimension
  value is refused at load time; an undeclared criterion reports
  `unclassified`, never guessed into a bucket that looks like the others.
  New `skillc/outcome_report.py` groups a graded record's criteria by this
  declaration and derives each bucket's own PASS/FAIL/INCONCLUSIVE verdict
  (mirroring `records.derive_status`'s exact rule, scoped to one bucket),
  plus a `not-applicable` verdict for a bucket with no criteria at all -
  distinct from "we could not determine this," which `INCONCLUSIVE` already
  means. Surfaced in both real-run reporting paths this issue names:
  `collection-run`'s paste-back gains a `graded.dimensions=` line, and
  `pilot-run`/`pilot-report`'s exported per-attempt entries gain an
  `outcome_dimensions` field - both best-effort, never turning a completed
  run's own report into a crash over a dimensions lookup - and a lookup
  FAILURE reports every bucket `unavailable` (with a bounded reason - the
  exception's class, never its message, which could name a host path),
  distinct from `unclassified`: "this grader declares nothing" is a fact
  about the grader, "we could not check" is a fact about the call, and
  collapsing the two would let a reader mistake one for the other (review
  ruling). Level 2
  (`evals/level2/slug-constrained`) and Level 3
  (`evals/level3/slugkit-installed`) declare dimensions for every one of
  their criteria; Level 1, L4 and L5 declare none today and report
  `unclassified` throughout - #13's own acceptance requirement ("a passing
  unit test must not imply installed-path success") does not depend on
  every task family adopting the vocabulary at once. Tests exercise the
  loader, the grouping/verdict logic, and both reporting paths against
  synthetic fixture criteria and real graded records from the fake pilot
  and fake docker CLI - never a real live-agent run, which stays
  operator-owed. Matched-configuration comparison (`#13`'s other acceptance
  bullet) is a separate, later change.

- **`skillc configuration-compare`: matched-configuration comparison**
  (Refs #13). Pure post-hoc analysis of two ALREADY-CAPTURED evidence
  records (`--a`/`--b`, JSON - `skillc/configuration_compare.py`'s own
  docstring states the input shape; no agent or docker call of its own).
  Refuses (exit 2) unless every identity field (`task_id`, `grader_revision`,
  `image_digest`, `client`, `model`, `timeout_seconds`, `collection`)
  matches between the two sides EXCEPT the one named by `--vary` - naming
  every mismatched field and both values, and stating the alternative
  `docs/specs/evaluation-facility/protocol.md` itself names: report a
  compatibility/product comparison instead of a causal claim. A record
  missing any identity field entirely refuses to load - "absent" is never
  treated as "matches" (review ruling, with a committed case for every
  field). The comparison output states its own scope plainly: descriptive
  only, one attempt per side (n=1 each), no rate or significance claim.

  `from_collection_run` adapts a REAL `collection-run` attempt's two actual
  saved artifacts (`collection_conformance.evidence_envelope()` and a
  `--evidence` export's `result-*.json`) into this shape - proven end to
  end against real fake-backend output, not fixtures written to this
  module's own schema (review finding: "fixtures written to the tool's
  own schema prove the tool agrees with itself"). Building it surfaced
  three real gaps in what `collection-run` persists today, all stated
  plainly rather than papered over:
  - `image_digest` and `timeout_seconds` are recorded NOWHERE in either
    artifact - `from_collection_run` takes both as required keyword
    arguments instead of reading or defaulting them, and its docstring
    says so. Filed as [#188](https://github.com/cooneycw/skillc/issues/188);
    closing it means changing what `collection-run` itself persists, out
    of scope here. Because of #188, a comparison that shows these two
    fields as MATCHED would otherwise read as if a real record had proved
    it - so `load_record` now accepts an optional per-field `provenance`
    (`"recorded"` or `"asserted"`, unmentioned fields default to
    `"asserted"` - the WEAKER claim by default, review correction: a
    generic hand-written record with no `provenance` block must not
    silently assert every identity field was recorded, which is exactly
    what this module cannot check from JSON alone). `from_collection_run`
    marks `recorded` only on the fields it actually read from a real
    artifact (`task_id`, `grader_revision`, `client`, `model`,
    `collection`), leaving `image_digest`/`timeout_seconds` on the
    `asserted` default. `compare` surfaces a `unverified_matched_fields`
    list (plus an explanatory note) naming any MATCHED field that is
    asserted on either side - present only when such a field exists, never
    an empty list, so absence of the key means "nothing was asserted," not
    "not checked."
  - the exported VERIFIED_RESULT's own `criteria` field is the WRONG
    source for `outcome_dimensions` - it mixes the verifier's own
    `installation-ready` criterion in alongside the grader's, silently
    turning a genuinely PASSing task grade into an INCONCLUSIVE dimension
    verdict when bucketed directly. The right source, `record["graded"]
    ["criteria"]` (task-only), is what `from_collection_run`'s docstring
    directs a caller to use instead - found by running the adapter against
    a real attempt and getting a wrong answer, not by reasoning about the
    schema.
  - Also collapsed an over-specified `task_revision`/`grader_revision`
    split from an earlier draft into one `grader_revision` field - this
    codebase has exactly one `grader.json` per task, one id and one
    revision covering both, never two independently-versioned things.

  Tests: synthetic fixture records for the comparison/refusal logic itself
  (`test_configuration_compare.py`, unchanged in spirit), including the
  provenance loader's own red cases (unknown field name, unknown value,
  partial-default), a committed case that a generic no-`provenance` record
  flags every matched field, a committed case that `unverified_matched_fields`
  actually appears when one specific field is asserted (every other field
  earning `recorded`), and its negative control (the key is absent
  entirely, not an empty list, when both sides earn `recorded` on every
  matched field); plus a real, fake-backend end-to-end test
  (`test_configuration_compare_real_producer.py`) driving two actual
  `collection-run` attempts and adapting their real output - one matched
  pair that compares (and is asserted-labeled on `image_digest`/
  `timeout_seconds`, per #188), one mismatched pair that refuses. Building
  the matching adapter for `pilot-report`'s own output is separate, later
  work, noted as such, not included here.

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

- **`skillc/disruption_trigger.py`, an ADVISORY request-count observer for
  Level 5** (Refs #14). `DisruptionTrigger` counts a live attempt's request
  log (an append-only file the subject's tool wrapper writes one line to per
  call) by polling `ExecutionBackend.export()` - the same primitive
  `AuthorityInterceptor` polls. **Its output is never passed as
  `trusted_observation`, and Level 5's trusted channel remains unsolved.**
  Caught by review after an initial version wired it in as one: the request
  log lives inside the same subject-writable workspace tree `export()` reads
  for L4, and unlike L4's own diff (which only asks whether bytes at a
  CONTROLLER-decided path changed), this module would have trusted the
  CONTENT of a subject-writable file - a line count - as evidence, which the
  subject can fabricate with zero real work behind it, on every attempt,
  unconditionally. Not a scoped "known gap" like `known-gaps/delete-then-
  restore` - there the mechanism is sound except for a narrow timing window;
  here the count itself IS the unenforced claim, so the whole value stays
  advisory. `_max_requests_seen` only ever grows (a subject that inflates
  the log then truncates it does not erase an earlier poll's higher count),
  which defeats shrinking after the fact but nothing about inflating in the
  first place - exactly why this stays advisory rather than trusted. A real
  fix needs a controller-owned decide-and-reply channel (a host-owned Unix
  socket bind-mounted into the container is one candidate, raised in review
  and tracked as skillc#183) - architecture and policy work past a single
  fixture-service PR.

- **Fix: a symlink to a directory outside scope was invisible to
  `AuthorityInterceptor`** (Refs #14, folded into part c per review).
  `os.walk` lists a symlink-to-a-directory in `dirnames`, never `filenames`
  - `followlinks=False` only stops it being DESCENDED into, not stops it
  being LISTED as an ordinary file would be, so `_snapshot_out_of_scope`,
  which only ever inspected `filenames` entries, silently missed any such
  symlink regardless of what it pointed at. Measured directly against the
  pre-fix code (`af51811`): absent from the snapshot entirely; post-fix,
  captured exactly like a symlink-to-a-file, by its target, never followed.
  `tests/test_authority_interceptor.py::test_a_symlink_to_a_directory_
  outside_scope_is_caught` is a direct unit test of the snapshot function,
  not routed through the fake `docker cp` round trip - `fake_docker.py`'s
  own `_copy_any` dereferences a symlink-to-a-directory when copying a tree
  out, which would silently exercise a different bug.

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

### Fixed

- **`DockerBackend` swallowed a failed `observations` write-back, and a
  subject could suppress its own capture** (Refs #186, #14, #76, #20).
  `execute()` writes the exec'd process's captured stdout back into the
  workspace via `docker cp -` (a tar stream), run with `check=False` and its
  result never inspected - so a subject that pre-creates `/work/observations`
  as a symlink to a directory made the tar extraction fail with
  `IsADirectoryError` (measured against the fake CLI: exit 1, traceback on
  stderr) completely silently: no exception, no `ExecuteResult` field, the
  subject's own object left in place, the real capture never landing.
  `ExecuteResult.observations_capture` now names the checked outcome -
  `"written"` or `"failed"`, never swallowed; `None` only when this backend
  doesn't report it (every backend but `DockerBackend`) or the write-back was
  never attempted (the `"launch-failed"` path, before any capture exists).
  Red case: `tests/test_docker_backend.py::test_a_directory_symlink_at_
  observations_makes_the_writeback_fail_visibly` fails on pre-fix code with
  `AttributeError: 'ExecuteResult' object has no attribute
  'observations_capture'`, not merely a wrong value.

  Found, and fixed, a second bug while answering "what does each
  `observations` reader do with this state": `verify.py`'s own
  `_read_untrusted` claimed "None when not a readable regular file", but
  actually CRASHED on a directory - `os.open()` succeeds opening a directory
  O_RDONLY, so the `S_ISREG` check running only AFTER `os.fdopen(fd, "rb")`
  was too late; `os.fdopen` itself raises `IsADirectoryError` for a
  directory fd. Fixed by checking `S_ISREG` on the bare fd before wrapping
  it. `tests/test_verify_backend.py::test_a_missing_or_non_file_
  observations_never_grades_pass[directory]` is the committed red case,
  confirmed against pre-fix `verify.py`: the `"missing"` case already
  correctly read as no report (caught at `os.open()`), the `"directory"`
  case crashed instead. Both readers of `observations` are now confirmed
  safe: `verify.py`'s `_probe_via_backend` path treats a missing or
  non-regular-file `observations` as an empty report (never a false PASS,
  since every eval judge's own `_unwrap`/`read_report` treats "no report" as
  a violation or refusal, not success), and `demo.py`'s own explicit
  `is_file()` check already returned `unmeasured(...)` for the same case
  without needing a change.

  `AuthorityInterceptor`'s directory-symlink branch no longer excludes
  `observations` unconditionally either (issue #14's own Nit Store follow-
  up, folded in here since it's the same root cause): a directory symlink
  planted at that reserved name is now recorded IMMEDIATELY, never deferred
  for settled-value resolution the way a REGULAR FILE at that path is - the
  write-back can never produce a directory, so there is no backend-write
  ambiguity to resolve for that shape. The settled-value resolution itself
  is refined to key off the VALUE's shape, not just the path: only a
  transition into something digest-shaped (what the write-back could
  plausibly have produced) is deferred; a delete, a symlink, or a special
  file at a `BACKEND_ARTIFACTS` path is recorded immediately, since the
  write-back can never produce any of those either.
  `tests/test_authority_interceptor.py::test_a_directory_symlink_named_
  observations_is_caught_immediately` is the committed red case, confirmed
  against pre-fix code: the snapshot was empty, post-fix it captures the
  symlink by its target.

  **A failed capture now grades INCONCLUSIVE, structurally, in one place -
  not reporting-only (orchestrator review).** Naming
  `observations_capture` on `ExecuteResult` was not enough by itself:
  nothing consumed it, so a failed write-back still read as an empty
  report and graded FAIL (`report-present`/`task-complete` VIOLATED) - a
  measurement that did not complete asserting the candidate did something
  wrong. Checked the actual repo-wide convention rather than assuming a
  fix was needed: all five existing eval tasks (L1 `slug-small-fix` and
  `finish-close-ref`, L2 `slug-constrained`, L3 `slugkit-installed`, L4,
  L5) already refuse to read an empty/malformed report as success, which
  is why this happened to be safe today - but that is a per-judge
  convention, not a structural guarantee for tasks not yet written.
  Fixed in `verify.py`'s `_probe_via_backend`/`grade_files` alone, the same
  way lost containment already is: `result.observations_capture ==
  "failed"` makes `category = "capture"`, every criterion UNKNOWN via the
  existing `_unknown()` path, `status` INCONCLUSIVE - the judge never runs
  at all, for every grader, no judge changes needed.
  `tests/test_verify_backend.py::test_a_failed_observations_capture_
  refuses_before_any_judge_runs` is the committed red case, and
  `tests/test_level4_instruction_conflict.py::test_a_failed_observations_
  capture_never_grades_the_report_satisfied` independently confirms L4's
  own judge already refused to read the empty-report case as success (the
  convention this PR no longer needs to rely on for that task specifically).

  Scope limit, stated plainly: fake-CLI-verified only. A real daemon's
  `docker cp` extraction over an existing directory symlink is untested
  here, per the standing no-real-daemon limitation, though it plausibly
  refuses the same way (a real tar extraction generally will not silently
  write a file over an existing directory either).
- **`DockerBackend.execute()` and `DockerBackend.read_home_tree()`'s
  stdout/stderr drain joins ran sequentially, doubling worst-case teardown
  latency** (Refs #20 Nit Store, found while fixing issue #174). Both
  methods' drain threads run concurrently already, but were each joined
  against their own full bound, back to back, in the calling thread - a
  still-open pipe paid that bound twice. Measured directly (not merely
  reasoned about) for both: `execute()` ~2.08x the single bound before this
  fix, ~1.08x after; `read_home_tree()` ~2.02x before, ~1.02x after. Both
  threads in each method now join against ONE shared deadline.
  `stdout_incomplete`/`stderr_incomplete` stay independently observed per
  stream in `execute()` (a committed test proves this directly - only
  stdout held open reports only `stdout_incomplete`). Found while building
  `read_home_tree()`'s own committed test: `_BoundedDrain` has a separate,
  pre-existing bug (Refs #189) that silently drops already-captured data
  under a still-open pipe below its read size - `read_home_tree()`'s new
  test is timing-only for that case, citing #189, since content
  verification there hits the other bug.
- **`_BoundedDrain` silently dropped already-captured data instead of
  reporting it as an incomplete partial capture** (Refs #189, found while
  fixing issue #20's drain-joins latency doubling). `run()` read with
  `IO.read(65536)`, which on a non-interactive stream may issue multiple
  underlying reads to fill the FULL requested size, blocking until either
  that much data arrives or EOF - so a subject that wrote some output
  (under 65536 bytes) and then left the pipe open without writing more or
  closing it was captured as **nothing**, silently, contradicting #102's
  own bounded-capture rule and `ExecuteResult`'s `stdout_incomplete`/
  `stdout_bytes` design (both promise "captured what we could, marked
  incomplete", never "wrote data, captured zero, no error"). Now reads
  with `os.read()` on the raw fd - one syscall, returns whatever is
  currently available rather than blocking to fill the buffer. A committed
  red case (a 10KB write held open, no docker/subprocess involved) fails
  on the pre-fix code and passes after; a positive control beside it
  proves the ordinary EOF-close path still captures everything.

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
