# Support matrix (#80, Refs #10)

- Status: what the facility supports today, restated from actual results,
  not from intent.
- Governing documents: [interfaces.md](interfaces.md) (the conformance table
  this restates), [spec.md](spec.md) (the EF-01..EF-11 requirement codes).

## Evidence rule

**This matrix is re-stated after the operator's live run, from its results,
not from intent** (#80's own stated evidence rule). Every row below that says
`demonstrated-here` was demonstrated against the fake `docker` CLI
(`tests/fixtures/docker-backend/fake_docker.py`) - CI's own Docker-shaped
green, not a live daemon. A row marked `owed-to-live-run` is not weakened by
a passing test anywhere in this repository; it can only move to
`demonstrated` once the operator has actually run it against a real Docker
daemon and that run's results are what gets pasted back here - never a
description of what the code is expected to do.

## Clients and pinned versions

Consumed by `#78`'s trial image (`docker/trial/`), read from the single
source of truth (`docker/trial/pinned-versions.json`, checked against the
Dockerfile by `docker/trial/check_pins.py`):

| Client | Package | Pinned version | Pinned on |
|---|---|---|---|
| Claude Code | `@anthropic-ai/claude-code` | 2.1.283 | 2026-09-26 |
| Codex | `@openai/codex` | 0.157.1 | 2026-09-26 |

Never `@latest` - a floating version would make "what ran" unverifiable
after the fact, the same reasoning `CANDIDATE_UID` being fixed (below)
serves for identity.

## Layouts and genericity (EF-01)

`skillc materialize` (#7) is proven generic by declaration, not by a single
collection's shape, against two independently-authored collections:

| Collection | Layout | Invocation metadata | Proven by |
|---|---|---|---|
| claude-power-pack (CPP) | Native Claude Code skills | `disable-model-invocation` (SKILL.md) | #7's original subject |
| mattpocock/skills (#11) | Bucketed layout, manifest-scoped shipped surface | Codex-native (`policy.allow_implicit_invocation`, `agents/openai.yaml`) | `tests/test_materialize.py::test_the_subject_guard_sees_a_planted_mattpocock_branch` |

`--target portable` (the Agent Skills specification) and `--target
claude-code` (plus its documented extensions) are both supported; `skillc
selftest` is itself target-aware (`controls/<rule>/targets/<target>/`).

## Execution backends

skillc ships exactly one backend today: `skillc.docker_backend.DockerBackend`
(#77). The seam (`skillc/backend.py`) is generic - nothing in skillc names,
imports or assumes any other backend - but none other exists in this
repository.

### `DockerBackend.describe()`'s claims, verbatim (2026-09-26, commit range
#77/#83/#85)

**Isolation claimed:**

- container (pid/mount/network namespaces)
- network=none by default
  - since #11: an agent container built by `collection_conformance.agent_backends`
    instead claims `network=bridge: egress OPEN (owner ruling on issue #11; agent
    containers only)` and drops the "egress actually blocked" line below; the
    grading container keeps `network=none`
- fixed non-root user 10001:10001 (candidate), independent of the host caller
- resource limits enforced: memory, memory-swap (equal), pids, cpus, shm-size
- disk: no per-container bound set (`disk_limit` is `None`) - or `--storage-opt
  size=<disk_limit>` when configured
- every container labeled `skillc.managed=true` and `skillc.attempt-id=<attempt id>`
- sandbox: unsandboxed-container-is-the-fence
- no docker socket, no docker binary, no passthrough flags in the composed argv
- one persistent container per attempt (`docker run -d` at `prepare()`);
  `install()`/`execute()` act on it via `docker cp`/`docker exec` - no bind
  mount, no shared volume, no second container

**Explicitly NOT established (required, not optional, per interfaces.md's
"Execution backend" section):**

- network egress actually blocked - not verified from inside the container
- file reads by candidate code
- credential confidentiality against an ancestor's `/proc/<pid>/environ` -
  the verifier's own boundary (`verify.py`'s probe through this same seam)
- **the live daemon boundary itself** - tested here only against a fake
  `docker` CLI, never a real daemon; this is the single largest gap this
  matrix records, and it is why every `demonstrated-here` row below is
  qualified rather than an unqualified `demonstrated`
- a disk bound actually enforced - `--storage-opt size=` is refused outright
  by any storage driver other than `overlay2` on a compatible backing
  filesystem, so a set `disk_limit` is a request, not a guarantee
- a graceful signal delivered to the exec'd subject itself on timeout or
  cancellation - `docker kill` reaches the container's own init/placeholder
  process, never a separately exec'd session, so the escalation only bounds
  when the whole attempt stops, not whether the subject got a chance to
  flush anything (a true per-subject signal needs an in-container
  supervisor - [Nit Store #20](https://github.com/cooneycw/skillc/issues/20))
- dependency resolution inside the container - `install()` copies in any
  declared surface entry naming an existing host path; it does not run a
  package manager or resolve a dependency closure
- `baseline_absence`'s own content check - it compares declared entry NAMES
  against a top-level listing of the container's workspace taken before any
  copy (issue #133 item 4), so a same-named file whose CONTENT differs from
  what the image already shipped is not distinguished from one this attempt
  genuinely installed; only the name-level contamination case is caught

Regenerate this section from `DockerBackend(image=..., base_dir=...).describe()`
directly rather than hand-editing it out of sync with the code - it is a
verbatim copy of that call's output, not a paraphrase.

## Demonstrated on a real daemon (operator live run, 2026-09-27)

The operator ran `skillc demo`, `--control` and `--subject` for both
collections at commit `8e06030`, on native Docker Engine, Linux x86_64.
Evidence: the leak-checked paste-back blocks and EXIT lines posted on #10
(https://github.com/cooneycw/skillc/issues/10#issuecomment-5855368984). Each row here is taken from that output, not from intent:

| What | Result on the real daemon |
|---|---|
| Trial image build (`docker/trial/`), including pinned CLIs, the `codex-code-mode-host` sidecar check, the no-docker-binary refusal and the interpreter check | succeeded; image `sha256:d1b2ced9dc6d25e9e1bc673c1973f032ced50a11da234fcd617ee376ff36eefc` |
| Full lifecycle, `prepare` through `confirm_absent` | `disposition=captured` on all three demo runs |
| Grading through the verifier's backend seam (#76) | `PASS`, all mandatory criteria satisfied |
| Image digest that ran, recorded | MET: the digest above appears in every block |
| Cleanup sweep, label-scoped | every reap outcome `already-absent`, `daemon_reachable=True` |
| Declared host paths unchanged | `changed=[]`, `unresolved=[]` on every run |
| `--control`: the seeded failures (reply-only client never touching the canary; a container deliberately left running; a leaky composition, meaning a known-bad grading candidate and a planted host value in a paste-back) | all caught, `EXIT=0`. The output is one aggregate line with no per-case breakdown. Each case being caught is entailed by `skillc/demo.py`'s `run_control`, which returns true only when every seeded failure is caught; it is not printed separately |
| `--subject cpp-codex` (claude-power-pack @ `85e9b03a`) | 74 skills / 273 files installed; in-container digests matched; 74/74 discovered by the client's own listing |
| `--subject mattpocock-skills` (@ `c55ee460`) | 2 skills / 7 files installed; digests matched; 2/2 discovered |
| Exit codes | `EXIT=0` for all four commands; no traceback anywhere |
| `collection-run` on Claude Code 2.1.283 (#124): `cpp-claude-code` (CPP `.claude/skills`, 18 skills) and `mattpocock-skills-claude-code` (2 skills) | both captured, graded PASS; every selected skill `listed` in the transcript's `skill_listing` (discovery observed from the transcript, not a model-free canary: Claude Code has none); missing-credential control `unavailable`; host login unaffected. Evidence: [evals/claude-code-agent-arm](../../../evals/claude-code-agent-arm/README.md) |

**Proven against the fake `docker` CLI and `FakeBackend` only**, by owner
ruling (2026-09-27; see [ADR 0005](../../decisions/0005-runtime-scope-and-cost-rulings.md)
rule 6), which accepts this coverage for #10:

| Failure path | Real-daemon status |
|---|---|
| Timeout | fake-only; real-daemon seed tracked in #122 |
| Operator cancellation | fake-only; real-daemon seed tracked in #122 |
| Provider unavailable | fake-only (seeding it means stopping the operator's daemon) |
| Capture failure | fake-only (no portable way to make a live `docker cp` fail) |
| Empty task selection | fake-only (decided before any container exists; identical driver logic) |
| Teardown failure | fake-only (a real `docker rm` cannot be forced to fail generically) |
| Launch failure | fake-only (a failing `docker run` surfaces as the same `BackendUnavailable` the tested daemon-unreachable path raises, so it is covered only incidentally; no dedicated test plants a rejected image) |
| Kill-by-signal | fake-only (timing-fragile; overlaps the timeout seed) |

**Still not established by any run**, live or fake: network egress
actually blocked, verified from inside a container; and anything about a
skill being selected, changing behaviour or helping (#26, #12). A real
client starting, completing a turn and satisfying the liveness canary WAS
established by #11's live `skillc collection-run`, once per collection (both
captured, graded PASS; [evidence](../../../evals/second-collection-conformance/evidence/README.md)),
with the agent container's egress open by owner ruling.
The conformance table below keeps its fake-daemon statuses, because it
mirrors `tests/test_docker_conformance.py`; this section is the live
evidence alongside it.

## Conformance cases (interfaces.md), restated with status

Full detail and citations: `tests/test_docker_conformance.py`'s
`CONFORMANCE_CASES` table, which this section mirrors -
`test_every_conformance_case_has_a_definite_status_and_a_citation` fails if
they drift apart.

| Case | EF codes | Status | Where |
|---|---|---|---|
| CPP and a second collection | EF-01 | demonstrated-elsewhere | `tests/test_materialize.py` |
| Missing required skill/helper or baseline contamination | EF-03 | demonstrated-here | `tests/test_docker_backend.py::test_install_reports_discovery_canary_violated_when_nothing_is_declared`, `::test_install_reports_a_partial_install_as_violated_not_masked_by_a_success`, `::test_install_reports_baseline_contamination_for_a_preexisting_entry` |
| Out-of-root write, symlink escape or repeated cleanup | EF-02, EF-10 | demonstrated-here (repeated cleanup, host immutability) / owed-to-live-run (escape prevention) | `tests/test_docker_conformance.py` |
| Incorrect output with forged success prose/JSON | EF-04, EF-08 | demonstrated-elsewhere | `tests/test_verify.py::test_forged_success_claims_do_not_change_the_verdict` |
| Agent replaces local tests, checker or pass file | EF-05, EF-08 | demonstrated-elsewhere | `tests/test_verify.py::test_replaced_local_tests_and_grader_do_not_change_the_verdict` |
| Candidate code writes verifier outputs | EF-05, EF-08 | demonstrated-elsewhere (grader boundary) + demonstrated-here (backend instance isolation) | `tests/test_verify.py`, `tests/test_docker_conformance.py::test_two_attempts_never_share_container_state` |
| Stale/cross-trial receipt, altered artifact or missing required digest | EF-07, EF-08 | demonstrated-elsewhere | `tests/test_verify.py::test_a_stale_receipt_is_not_graded` |
| Missing events, truncated output or unavailable provider | EF-07 | demonstrated-here (backend) / demonstrated-elsewhere (grader) | `tests/test_docker_conformance.py::test_provider_unavailable_through_the_real_backend`, `tests/test_verify.py::test_a_judge_that_hangs_or_prints_no_object_is_INCONCLUSIVE` |
| Always-pass, always-fail, crashed or silent grader | EF-05 | demonstrated-elsewhere | `tests/test_verify.py::test_blind_graders_are_the_certification_gates_to_catch` |
| Frozen output regraded by the same deterministic grader | EF-05, EF-08 | demonstrated-elsewhere | `tests/test_verify.py::test_a_regrade_repeats_the_outcomes_and_keeps_the_original` |

**None of the above is `demonstrated` unqualified.** Every `demonstrated-here`
row was run against the fake `docker` CLI; every `demonstrated-elsewhere` row
needs no Docker at all (grader/controller behavior only) and so is closer to
a real demonstration, but even those have never been exercised inside an
actual trial end to end. The facility becomes reviewable, per spec.md, when
EF-01 through EF-08, EF-10 and EF-11 are demonstrated for this stated support
matrix - EF-06 (matched comparison) and EF-09 (progressive qualification)
apply to a later multi-arm/multi-level experiment, not to a single backend's
conformance, and are out of this matrix's scope.

## EF-11: static use needs no Docker

Proven in `tests/test_no_docker_required.py`:

- `skillc.cli` does not import `skillc.docker_backend` at module load
  (checked in a fresh subprocess; a committed redcase,
  `tests/fixtures/conformance/imports_docker_backend_at_load.py`, proves the
  check itself can report the other verdict).
- `skillc check` and `skillc selftest` (and `rules`, `--version`) complete
  successfully under a PATH with no `docker` executable reachable at all - a
  positive control first proves that PATH construction actually makes
  `docker` unreachable, so the green result is not vacuous on a host that
  happens to have Docker installed anyway.

## Gaps, stated plainly

- **The live daemon boundary is untested by this repository's own CI.** The
  operator's live run crossed it for the rows listed under "Demonstrated on
  a real daemon" above, and for nothing else. Every claim in this matrix marked `demonstrated-here` is proven
  against a fake CLI that runs the "subject" as an ordinary host subprocess
  with no namespaces, no cgroups and no network restriction of its own - it
  proves the LIFECYCLE state machine and the composed `docker` argv, never a
  containment boundary. This is `describe()`'s own single largest
  `unobserved` claim, repeated here so a reader of this document does not
  have to go find it.
- **A true per-subject graceful signal on timeout/cancellation** needs an
  in-container supervisor this backend does not provide; `docker kill`
  reaches the container's own placeholder process, not a separately exec'd
  session (routed to the Nit Store, issue #20).
- **`baseline_absence` is never independently verified** - always reported
  `SATISFIED`, matching the reference `FakeBackend`'s own scope, not a real
  check of the image's existing contents for an undeclared skill.
- **EF-06 (matched comparison) and EF-09 (progressive qualification)** are
  not addressed by this matrix at all - they describe a multi-arm experiment
  and a multi-level reporting boundary respectively, neither of which a
  single backend's conformance can establish on its own.
