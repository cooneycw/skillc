# Changelog

All notable changes to skillc are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Dates are the day the
work landed on `main`, not the day a version is tagged - see
[#72](https://github.com/cooneycw/skillc/issues/72) for the release checklist
and version plan.

## [Unreleased]

### Added

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
