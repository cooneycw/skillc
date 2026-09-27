"""Second-collection agent-run conformance (issue #11's remaining acceptance
bullet: "the same client, Level 1 fixture, contract and grader").

`evals/second-collection-conformance/README.md` states the gap this module
closes precisely: the no-agent `--subject` leg (`skillc/demo.py`, issue #101)
proves a declared skill collection installs intact into a real container and
that the client can see it - explicitly NOT that any skill is invoked,
selected, or helps. Bullet 2 needs an agent actually WORKING the Level 1 task
(`evals/level1/slug-small-fix`) with each collection's own selected skills
installed, through the SAME client/contract/grader `agent_trial.py` (#106)
already drives every other real-agent attempt through.

ONE real agent attempt, per collection, composed from pieces this module
does not reinvent:

  - `agent_trial.run_one_attempt` (#106) - credential delivery, the transcript
    adapter, the liveness canary, and the grading gate, unchanged;
  - `skill_name=None` (issue #26) - the SKILL-FREE canary mode: the
    instruction names no skill, so any skill the agent invokes on its own is
    an observation (`TranscriptObservation.skill_invocations`), never an
    artifact of a prompt that told it which one to use. #11 measures
    collection conformance, not skill selection - #26's own job - and naming
    a skill here would contaminate exactly the measurement #26 needs to make
    later;
  - `demo.load_demo_subject`/`demo.acquire_subject_checkout`/
    `materialize.acquire_snapshot`/`materialize.inventory`/
    `demo.subject_surface_files` (issue #101) - the SAME subject-loading
    pipeline the no-agent `--subject` leg already uses, reused rather than
    duplicated, so a subject declaration is read exactly once, one way, by
    the whole codebase;
  - `agent_trial.run_one_attempt`'s own `extra_home_files` parameter (issue
    #11) - delivers the collection's selected skill files into the SAME
    container the agent runs in, at the same `.codex/skills/<dir>/...`
    layout `demo.install_subject` already uses for the no-agent leg.

STRUCTURALLY UNABLE TO LAUNCH A REAL AGENT WITHOUT `SKILLC_ALLOW_REAL_AGENT=1`
- this module adds no gate of its own; every call passes through
  `agent_trial.run_one_attempt` and therefore `lifecycle.run_through_backend`'s
  own existing `_refuse_real_agent`, unchanged.

FUNDING BASIS for the real agent call, quoted verbatim rather than paraphrased
(ADR 0005 rule 6, owner ruling 2026-09-27): "Normal Claude and codex" - the
operator's own normal Codex subscription login, inside the normal usage
budget, never metered API spend and never gated by the #12 $5 judge-call
ceiling (rule 5), which covers judge/provider-API calls only.

NO REAL MODEL CALL ANYWHERE IN THIS MODULE'S OWN TEST SUITE, mirroring
`agent_trial.py`'s own acceptance: `tests/test_collection_conformance.py`
runs entirely against the fake `docker` CLI, a committed fixture collection
(never a real subject's real git remote), and
`tests/fixtures/agent-trial/fake_agent_client.py`. THE REAL RUN, ONCE PER
COLLECTION, IS OWED TO THE OPERATOR'S OWN LIVE SESSION - never claimed by
this module's own green tests, exactly as `demo.py`'s own real-Docker leg
states throughout.

Generic over `subject_name` (issue #11's "no subject-name branch anywhere in
`skillc/`", `tests/test_materialize.py`'s AST genericity guard, which covers
every `skillc/*.py` module the moment it exists): this module never branches
on which collection it was given.

Stdlib only (AGENTS.md), plus this repository's own modules.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import agent_trial, credential, demo, materialize, reap, trial, verify
from .backend import Limits
from .docker_backend import ATTEMPT_LABEL_KEY, OWNER_LABEL_KEY, OWNER_LABEL_VALUE, DockerBackend

#: The Level 1 task's own starting state (`evals/level1/slug-small-fix/fixture/src`)
#: - installed into the agent's `/work`, never the sibling `fixture/expected.json`
#: (the grader's OWN ground truth for this fixture - "this candidate should
#: FAIL, violating reported-example and R3" - which would hand the agent the
#: answer key if it ever reached the container). Only `src/` is a candidate
#: file `qualify.py`'s own certification treats as installable state; every
#: other candidate directory (`reference/`, `wrong/*/`) is shaped the same
#: way for the same reason.
_FIXTURE_SRC_DIRNAME = "src"

#: The AGENT container's network. A hosted-model client must reach its
#: provider, and `DockerBackend`'s own default (`"none"`) made every real
#: attempt unable to: the first live `collection-run` delivered its prompt,
#: then every request failed and codex exited 1 - `inconclusive`, never graded.
#: Owner ruling, recorded on issue #11 (2026-09-27): "i'm fine for a container
#: (controlled by what we place into it) to have network access. i'm not going
#: to submit hostile repos". Only the agent container gets it - the GRADING
#: container keeps `DockerBackend`'s `"none"` (`agent_backends` below).
#: REVERSAL TRIGGER: revisit (a provider-only egress allowlist or proxy) the
#: moment skillc is pointed at a subject, fixture or collection the operator
#: did not choose and trust - the ruling's premise is no hostile inputs.
AGENT_NETWORK = "bridge"

#: The real client invocation when the caller supplies none. `--skip-git-repo-check`
#: is required, not a convenience: the trial workspace `/work` is not a git
#: repository, and codex-cli 0.157.1 refuses to start outside one ("Not inside
#: a trusted directory and --skip-git-repo-check was not specified") - the
#: first live run exited 1 in 0.4s on exactly that.
DEFAULT_CLIENT_ARGV = ("codex", "exec", "--sandbox", "danger-full-access", "--skip-git-repo-check")

#: The agent's own wall-clock limit, separate from the per-docker-call
#: `daemon_timeout`: one `--timeout` used to feed both, so the runbook command
#: (no `--timeout`) would have killed a real agent after 30 seconds.
DEFAULT_AGENT_TIMEOUT = 900.0


@dataclass(frozen=True)
class TrackingDockerBackend(DockerBackend):
    """A `DockerBackend` that remembers every attempt id it was asked to
    `prepare()` - the agent's own attempt and each grading probe's random
    `probe-<hex>` id alike - so a cleanup check can ask the daemon about THIS
    run's containers by their attempt label, rather than attributing every
    skillc-owned container that appeared meanwhile to this run (codex review:
    `reap.diff` documents that it cannot establish causation)."""

    prepared_ids: list[str] = field(default_factory=list, compare=False)

    def prepare(self, attempt_id: str) -> object:
        self.prepared_ids.append(attempt_id)
        return super().prepare(attempt_id)


def attributable_leftovers(
    docker_bin: Sequence[str], attempt_ids: Sequence[str], timeout: float,
) -> list[str] | None:
    """Every container still carrying skillc's ownership label AND one of
    `attempt_ids`' attempt labels - `None` when the daemon could not be asked
    about any one of them, never an empty list standing in for "unreachable".
    An empty `attempt_ids` is also `None`: nothing was checked, so nothing can
    be claimed clean."""
    if not attempt_ids:
        return None
    found: list[str] = []
    for attempt_id in attempt_ids:
        names = reap._list_names(
            docker_bin, None, timeout, [(OWNER_LABEL_KEY, OWNER_LABEL_VALUE), (ATTEMPT_LABEL_KEY, attempt_id)],
        )
        if names is None:
            return None
        found.extend(names)
    return found


def agent_backends(
    *, image: str, base: Path, docker_bin: Sequence[str], daemon_timeout: float,
) -> tuple[TrackingDockerBackend, TrackingDockerBackend]:
    """`(agent backend, grading backend)` for one collection run. The agent
    backend runs on `AGENT_NETWORK` (see its comment for the ruling); the
    grading backend is left on `DockerBackend`'s own default, deliberately
    not passed a network, so the grader never gains egress by this ruling."""
    agent = TrackingDockerBackend(
        image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=daemon_timeout, network=AGENT_NETWORK,
    )
    grading = TrackingDockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=daemon_timeout)
    return agent, grading


def new_run_root(base: Path, subject_name: str) -> Path:
    """A fresh, unique directory under `base` for ONE run's checkout, staging
    and store. Fixed `<base>/<subject>-checkout` names made a second run of the
    same subject on a host fail at `git clone` (the first run's checkout was
    never removed), and two concurrent runs would share one directory - the
    same defect class #118 fixed in `skillc demo`.

    Refuses (`demo.SubjectRefused`) a name that is empty, `.`/`..`, or carries
    a path separator, before anything is created: the name becomes part of a
    path here, ahead of the subject declaration being read (codex review)."""
    if subject_name in ("", ".", "..") or "/" in subject_name or os.sep in subject_name:
        raise demo.SubjectRefused(f"subject name {subject_name!r} is not a plain name under evals/subjects/")
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"skillc-collection-run-{subject_name}-", dir=base))


def discard_acquisition(run_root: Path, subject_name: str) -> None:
    """Remove the run's checkout and staging copies - inputs re-derivable from
    the subject's pinned revision. The store, the run's evidence, is kept."""
    for suffix in ("checkout", "staging"):
        shutil.rmtree(run_root / f"{subject_name}-{suffix}", ignore_errors=True)


@dataclass(frozen=True)
class HostCredentialState:
    """The operator's OWN credential file, read on the host before and after
    a run (issue #106's owed "the host login still working afterwards").
    Holds a digest and a remaining life - never the bytes, so no field here
    can carry a token into a record or a paste-back.

    `digest`/`remaining_seconds` are `None` when the file could not be read
    or its remaining life could not be determined; `None` is "not observed",
    never "fine"."""

    digest: str | None
    remaining_seconds: float | None


def read_host_credential(client: str, explicit_path: str | Path | None) -> HostCredentialState:
    try:
        data = credential.read_fresh(credential.resolve_path(client, explicit_path))
    except (credential.CredentialRefused, OSError):
        return HostCredentialState(digest=None, remaining_seconds=None)
    return HostCredentialState(
        digest=hashlib.sha256(data).hexdigest(),
        remaining_seconds=credential.remaining_life_seconds(client, data),
    )


@dataclass(frozen=True)
class HostCredentialCheck:
    """Before-and-after comparison of `HostCredentialState`. `unchanged` is
    `None` when either side was unreadable - a comparison that could not be
    made, never a pass."""

    before: HostCredentialState
    after: HostCredentialState

    @property
    def unchanged(self) -> bool | None:
        if self.before.digest is None or self.after.digest is None:
            return None
        return self.before.digest == self.after.digest


@dataclass(frozen=True)
class CollectionAgentResult:
    subject_name: str
    revision: str
    client: str
    record: dict[str, object]
    #: The agent container's network as actually configured, stated in the
    #: paste-back so no record implies containment it did not have. `None`
    #: when unknown (a result built outside `run_collection_agent_attempt`).
    agent_network: str | None = None
    #: Filled by the CLI around the run (issue #106); `None` = not observed.
    host_credential: HostCredentialCheck | None = None
    #: `reap.diff` of two daemon snapshots taken around the whole run -
    #: CONTEXT only: it counts any skillc-owned container that appeared,
    #: including a concurrent run's. `None` = not taken.
    daemon_diff: reap.SnapshotDiff | None = None
    #: Containers still labelled with one of THIS run's attempt ids (the
    #: agent's and every grading probe's) after the run - the cleanup verdict.
    #: `None` = could not be asked, or no attempt id was prepared.
    attributable_leftovers: list[str] | None = None
    attempts_checked: int | None = None
    #: The journal's own last `cleaned` event status for the attempt's
    #: workspace (e.g. "removed"). `lifecycle.run_through_backend` finalizes
    #: the record BEFORE it cleans the workspace, so the record's `cleanup`
    #: always reads "partial" on a lifecycle-driven attempt; the journal event
    #: is written after the removal and is the fact. `None` = no such event.
    workspace_cleaned: str | None = None
    #: Where the run's evidence store was kept, already redacted for printing.
    store_display: str | None = None
    #: Whether the full record JSON was written into the store (it is only
    #: written when it passes the same leak check as the paste-back).
    record_written: bool | None = None


@dataclass(frozen=True)
class AcquiredCollection:
    """The result of reading and acquiring a subject's declared surface -
    ACQUIRED ONCE, shared by `plan_collection_attempt` (which needs
    `source.digest`, a real content digest, never the placeholder codex
    review flagged - `materialize.acquire_snapshot`'s own `tree_digest`) and
    `run_collection_agent_attempt` (which needs `files` to build
    `extra_home_files`). Splitting acquisition out this way means calling
    both never doubles a real subject's real git clone."""

    subject: materialize.Subject
    source: materialize.Source
    files: list[demo.SubjectFile]


def acquire_collection(subject_name: str, base: Path, *, checkout: Path | None = None) -> AcquiredCollection:
    """Read `subject_name`'s declaration and acquire its declared, selected
    skill surface - no Docker work, no trial planning.

    `checkout`, when given, is an already-acquired local directory holding
    `subject.skills_root` directly - a plain directory, never a git
    repository, matching `demo.run_subject_demo`'s own test-only convention
    (this module's own tests use a committed fixture collection, needing no
    `git` binary at all). The real CLI path (owed to the operator) clones
    fresh via `demo.acquire_subject_checkout`, which forces it to the pinned
    revision first.

    Refuses (`demo.SubjectRefused`) if the subject is unknown, malformed, or
    names a selected skill absent from its surface - `materialize.inventory`'s
    own check, the same one `demo.run_subject_demo` already surfaces this
    way."""
    subject = demo.load_demo_subject(subject_name)
    repo = checkout if checkout is not None else demo.acquire_subject_checkout(subject, base / f"{subject_name}-checkout")
    staging = base / f"{subject_name}-staging"
    staging.mkdir(parents=True, exist_ok=True)
    try:
        source = materialize.acquire_snapshot(subject, repo, staging)
        entries = materialize.inventory(subject, source)
    except materialize.Refused as exc:
        raise demo.SubjectRefused(f"subject {subject_name!r} could not be prepared: {exc}") from exc
    files = demo.subject_surface_files(source, entries)
    return AcquiredCollection(subject, source, files)


def _collection_home_files(source: materialize.Source, files: list[demo.SubjectFile]) -> dict[str, bytes]:
    """`demo.install_subject`'s own per-file read, without the Docker call -
    this module delivers the same bytes through `agent_trial.run_one_attempt`'s
    `extra_home_files`, never a second surface-reading convention."""
    return {f.container_relpath: (source.surface_dir / f.directory / f.rel).read_bytes() for f in files}


def _fixture_surface(fixture_dir: Path) -> dict[str, bytes]:
    """`fixture_dir/src/**` only, keyed by its path relative to `fixture_dir`
    (e.g. `src/slugify.py`) - the `install()` surface shape
    `docker_backend.DockerBackend.install` already accepts (`{relative path:
    bytes}`, `verify.py`'s own probe-surface convention). Never
    `fixture_dir/expected.json` - see the module-level `_FIXTURE_SRC_DIRNAME`
    comment for why."""
    src_dir = fixture_dir / _FIXTURE_SRC_DIRNAME
    surface: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(src_dir, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(fixture_dir).as_posix()
            surface[rel] = path.read_bytes()
    return surface


def plan_collection_attempt(
    subject_name: str, acquired: AcquiredCollection, store: Path, *, image_digest: str | None = None,
) -> tuple[trial.Experiment, str]:
    """Plan one attempt, labeled by `subject_name`, before any Docker work or
    argv is built - split out from `run_collection_agent_attempt` so a caller
    that needs the attempt id UP FRONT (the fake docker CLI's own
    `--home`-mapping convention, `tests/test_agent_trial.py`'s `_mapped_home`)
    can learn it before constructing `base_argv`. A real launch needs no such
    thing (a real container needs no `--home` argument at all), so the real
    CLI path may call this in either order relative to building its own argv.

    `acquired` (`acquire_collection`) must be the SAME acquisition
    `run_collection_agent_attempt` is given below - never re-acquired here,
    which would risk a second real git clone and could in principle disagree
    with what the agent's own container actually receives. Its real content
    digest (`acquired.source.digest`, `materialize.acquire_snapshot`'s own
    `tree_digest`) becomes the plan's `subject.digest` - codex review of an
    earlier version of this module found both `subject.digest` and
    `image.digest` hardcoded to placeholder literals regardless of which
    collection or image actually ran, which left the planned evidence unable
    to identify its own inputs. `image_digest`, when known (the CLI resolves
    it via `demo.resolve_image_digest` before planning, mirroring
    `demo.run_demo`'s own "resolved before either backend starts" rule),
    becomes `image.digest`; `None` (an unreachable daemon, or a caller that
    has not resolved one yet) renders as the honest `"UNKNOWN"` marker
    `demo.py`'s own paste-back already uses for the same fact - never a
    fabricated hash standing in for missing knowledge."""
    spec: dict[str, object] = {
        "experiment": "collection-conformance",
        "trials": [{
            "label": subject_name, "case": {"id": "slug-small-fix", "revision": "r1"},
            "grader": {"id": "slug-small-fix", "revision": "g1"}, "subject": {"digest": acquired.source.digest},
            "client": {"name": materialize.CLIENT, "version": acquired.subject.client_version},
            "image": {"digest": image_digest or "UNKNOWN"}, "config": {}, "attempts": 1,
        }],
    }
    experiment = trial.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    return experiment, str(attempt["attempt_id"])


def run_collection_agent_attempt(
    *,
    subject_name: str,
    acquired: AcquiredCollection,
    experiment: trial.Experiment,
    attempt_id: str,
    backend: DockerBackend,
    grading_backend: DockerBackend,
    base: Path,
    base_argv: Sequence[str],
    prompt: str | None = None,
    surface: Mapping[str, object] | None = None,
    timeout: float = 30,
    credential_explicit_path: str | Path | None = None,
    minimum_credential_seconds: float = credential.MINIMUM_REMAINING_SECONDS,
) -> CollectionAgentResult:
    """Install `acquired`'s declared, selected skill files into the same
    container as one real (or, in this module's own tests, scripted-fake)
    agent attempt against `evals/level1/slug-small-fix`, in skill-free canary
    mode, on the client the subject itself declares.

    `acquired`/`experiment`/`attempt_id` are caller-supplied -
    `acquire_collection`/`plan_collection_attempt` above, exactly as
    `agent_trial.run_one_attempt` itself already requires `experiment`/
    `attempt_id` caller-supplied (never built implicitly per call, since a
    real trial matrix plans once and dispatches many attempts); `acquired`
    the SAME acquisition `plan_collection_attempt` used, never re-acquired
    here (see that function's own docstring for why).

    `base_argv` is caller-supplied, exactly as `agent_trial.run_one_attempt`
    itself requires - this module never invents the real launch argv (see
    that function's own docstring for why). `prompt` and `surface` default
    to the FIXED Level 1 task's own data - `goal.md` (#5's own "agent-facing
    request, identical for every arm") and `fixture/src/` (never the sibling
    `fixture/expected.json`, the grader's ground truth for it - see
    `_fixture_surface`'s own comment) - reading them is not inventing a
    prompt, since bullet 2 fixes this task for every collection; a caller
    that needs a different one (this module's own tests, a red case) may
    still override either."""
    resolved_prompt = prompt if prompt is not None else (demo.GRADER_ROOT / "goal.md").read_text(encoding="utf-8")
    resolved_surface = surface if surface is not None else _fixture_surface(demo.GRADER_ROOT / "fixture")
    extra_home_files = _collection_home_files(acquired.source, acquired.files)

    grader = verify.GraderDef.load(demo.GRADER_ROOT)
    record = agent_trial.run_one_attempt(
        backend=backend, experiment=experiment, attempt_id=attempt_id, client=materialize.CLIENT,
        base_argv=base_argv, prompt=resolved_prompt, skill_name=None,
        surface=resolved_surface, limits=Limits(timeout=timeout), base=base,
        credential_explicit_path=credential_explicit_path,
        minimum_credential_seconds=minimum_credential_seconds,
        cli_version=acquired.subject.client_version,
        grader=grader, grading_backend=grading_backend,
        extra_home_files=extra_home_files,
    )
    cleaned = [e for e in experiment.events(attempt_id) if e.get("event") == "cleaned"]
    return CollectionAgentResult(
        subject_name, acquired.subject.revision, materialize.CLIENT, record, agent_network=backend.network,
        workspace_cleaned=str(cleaned[-1].get("status")) if cleaned else None,
    )


def _string_leaves(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [leaf for k, v in value.items() for leaf in (*_string_leaves(k), *_string_leaves(v))]
    if isinstance(value, (list, tuple)):
        return [leaf for item in value for leaf in _string_leaves(item)]
    return []


def evidence_leak_findings(evidence: object, serialized: str) -> list[str]:
    """Leak-check an evidence object BOTH as its string leaves and as the
    serialized text (codex review): `json.dumps` escapes the quotes inside a
    string value, so an OAuth-shaped `{"access_token": "..."}` embedded in, say,
    a grader's detail text stops matching the token pattern once serialized.
    Scanning the leaves catches that; scanning the text catches anything a
    leaf split would hide."""
    findings = [f for leaf in _string_leaves(evidence) for f in demo.leak_check_text(leaf)]
    return findings + demo.leak_check_text(serialized)


def evidence_envelope(result: CollectionAgentResult) -> dict[str, object]:
    """Everything the paste-back states, in one saved document - the driver's
    record AND the observations the CLI made around it (codex review: saving
    only the record left a cleanup exit 1 or a host comparison unexplained
    once the terminal output was gone). The host credential appears as its
    comparison and remaining life only - never its digest or bytes."""
    host = result.host_credential
    diff = result.daemon_diff
    return {
        "subject": result.subject_name, "revision": result.revision, "client": result.client,
        "agent_network": result.agent_network,
        "record": result.record,
        "workspace_cleaned_journal": result.workspace_cleaned,
        "host_credential": None if host is None else {
            "unchanged": host.unchanged,
            "remaining_seconds_before": host.before.remaining_seconds,
            "remaining_seconds_after": host.after.remaining_seconds,
        },
        "attributable_leftovers": result.attributable_leftovers,
        "attempts_checked": result.attempts_checked,
        "daemon_context": None if diff is None else {
            "comparable": diff.comparable, "leaked": sorted(diff.leaked),
            "foreign_vanished": sorted(diff.foreign_vanished),
        },
    }


def _fmt_seconds(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "None"
    return f"{int(value) // 60}m"


def build_collection_paste_back(result: CollectionAgentResult) -> str:
    """The planned shape (`docs/specs/evaluation-facility/operator-demo.md`),
    grouped by the five kinds of evidence issue #106's live run retains:
    prompt delivery, the liveness canary, the credential, the outcome, and
    cleanup - plus the real transcript's own format census. Leak-checked by
    the caller before printing, via `demo.leak_check_text`/
    `demo.print_paste_back` directly, never a second scan convention.

    Every value is read from the record under the key the record actually
    uses. #11's version read `refresh_observed_in_container` from the
    observation, whose real key is `credential_refresh_observed_in_container`
    (`credential.CredentialUsage.to_record_fields`), so the live paste-back
    always printed `None` - a missing key reads exactly like "not observed"."""
    record = result.record
    observation = record.get("observation")
    obs = observation if isinstance(observation, dict) else {}
    graded = record.get("graded")
    graded_d = graded if isinstance(graded, dict) else {}
    stop = record.get("stop")
    stop_d = stop if isinstance(stop, dict) else {}
    criteria = graded_d.get("criteria")
    criteria_text = (
        ", ".join(f"{c.get('id')}={c.get('outcome')}" for c in criteria if isinstance(c, dict))
        if isinstance(criteria, list) else None
    )
    cleanup = record.get("cleanup")
    cleanup_d = cleanup if isinstance(cleanup, dict) else {}
    host = result.host_credential
    diff = result.daemon_diff
    lines = [
        "",
        f"collection agent run: {result.subject_name} revision={result.revision} client={result.client}",
        f"  agent_network={result.agent_network}",
        f"  attempt_id={record.get('attempt_id')}",
        "  [prompt delivery]",
        f"    prompt_delivered={obs.get('prompt_delivered')}",
        f"    prompt_delivery_reason={obs.get('prompt_delivery_reason')}",
        f"    transcript_files_found={obs.get('transcript_files_found')}",
        "  [canary]",
        f"    canary_satisfied={obs.get('canary_satisfied')}",
        f"    canary_reason={obs.get('canary_reason')}",
        f"    liveness_method={record.get('liveness_method')}",
        "  [credential]",
        f"    credential_delivered={obs.get('credential_delivered')} source={obs.get('credential_source')}",
        f"    remaining_at_launch={_fmt_seconds(obs.get('credential_remaining_seconds_at_launch'))}",
        f"    refresh_observed_in_container={obs.get('credential_refresh_observed_in_container')}",
        f"    host_credential_unchanged={host.unchanged if host else None}",
        f"    host_remaining_after={_fmt_seconds(host.after.remaining_seconds) if host else 'None'}",
        "  [outcome]",
        f"    disposition={record.get('disposition')} reason={record.get('reason')}",
        (
            f"    stop.reason={stop_d.get('reason')} stop.exit_code={stop_d.get('exit_code')} "
            f"stop.confirmed={stop_d.get('confirmed')}"
        ),
        f"    skill_invocations={obs.get('skill_invocations')} (detection={obs.get('skill_invocation_detection')})",
        f"    graded.status={graded_d.get('status') if graded_d else None}",
        f"    graded.criteria={criteria_text}",
        f"    grading_blocked_reason={record.get('grading_blocked_reason')}",
        "  [cleanup]",
        f"    workspace_cleaned(journal)={result.workspace_cleaned}",
        f"    workspace_cleanup(record, at finalize)={cleanup_d.get('status')}",
        f"    backend_teardown={record.get('backend_teardown')}",
        f"    backend_teardown_error={record.get('backend_teardown_error')}",
        (
            f"    attributable_leftover_containers="
            f"{len(result.attributable_leftovers) if result.attributable_leftovers is not None else None} "
            f"(attempts_checked={result.attempts_checked})"
        ),
        (
            f"    context: daemon_comparable={diff.comparable if diff else None} "
            f"leaked_owned_containers={len(diff.leaked) if diff and diff.comparable else None} "
            f"foreign_vanished={len(diff.foreign_vanished) if diff and diff.comparable else None}"
        ),
        f"    store_kept={result.store_display} record_written={result.record_written}",
        "  [transcript format]",
        f"    client_version={obs.get('transcript_client_version')} model={obs.get('transcript_model')}",
        (
            f"    unrecognized_types={obs.get('transcript_unrecognized_types')} "
            f"(response_items_inspected={obs.get('transcript_response_items_inspected')})"
        ),
        f"    line_types={obs.get('transcript_line_types')}",
    ]
    return "\n".join(lines)
