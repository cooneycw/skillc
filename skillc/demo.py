"""The operator demo command (#81, sub-issue of #10): the ONE command an
operator runs, on their OWN machine, to see a real Docker trial lifecycle
happen end to end, and the paste-back block they send back.

#10 CLOSES ONLY ON THE OPERATOR'S OWN LIVE RUN of this command against a real
Docker daemon - never on this module's own tests passing, never on CI going
green. Every test in this codebase for this module runs against the fake
`docker` CLI (`tests/fixtures/docker-backend/fake_docker.py`); the real
daemon boundary is owed to that live run, exactly as `docker_backend.py`
itself states throughout.

TWO INDEPENDENT DOCKER-BACKED DEMONSTRATIONS, folded into one command, never
a real paid-model agent (no API key, no network call to a model provider is
made by this module, at any point):

1. THE LIFECYCLE DEMO (`run_lifecycle_demo`): drives one attempt through
   `lifecycle.run_through_backend` with a real `DockerBackend` and a trivial
   SCRIPTED subject (a `python3 -c ...` one-liner, never an agent CLI) - this
   proves prepare/install/execute/confirm_stopped/export/destroy/
   confirm_absent all work against a real daemon, using `lifecycle.py`'s own
   already-working liveness canary (a planted file's CONTENT, read back after
   `export()` - never a transcript).
2. THE GRADING DEMO (`run_grading_demo`): grades a candidate through
   `verify.grade_files(..., backend=...)` (#76, interfaces.md step 8's
   "separate backend instance, same seam") - a SECOND, independent
   `DockerBackend` instance runs the probe. Uses the already-certified
   `evals/level1/slug-small-fix` task: the `reference/` candidate for the
   success path, a `wrong/` candidate for `--control`'s known-bad run.

WHY NOT A REAL AGENT (the canary-adapter gap, raised on issue #81):
`trial_bootstrap.check_canary` requires a `tool_use` event's CONFIRMED
`output` to literally carry the nonce marker - but a real Claude Code `Write`
result typically confirms only that a file was written, never echoing its
content. That check is therefore always red against an unmodified real
transcript, unless a per-client adapter re-reads the actual written file back
from the exported output to synthesize `output`. Per-client transcript
adapters now exist (issue #106's first split PR); wiring a REAL agent through
`trial_bootstrap.py`'s own bootstrap, with that adapter, is #106's own job -
`skillc/agent_trial.py`, not this module, which keeps using
`lifecycle.py`'s own file-content mechanism instead, since that has no such gap
for a SCRIPTED subject.

THE PASTE-BACK BLOCK IS LEAK-CHECKED BEFORE IT EXISTS TO BE PRINTED
(`leak_check_text`, reusing `skillc.leak.scan_text` directly - no file
round-trip needed). A block that fails the scan is refused: nothing is
printed, and the command exits non-zero. This is the operator's own
guarantee that nothing needs manual redaction, not a formatting nicety.

Stdlib only for orchestration (AGENTS.md); every Docker-facing call goes
through `docker_backend.py`'s own helpers, never a second subprocess
convention.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from . import docker_backend as dbe
from . import leak, lifecycle, materialize, provenance, reap, trial, verify
from .backend import Confirmation, Limits

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The host paths this demo declares and proves untouched by its own trial -
#: relative to the skillc checkout root, present in any checkout (never the
#: operator's own unrelated files, which this command has no way to name
#: generically). A real operator concerned about a WIDER blast radius extends
#: this list themselves; what matters here is that the mechanism
#: (`reap.snapshot_host_paths`/`diff_host_paths`) is proven to work, not that
#: this particular list is exhaustive.
HOST_PATHS_TO_WATCH: tuple[str, ...] = ("pyproject.toml", "README.md")

#: The already-certified Level 1 task this demo grades through the backend
#: seam (#76) - never a task invented for this module alone. `reference/` is
#: the known-good candidate; `wrong/no-lowercase/` is `--control`'s
#: known-bad one (chosen arbitrarily among the task's own committed `wrong/`
#: variants - any of them would do, per `qualify.py`'s own discrimination
#: proof).
GRADER_ROOT = REPO_ROOT / "evals" / "level1" / "slug-small-fix"
GOOD_CANDIDATE = GRADER_ROOT / "reference"
BAD_CANDIDATE = GRADER_ROOT / "wrong" / "no-lowercase"

DEFAULT_IMAGE = "skillc-trial:latest"


def _read_default_subject() -> str:
    """The `--subject` name used when the flag is given no value, read from
    `evals/subjects/DEFAULT_SUBJECT` (one line, the name only) rather than a
    literal in this file. A hardcoded name here would itself be a
    subject-name branch: `tests/test_materialize.py`'s genericity guard
    (issue #11's "no subject-name branch anywhere in skillc/") AST-scans
    every `skillc/*.py` module for exactly this shape. The returned value is
    still a NAME ONLY, used exclusively to build a path; nothing here
    branches on it."""
    path = REPO_ROOT / "evals" / "subjects" / "DEFAULT_SUBJECT"
    return path.read_text(encoding="utf-8").strip()


#: See `_read_default_subject` - resolved once at import time from data, not
#: a literal, so this module names no subject.
DEFAULT_SUBJECT = _read_default_subject()


class SubjectRefused(Exception):
    """The selected subject's declaration, its acquisition, or its selection
    could not proceed - a clear message and a nonzero exit, before anything
    is installed."""


def load_demo_subject(name: str) -> materialize.Subject:
    """`evals/subjects/<name>/subject.json`, loaded through
    `materialize.Subject`'s own generic schema - `name` builds a path and
    nothing else. Refuses BEFORE any acquisition or installation is
    attempted if the declaration is missing, unsupported, or malformed."""
    path = REPO_ROOT / "evals" / "subjects" / name / "subject.json"
    if not path.is_file():
        raise SubjectRefused(f"no subject declaration at evals/subjects/{name}/subject.json")
    try:
        return materialize.Subject.load(path)
    except materialize.Refused as exc:
        raise SubjectRefused(f"subject {name!r} is not usable: {exc}") from exc


def acquire_subject_checkout(subject: materialize.Subject, into: Path, timeout: float = 300) -> Path:
    """A fresh clone of the subject's own declared `locator`, forced to its
    pinned `revision` via `git checkout` - this is #101's own extra network
    dependency beyond skillc's bare clone, for whichever subject `--subject`
    selects, stated here plainly, not hidden: installing a second collection
    needs its own source.

    `run_subject_demo` hands the result to `materialize.acquire_snapshot`,
    never `acquire_git` - deliberately, the same call this module made for a
    since-removed, narrower `--subject` under issue #81: `acquire_git` shells
    out to `git` itself (`git archive` on the pinned commit) to build its
    `Source`, which is redundant work once this function has ALREADY forced
    the checkout to that exact commit, and it is what made this module's own
    tests require a real `git` binary in CI's gate image, where none is
    installed - the checked-out directory needs no further git verification
    to be trusted.
    Known, accepted tradeoff: `materialize.acquire_snapshot`'s own `Source`
    reports `revision="snapshot:<digest>"`, never the real commit SHA, so
    `run_subject_demo` reports the paste-back's `revision` from `subject.revision`
    (the DECLARED pin) directly, never from the acquired `Source` - the
    operator-meaningful claim either way is "the pin this subject declares",
    which acquisition mechanics should not be able to change the wording of."""
    url = f"https://{subject.locator}"
    try:
        subprocess.run(
            ["git", "clone", "--quiet", url, str(into)], check=True, timeout=timeout, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(into), "checkout", "--quiet", subject.revision],
            check=True, timeout=60, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SubjectRefused(f"could not acquire {subject.locator!r} at {subject.revision!r}: {exc}") from exc
    return into


# --------------------------------------------------------------- image digest


def resolve_image_digest(
    docker_bin: Sequence[str], image: str, env: dict[str, str] | None, timeout: float = dbe.DAEMON_TIMEOUT,
) -> str | None:
    """The digest of the image that would ACTUALLY run - `docker image
    inspect <image> --format {{.Id}}` - never a claim from `image`'s own
    string alone, which could be a floating tag. `None` when the daemon
    cannot be asked or the image is unknown to it - never a guessed digest."""
    try:
        proc = subprocess.run(
            [*docker_bin, "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True, text=True, timeout=timeout, env=env, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


# ------------------------------------------------------------- lifecycle demo


#: A trivial SCRIPTED subject - never an agent CLI. Touches the liveness
#: canary lifecycle.py plants via `install()`'s injected nonce, exactly as
#: `tests/fixtures/backend-lifecycle/fake_client.py`'s own `work` mode does,
#: proving the full attempt lifecycle against a REAL daemon without any
#: model call at all.
_LIFECYCLE_SUBJECT = (
    "import pathlib;"
    "p = pathlib.Path('.skillc-canary');"
    "n = p.read_text(encoding='utf-8') if p.exists() else '';"
    "pathlib.Path('.skillc-canary-result').write_text(f'touched:{n}', encoding='utf-8');"
    "pathlib.Path('out.txt').write_text('demo subject ran', encoding='utf-8')"
)


def run_lifecycle_demo(
    backend: dbe.DockerBackend, base: Path, *, recorded_attempt_ids: list[str] | None = None,
) -> dict[str, object]:
    """One attempt, through the REAL driver (`lifecycle.run_through_backend`),
    against `backend`. Returns the same lifecycle record shape that driver
    always returns - `record["disposition"]` is `"captured"` on a genuine
    success, through a real daemon, with liveness proven by the canary file's
    content (never a claim from an exit code alone).

    `recorded_attempt_ids`, when given, gets this attempt's id appended BEFORE
    the backend ever touches it - so a caller holding that same list already
    knows this id if a `KeyboardInterrupt` lands anywhere in
    `lifecycle.run_through_backend` below (issue #118 review: a Ctrl-C sweep
    scoped to attempt ids, never a host-global one, needs the id recorded
    before the risk starts, not after it returns)."""
    store = trial.open_store(base / "store", forbidden=[])
    spec: dict[str, object] = {
        "experiment": "demo",
        "trials": [{
            "label": "lifecycle-demo", "case": {"id": "demo", "revision": "r1"},
            "grader": {"id": "demo", "revision": "g1"}, "subject": {"digest": "sha256:00"},
            "client": {"name": "scripted", "version": "1"}, "image": {"digest": "sha256:01"},
            "config": {}, "attempts": 1,
        }],
    }
    experiment = trial.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    attempt_id = str(attempt["attempt_id"])
    if recorded_attempt_ids is not None:
        recorded_attempt_ids.append(attempt_id)
    argv = [verify.PROBE_INTERPRETER, "-c", _LIFECYCLE_SUBJECT]
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, argv, {"demo": "x"}, Limits(timeout=30), base,
    )
    return {**record, "attempt_id": attempt_id}


# --------------------------------------------------------------- grading demo


def _candidate_files(candidate_dir: Path) -> list[tuple[str, bytes, bool]]:
    """The same walk `verify.grade_directory` does internally - extracted
    because that function does not accept a `backend=` argument, and this
    demo needs to pass one (#76's own backend-seam integration)."""
    files: list[tuple[str, bytes, bool]] = []
    for dirpath, dirnames, filenames in os.walk(candidate_dir, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            path = Path(dirpath) / name
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                rel = path.relative_to(candidate_dir).as_posix()
                files.append((rel, path.read_bytes(), bool(info.st_mode & stat.S_IXUSR)))
    return files


def run_grading_demo(
    backend: dbe.DockerBackend, candidate_dir: Path, base: Path, *, recorded_attempt_ids: list[str] | None = None,
) -> verify.Graded:
    """Grade `candidate_dir` against the certified `slug-small-fix` task
    through `backend` - a fresh instance, never the lifecycle demo's own (the
    same "separate backend instance, same seam" interfaces.md step 8
    requires). `recorded_attempt_ids` gets the probe's attempt id before its
    container exists (issue #122), so the caller's sweep covers it."""
    grader = verify.GraderDef.load(GRADER_ROOT)
    files = _candidate_files(candidate_dir)
    return verify.grade_files(grader, files, base, backend=backend, recorded_attempt_ids=recorded_attempt_ids)


# --------------------------------------------------------------- subject demo


#: `CODEX_HOME` for the codex listing, relative to `CONTAINER_HOME` -
#: `materialize.Arm.codex_home`'s own convention (`<home>/.codex`), aimed at
#: a real container's home instead of a host arm directory.
_SUBJECT_CODEX_HOME_RELPATH = ".codex"
#: Where a subject's files land when no surface is named - the codex surface's
#: own skills directory, the only one that existed before issue #124.
_DEFAULT_SKILLS_RELPATH = materialize.SURFACES[materialize.SURFACE].home_skills_relpath


@dataclass(frozen=True)
class SubjectFile:
    directory: str  # the skill's own directory name under the subject's skills_root
    rel: str  # relative to that directory, e.g. "SKILL.md"
    skill: str  # the skill's declared `name`, from its own frontmatter
    digest: str
    #: The declared surface's own skills directory, relative to the home
    #: (issue #124): `.codex/skills` or `.claude/skills` - read from
    #: `materialize.SURFACES`, never from the subject's name.
    skills_relpath: str = _DEFAULT_SKILLS_RELPATH

    @property
    def container_relpath(self) -> str:
        return f"{self.skills_relpath}/{self.directory}/{self.rel}"


def subject_surface_files(
    source: materialize.Source, entries: list[materialize.SkillEntry],
    skills_relpath: str = _DEFAULT_SKILLS_RELPATH,
) -> list[SubjectFile]:
    """Every file across every selected skill, as a flat list ready to
    deliver into a container's home under `skills_relpath` (the subject's
    declared surface's own `home_skills_relpath`) - `entries` is
    `inventory()`'s own output, so a `--subject` whose `select` names a skill
    absent from the surface never reaches here at all: `inventory()` raises
    `materialize.Refused` first (translated to `SubjectRefused` by the
    caller), before any Docker work starts."""
    return [
        SubjectFile(entry.directory, str(f["path"]), entry.name, str(f["digest"]), skills_relpath)
        for entry in entries for f in entry.files
    ]


def install_subject(
    backend: dbe.DockerBackend, handle: object, source: materialize.Source, files: list[SubjectFile],
) -> dict[str, object]:
    """Delivers every selected file into the container's home, one
    `deliver_home_file` call per file - the same candidate-owned tar-stream
    mechanism `install()` uses for `CONTAINER_WORKSPACE`, aimed at
    `CONTAINER_HOME` instead (#98's own precedent). Nothing is bind-mounted.
    Returns the installation receipt this leg's paste-back and digest
    re-check both read from."""
    for f in files:
        data = (source.surface_dir / f.directory / f.rel).read_bytes()
        backend.deliver_home_file(handle, f.container_relpath, data)
    return {
        "skills": sorted({f.skill for f in files}),
        "skill_count": len({f.skill for f in files}),
        "file_count": len(files),
        "files": [{"path": f.container_relpath, "digest": f.digest} for f in files],
    }


def recheck_subject_digests(
    backend: dbe.DockerBackend, handle: object, files: list[SubjectFile],
) -> tuple[str, list[str]]:
    """Re-reads every installed file's CURRENT bytes back out of the
    container (`read_home_file`) and re-hashes them - "landed intact" is
    observed here, never assumed from the install call alone. Returns
    `("matched", [])` or `("mismatched", [<container_relpath>, ...])`."""
    mismatched: list[str] = []
    for f in files:
        try:
            data = backend.read_home_file(handle, f.container_relpath)
        except dbe.BackendUnavailable as exc:
            mismatched.append(f"{f.container_relpath}: unreadable ({exc})")
            continue
        if materialize.sha256_bytes(data) != f.digest:
            mismatched.append(f.container_relpath)
    return ("mismatched" if mismatched else "matched"), mismatched


def run_subject_discovery(
    backend: dbe.DockerBackend, handle: object, client_argv: list[str], selected: set[str],
    limits: Limits, export_root: Path,
) -> tuple[dict[str, str], frozenset[str], str | None]:
    """Runs the client's own listing (`codex debug prompt-input`, the same
    argv convention `skillc.exposure`'s `render_codex` already uses) INSIDE
    the container via `execute()`, with no model call - never
    `materialize.run_client`'s host-local subprocess, which never touches
    the container at all. `CODEX_HOME` is set for just this one exec via
    `env` (coreutils, already in the trial image), pointed at the home
    directory `install_subject` populated - the container's own ambient
    `HOME` alone is not enough, since the real client reads `CODEX_HOME`
    explicitly when set (`materialize.run_client` does the same for its own
    host-local runs).

    Returns `{skill_name: "discovered"|"not-discovered"}` for every name in
    `selected`, plus every OTHER name the listing named (`unexpected` -
    #150-D: a name outside `selected` is exactly what a contaminated
    baseline looks like, an image-shipped or leftover skill that could make
    a degraded arm pass installation-readiness for the wrong reason), or
    every one of `selected` mapped to `"UNMEASURED"` with a reason string
    and an empty `unexpected` when the listing could not run at all (a
    launch failure, a nonzero exit, no `observations` file, or output the
    shared parser cannot read) - never dropped, never a silent partial
    result. A non-empty `unexpected` is only meaningful when the reason is
    `None`; an unmeasured listing cannot say whether anything else is
    listed either.

    A listed entry rooted under `materialize.CLIENT_SYSTEM_DIR` is never
    `unexpected`, mirroring `materialize.derive_readiness`'s own native
    "foreign" check: the client seeds that skill into every home it is
    pointed at, so it is not contamination, it is the client existing."""

    def unmeasured(reason: str) -> tuple[dict[str, str], frozenset[str], str | None]:
        return {name: "UNMEASURED" for name in selected}, frozenset(), reason

    codex_home = f"{dbe.CONTAINER_HOME}/{_SUBJECT_CODEX_HOME_RELPATH}"
    argv = ["env", f"CODEX_HOME={codex_home}", *client_argv, *materialize.CANARY_ARGV, materialize.CANARY_PROMPT]
    result = backend.execute(handle, argv, limits)
    backend.confirm_stopped(handle)
    if result.reason != "exited" or result.exit_code != 0:
        return unmeasured(
            f"listing did not complete cleanly: reason={result.reason} exit_code={result.exit_code} error={result.error}"
        )
    export_dir = export_root / "subject-discovery-export"
    try:
        backend.export(handle, export_dir)
    except OSError as exc:
        return unmeasured(f"could not export the container's workspace: {exc}")
    observations = export_dir / "observations"
    if not observations.is_file():
        return unmeasured("no observations file was exported")
    stdout_text = observations.read_text(encoding="utf-8", errors="replace")
    listing = materialize.parse_listing(stdout_text, export_dir)
    if listing.status != "ok":
        return unmeasured(f"listing {listing.status}: {listing.detail}")
    listed = {name for name, _ in listing.entries}
    per_selected = {name: ("discovered" if name in listed else "not-discovered") for name in selected}
    system_named = {
        name for name, path in listing.entries
        if materialize.CLIENT_SYSTEM_DIR in Path(path).parts
    }
    unexpected = frozenset(listed - selected - system_named)
    return per_selected, unexpected, None


@dataclass(frozen=True)
class SubjectResult:
    subject_name: str
    revision: str
    receipt: dict[str, object]
    digest_status: str
    digest_mismatches: list[str]
    discovery: dict[str, str]
    discovery_reason: str | None
    host_diff: reap.HostPathDiff
    reap_report: reap.ReapReport
    #: Set (issue #118) when acquisition or `prepare()` failed before any
    #: install/digest/discovery work could even start - every acceptance
    #: item for this leg reports NOT EXERCISED with this text as evidence,
    #: never a guessed MET/NOT MET for work that never ran. `None` is the
    #: ordinary case: the leg ran, whatever its own items concluded.
    not_exercised_reason: str | None = None
    #: False when the subject's client has no model-free listing (issue
    #: #124: Claude Code) - discovery was never attempted here, so its item
    #: reports NOT EXERCISED with `discovery_reason`, never a borrowed result.
    discovery_exercised: bool = True


def _not_exercised_subject_result(subject_name: str, revision: str, reason: str) -> SubjectResult:
    """Every field a placeholder honestly labeled as such - never a value
    that could be mistaken for a real observation. `_subject_acceptance_items`
    checks `not_exercised_reason` FIRST and never reads any of these."""
    return SubjectResult(
        subject_name=subject_name, revision=revision, receipt={"skills": [], "skill_count": 0, "file_count": 0, "files": []},
        digest_status="not-exercised", digest_mismatches=[], discovery={}, discovery_reason=None,
        host_diff=reap.HostPathDiff(changed=(), unresolved=()),
        reap_report=reap.ReapReport(daemon_reachable=False, outcomes=()),
        not_exercised_reason=reason,
    )


def run_subject_demo(
    *, subject_name: str, image: str, docker_bin: Sequence[str], base: Path, timeout: float = 30,
    checkout: Path | None = None, client_argv: list[str] | None = None,
    recorded_attempt_ids: list[str] | None = None,
) -> SubjectResult:
    """The `--subject` leg: install the declared collection into a REAL
    container's home, re-read its digests back from the container, and
    observe the client's own discovery of it - a THIRD demonstration,
    alongside (never replacing) the lifecycle and grading demos, so #81's
    demo and #11's second-collection evidence share one command and one
    runbook. `checkout`, when given, is an already-acquired local directory
    holding `subject.skills_root` directly - a plain directory, never a git
    repository (this module's own tests pass a committed fixture collection
    here, needing no `git` binary at all); the real CLI path clones fresh via
    `acquire_subject_checkout`, which forces it to the pinned revision before
    this function ever sees it.

    Acquired via `materialize.acquire_snapshot`, never `acquire_git` - see
    `acquire_subject_checkout`'s own docstring for why, and why this reports
    `subject.revision` in the result rather than the acquired `Source`'s own.

    Refuses BEFORE any Docker work starts if the subject is unknown,
    malformed, or names a selected skill absent from its surface
    (`inventory()`'s own check, issue #101's "Install" acceptance item).

    ACQUISITION AND BACKEND FAILURES NEVER RAISE (issue #118): a real clone
    failing, or `prepare()` finding no daemon/image, is reported as a
    NOT-EXERCISED `SubjectResult` through the normal, leak-checked paste-back
    path - not a raised exception, and never a raw traceback (an earlier
    version let `BackendUnavailable` from `prepare()` propagate uncaught,
    and the traceback printed the operator's own home directory and
    username). Only the STATIC checks above (an unknown subject name, a
    `select` naming a skill absent from the surface) still raise
    `SubjectRefused` synchronously - those are caller/config errors the
    operator needs to see and fix, not a runtime hazard to report
    gracefully, and existing callers depend on that distinction.

    Every temporary directory THIS function creates is a fresh
    `tempfile.mkdtemp`, removed in `finally` - never a fixed path under
    `base` (issue #118): a fixed scratch path collides between concurrent
    runs, between operators, and with itself after a crash left a previous
    run's directory behind. A caller-supplied `checkout` is never touched -
    it is not this function's to delete."""
    subject = load_demo_subject(subject_name)

    owned_checkout: Path | None = None
    staging = Path(tempfile.mkdtemp(prefix="skillc-subject-staging-"))
    try:
        if checkout is not None:
            repo = checkout
        else:
            owned_checkout = Path(tempfile.mkdtemp(prefix="skillc-subject-checkout-"))
            try:
                acquire_subject_checkout(subject, owned_checkout)
            except SubjectRefused as exc:
                reason = redact_known_host_paths(f"acquisition failed: {exc}", base=base)
                return _not_exercised_subject_result(subject_name, subject.revision, reason)
            repo = owned_checkout

        try:
            source = materialize.acquire_snapshot(subject, repo, staging)
            entries = materialize.inventory(subject, source)
        except materialize.Refused as exc:
            raise SubjectRefused(f"subject {subject_name!r} could not be prepared: {exc}") from exc
        files = subject_surface_files(source, entries, subject.surface_spec.home_skills_relpath)
        selected = {e.name for e in entries}

        env = None  # inherit the operator's own ambient environment, like a plain `docker` invocation
        host_paths = [REPO_ROOT / p for p in HOST_PATHS_TO_WATCH]
        host_before = reap.snapshot_host_paths(host_paths)

        backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)
        # A nonce, not just the subject name: two concurrent demo runs (or a
        # single run's own lifecycle/grading attempt ids, which already carry
        # their own uniqueness) must never collide on one container name.
        attempt_id = f"subject-{subject_name}-{secrets.token_hex(4)}"
        if recorded_attempt_ids is not None:
            recorded_attempt_ids.append(attempt_id)
        try:
            handle = backend.prepare(attempt_id)
        except dbe.BackendUnavailable as exc:
            reason = redact_known_host_paths(f"backend unavailable: {exc}", base=base)
            return _not_exercised_subject_result(subject_name, subject.revision, reason)
        try:
            receipt = install_subject(backend, handle, source, files)
            digest_status, mismatches = recheck_subject_digests(backend, handle, files)
            if subject.surface_spec.model_free_listing:
                # `unexpected` (#150-D) is not yet surfaced by this command's
                # own report - SubjectResult predates it - so it is read and
                # discarded here rather than silently dropped by an unpacking
                # mismatch. skillc/agent_trial.py's own caller of this
                # function is the first consumer.
                discovery, _unexpected, discovery_reason = run_subject_discovery(
                    backend, handle, client_argv if client_argv is not None else [subject.client],
                    selected, Limits(timeout=timeout), base,
                )
            else:
                discovery = {name: "UNMEASURED" for name in selected}
                discovery_reason = (
                    f"{subject.client} has no model-free listing; discovery for surface "
                    f"{subject.surface!r} is observed from a real agent transcript by "
                    f"`skillc collection-run`, never borrowed from another client"
                )
        finally:
            backend.destroy(handle)
            backend.confirm_absent(handle)

        reap_report = reap.reap(docker_bin, [attempt_id], env, timeout)
        host_after = reap.snapshot_host_paths(host_paths)
        host_diff = reap.diff_host_paths(host_before, host_after)
        return SubjectResult(
            subject_name, subject.revision, receipt, digest_status, mismatches, discovery, discovery_reason,
            host_diff, reap_report, discovery_exercised=subject.surface_spec.model_free_listing,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if owned_checkout is not None:
            shutil.rmtree(owned_checkout, ignore_errors=True)


def _subject_acceptance_items(result: SubjectResult) -> list[AcceptanceItem]:
    if result.not_exercised_reason is not None:
        names = (
            f"subject {result.subject_name!r}: installed skills match its declared selection",
            f"subject {result.subject_name!r}: in-container digests match the installation receipt",
            f"subject {result.subject_name!r}: every selected skill is discovered by the client",
            f"subject {result.subject_name!r}: declared host paths unchanged",
            f"subject {result.subject_name!r}: cleanup sweep confirms no owned container left running",
        )
        return [AcceptanceItem(name, False, result.not_exercised_reason, exercised=False) for name in names]

    receipt_skills = result.receipt["skills"]
    assert isinstance(receipt_skills, list)
    install_ok = set(receipt_skills) == set(result.discovery)
    digest_ok = result.digest_status == "matched"
    discovery_ok = result.discovery_reason is None and all(v == "discovered" for v in result.discovery.values())
    host_ok = not result.host_diff.changed and not result.host_diff.unresolved
    reap_ok = result.reap_report.daemon_reachable and not result.reap_report.left_running and not result.reap_report.unknown
    return [
        AcceptanceItem(
            f"subject {result.subject_name!r}: installed skills match its declared selection", install_ok,
            f"receipt skills={result.receipt['skills']}",
        ),
        AcceptanceItem(
            f"subject {result.subject_name!r}: in-container digests match the installation receipt", digest_ok,
            f"digest_status={result.digest_status}, mismatched={result.digest_mismatches}",
        ),
        AcceptanceItem(
            f"subject {result.subject_name!r}: every selected skill is discovered by the client", discovery_ok,
            (f"discovery={result.discovery}" if result.discovery_reason is None
             else f"UNMEASURED: {result.discovery_reason}"),
            exercised=result.discovery_exercised,
        ),
        AcceptanceItem(
            f"subject {result.subject_name!r}: declared host paths unchanged", host_ok,
            f"changed={list(result.host_diff.changed)}, unresolved={list(result.host_diff.unresolved)}",
        ),
        AcceptanceItem(
            f"subject {result.subject_name!r}: cleanup sweep confirms no owned container left running", reap_ok,
            f"reap outcomes={[o.outcome for o in result.reap_report.outcomes]}",
        ),
    ]


def build_subject_paste_back(result: SubjectResult) -> str:
    if result.not_exercised_reason is not None:
        return (
            f"\nsubject: {result.subject_name} revision={result.revision}\n"
            f"  NOT EXERCISED: {result.not_exercised_reason}"
        )
    lines = [
        "",
        f"subject: {result.subject_name} revision={result.revision}",
        f"  installed: {result.receipt['skill_count']} skill(s), {result.receipt['file_count']} file(s)",
        f"  digest_check: {result.digest_status}"
        + (f" mismatched={result.digest_mismatches}" if result.digest_mismatches else ""),
        f"  discovery: {result.discovery}"
        + (f" (UNMEASURED: {result.discovery_reason})" if result.discovery_reason else ""),
        f"  host paths unchanged: changed={list(result.host_diff.changed)}, unresolved={list(result.host_diff.unresolved)}",
        "  cleanup (reap outcomes):",
    ]
    for outcome in result.reap_report.outcomes:
        lines.append(f"    {outcome.attempt_id}: {outcome.outcome}")
    lines.append(f"    daemon_reachable={result.reap_report.daemon_reachable}")
    return "\n".join(lines)


# ------------------------------------------------------------ acceptance items


@dataclass(frozen=True)
class AcceptanceItem:
    name: str
    met: bool
    evidence: str
    #: False when the check this item names never ran at all (issue #118:
    #: "vacuous MET" - when `prepare()` never succeeded, "cleanup sweep
    #: confirms no owned container left running" and "declared host paths
    #: unchanged" both read technically true, since NOTHING happened, which
    #: is a different claim from "this demo actually proved it" and must
    #: never render the same way. `met` stays `False` for an unexercised
    #: item regardless of this flag, so `ok = all(item.met for item in items)`
    #: needs no separate check - a demo where nothing ran is never `ok`.
    exercised: bool = True


def _acceptance_items(
    lifecycle_record: dict[str, object], graded: verify.Graded,
    reap_report: reap.ReapReport, host_diff: reap.HostPathDiff, image_digest: str | None,
) -> list[AcceptanceItem]:
    lifecycle_ok = lifecycle_record.get("disposition") == "captured"
    grading_ok = graded.status == "PASS"
    reap_ok = reap_report.daemon_reachable and not reap_report.left_running and not reap_report.unknown
    host_ok = not host_diff.changed and not host_diff.unresolved
    digest_ok = image_digest is not None
    # Issue #118's own "vacuous MET": when the lifecycle leg's own prepare()
    # never succeeded ("unavailable" - lifecycle.run_through_backend's own
    # disposition for exactly that case), nothing ever started, so "no
    # owned container left running" and "host paths unchanged" are true only
    # because there was nothing to change - a real claim about a demo that
    # ran, not this one. Never silently MET.
    prepare_never_succeeded = lifecycle_record.get("disposition") == "unavailable"
    return [
        AcceptanceItem("full Docker trial lifecycle (prepare..confirm_absent)", lifecycle_ok,
                        f"lifecycle disposition={lifecycle_record.get('disposition')}"),
        AcceptanceItem("grades through the verifier's backend seam (#76)", grading_ok,
                        f"grading status={graded.status}, detail={graded.detail}"),
        AcceptanceItem(
            "cleanup sweep confirms no owned container left running",
            reap_ok and not prepare_never_succeeded,
            f"reap outcomes={[o.outcome for o in reap_report.outcomes]}",
            exercised=not prepare_never_succeeded,
        ),
        AcceptanceItem(
            "declared host paths unchanged",
            host_ok and not prepare_never_succeeded,
            f"changed={list(host_diff.changed)}, unresolved={list(host_diff.unresolved)}",
            exercised=not prepare_never_succeeded,
        ),
        AcceptanceItem("image digest recorded", digest_ok,
                        f"digest={image_digest}"),
    ]


def _fleet_item_and_observation(
    fleet_diff: reap.SnapshotDiff, own_attempt_ids: Sequence[str],
) -> tuple[AcceptanceItem, str | None]:
    """The fleet check, ALWAYS emitted (issue #122, from the nit store): an
    incomparable pair of snapshots is unverified - `NOT EXERCISED` - never an
    omitted item that lets the demo pass without it.

    Only a change ATTRIBUTABLE to this run can fail it: a new owned
    container whose name is one of this run's own attempt containers. Any
    other change - a neighbour's new container, a foreign container that
    vanished - is reported as an unattributed OBSERVATION, never a failure
    (`reap.diff`'s own docstring: attribution is not causation). The
    observation carries counts, never names: a foreign container's name is
    the operator's own data, and nothing this block should repeat."""
    name = "no container leaked by this run"
    if not fleet_diff.comparable:
        return AcceptanceItem(
            name, False, "fleet snapshots incomparable - the daemon could not be listed before or after; unverified",
            exercised=False,
        ), None
    own_names = {dbe._container_name(attempt_id) for attempt_id in own_attempt_ids}
    ours = sorted(fleet_diff.leaked & own_names)
    unattributed_new = len(fleet_diff.leaked - own_names)
    vanished = len(fleet_diff.foreign_vanished)
    observation = None
    if unattributed_new or vanished:
        observation = (
            f"fleet observations (not attributed to this run, never a failure): "
            f"{unattributed_new} new skillc-owned container(s), {vanished} foreign container(s) vanished"
        )
    return AcceptanceItem(name, not ours, f"leaked by this run={ours}"), observation


# --------------------------------------------------------------- paste-back


def leak_check_text(text: str) -> list[str]:
    """Every finding `skillc.leak.scan_text` reports against `text` directly
    - no file round-trip, no tree walk: the paste-back block is a string in
    memory, and staging it to disk first would only add a chance to leave it
    there. Empty means clean."""
    denylist = leak.load_denylist()
    return [f"{lineno}: {kind}: {detail}" for lineno, kind, detail in leak.scan_text(text, denylist)]


def redact_known_host_paths(text: str, *, base: Path | None = None) -> str:
    """Replace every occurrence of a host-local absolute path THIS PROCESS
    ALREADY KNOWS with a generic placeholder, longest candidate first -
    `<base>` (the run's own disposable root, when given), `<repo>` (this
    checkout's root), `<home>` (the operator's home directory), `<tmp>`
    (the system temp directory).

    Cross-model review of issue #118's own fix: `leak_check_text` (via
    `leak.scan_text`'s `HOME_PATH_RE`) only matches `/home/<user>/...` - a
    checkout under `/opt`, `/srv`, or any non-`/home` layout sailed through
    it completely unscrubbed (reproduced live: an unreadable
    `subject.json` under a non-`/home` checkout printed its own absolute
    path, twice, via `SubjectRefused`'s message). Widening `leak.py`'s own
    pattern to catch every absolute path was rejected - it would
    false-positive on legitimate CONTAINER paths this codebase prints on
    purpose, like `/work` and `/home/candidate`. This is the alternative:
    proactively replace the SPECIFIC host paths this process can name in
    advance, before the leak-check ever runs - the leak-check remains the
    second, independent layer for anything this substitution does not
    name, never replaced by it.

    Longest-first matters: if `base` is nested under the system temp
    directory (the common case - `tempfile.gettempdir()` is `run_demo`'s
    own default `--base`), replacing `<tmp>` first would leave
    `<tmp>/<base's-own-subdirectory-name>` instead of the more specific,
    more useful `<base>`."""
    candidates: list[tuple[str, str]] = [
        (str(REPO_ROOT), "<repo>"),
        (str(Path.home()), "<home>"),
        (tempfile.gettempdir(), "<tmp>"),
    ]
    if base is not None:
        candidates.append((str(base), "<base>"))
    for original, placeholder in sorted(candidates, key=lambda pair: len(pair[0]), reverse=True):
        if original:
            text = text.replace(original, placeholder)
    return text


def describe_error_safely(exc: BaseException, *, base: Path | None = None) -> str:
    """A one-line description of `exc`, scrubbed the same way the paste-back
    block itself is (issue #118): an uncaught exception's own message can
    carry an absolute host path just as easily as the block can (a
    subprocess `CalledProcessError`, an `OSError` naming a real file) - this
    is the SAME guarantee `print_paste_back` gives that block, applied to
    the one other place raw text could reach the operator's terminal.
    `redact_known_host_paths` runs FIRST (see its own docstring for why);
    `leak_check_text` is the second, independent layer for anything that
    substitution does not name - a message still leaky after both is
    replaced with its type name alone, nothing partial ever printed."""
    detail = redact_known_host_paths(f"{type(exc).__name__}: {exc}", base=base)
    if leak_check_text(detail):
        return f"{type(exc).__name__} (detail withheld - it failed its own leak-check)"
    return detail


def build_paste_back(
    items: list[AcceptanceItem], image: str, image_digest: str | None, reap_report: reap.ReapReport,
    subject_result: SubjectResult | None = None, fleet_observation: str | None = None,
) -> str:
    prov = provenance.stamp()
    lines = [
        "skillc operator demo - paste-back block",
        f"skillc_version={prov.skillc_version} source_commit={prov.source_commit} dirty={prov.dirty}",
        f"image={image} image_digest={image_digest or 'UNKNOWN'}",
        "",
        "acceptance:",
    ]
    for item in items:
        label = "NOT EXERCISED" if not item.exercised else ("MET" if item.met else "NOT MET")
        lines.append(f"  [{label}] {item.name} - {item.evidence}")
    lines.append("")
    lines.append("cleanup (reap outcomes, four possible values: reaped/already-absent/left-running/unknown):")
    for outcome in reap_report.outcomes:
        lines.append(f"  {outcome.attempt_id}: {outcome.outcome}")
    lines.append(f"  daemon_reachable={reap_report.daemon_reachable}")
    if fleet_observation is not None:
        lines.append("")
        lines.append(fleet_observation)
    if subject_result is not None:
        lines.append(build_subject_paste_back(subject_result))
    return "\n".join(lines) + "\n"


class PasteBackRefused(Exception):
    """The assembled paste-back block failed its own leak-check and was
    never printed."""


def print_paste_back(text: str) -> None:
    """Leak-check `text`, refuse (raise, print nothing) if anything is
    found, otherwise print it verbatim - the operator redacts nothing
    because nothing reaches them that this check did not already clear."""
    findings = leak_check_text(text)
    if findings:
        raise PasteBackRefused(
            "paste-back block failed its own leak-check and was NOT printed:\n" + "\n".join(findings)
        )
    print(text)


# --------------------------------------------------------------------- runner


@dataclass(frozen=True)
class DemoResult:
    ok: bool
    paste_back: str
    lifecycle_record: dict[str, object]
    graded: verify.Graded
    reap_report: reap.ReapReport
    host_diff: reap.HostPathDiff
    image_digest: str | None
    subject_result: SubjectResult | None = None


def run_demo(
    *, image: str, docker_bin: Sequence[str], base: Path, timeout: float = 30,
    subject_name: str | None = None, subject_checkout: Path | None = None,
    subject_client: list[str] | None = None,
    recorded_attempt_ids: list[str] | None = None,
) -> DemoResult:
    """The command's own normal-mode run: the success path, end to end,
    against a real daemon. Two SEPARATE `DockerBackend` instances are used -
    one for the lifecycle demo, one for grading - never shared, matching
    interfaces.md step 8's "separate backend instance, same seam"
    requirement literally, not just in spirit. `--control`'s own run is
    `run_control()` below, a genuinely different verdict shape (every SEEDED
    failure must be CAUGHT), not this function with a flag flipped.

    `subject_name`, when given, runs a THIRD demonstration (`run_subject_demo`,
    issue #101) alongside the two above: installing a declared skill
    collection into a real container's home, re-checking its digests, and
    observing the client's own discovery of it. `None` (no `--subject` on
    the CLI) runs exactly the two-leg demo #97 shipped, unchanged - a flag
    that changes nothing when omitted, per the same discipline #97 itself
    was held to.

    `recorded_attempt_ids`, when given, is threaded into `run_lifecycle_demo`
    and `run_subject_demo` so the caller's own list is populated with each
    attempt id the instant it exists, before any backend call that could hang
    - `cmd_demo`'s `KeyboardInterrupt` handler reads it to scope its
    best-effort cleanup to exactly this run's own containers (issue #118
    review: a host-global sweep reaped a foreign run's container under a real
    interrupt). The grading probe's attempt id is threaded through too
    (issue #122, via `verify.grade_files(recorded_attempt_ids=...)`), so an
    interrupt during grading can reach its container, and the normal-path
    sweep covers it."""
    env = None  # inherit the operator's own ambient environment, like a plain `docker` invocation
    host_paths = [REPO_ROOT / p for p in HOST_PATHS_TO_WATCH]
    host_before = reap.snapshot_host_paths(host_paths)
    fleet_before = reap.snapshot(docker_bin, env, timeout)
    # Resolved BEFORE either backend starts, so it reflects the image both
    # backends actually create their containers from - resolving it only
    # after both demos ran (as this used to) would instead record whatever
    # `image` points at by the time the run finishes, which can be a
    # different image if the tag was rebuilt or retagged mid-run.
    image_digest = resolve_image_digest(docker_bin, image, env, timeout)

    lifecycle_backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)
    grading_backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)

    own_ids: list[str] = recorded_attempt_ids if recorded_attempt_ids is not None else []
    lifecycle_record = run_lifecycle_demo(lifecycle_backend, base, recorded_attempt_ids=own_ids)
    before_grading = len(own_ids)
    graded = run_grading_demo(grading_backend, GOOD_CANDIDATE, base, recorded_attempt_ids=own_ids)
    probe_ids = own_ids[before_grading:]

    subject_result: SubjectResult | None = None
    if subject_name is not None:
        subject_result = run_subject_demo(
            subject_name=subject_name, image=image, docker_bin=docker_bin, base=base, timeout=timeout,
            checkout=subject_checkout, client_argv=subject_client,
            recorded_attempt_ids=own_ids,
        )

    # The grading probe's attempt is swept too (issue #122): cleanup MET
    # used to cover the lifecycle attempt alone, a narrower population than
    # its wording claimed. The subject leg sweeps its own attempt itself.
    attempt_ids = [str(lifecycle_record["attempt_id"]), *probe_ids]
    reap_report = reap.reap(docker_bin, attempt_ids, env, timeout)

    fleet_after = reap.snapshot(docker_bin, env, timeout)
    fleet_diff = reap.diff(fleet_before, fleet_after)
    host_after = reap.snapshot_host_paths(host_paths)
    host_diff = reap.diff_host_paths(host_before, host_after)

    items = _acceptance_items(lifecycle_record, graded, reap_report, host_diff, image_digest)
    if subject_result is not None:
        items += _subject_acceptance_items(subject_result)
    fleet_item, fleet_observation = _fleet_item_and_observation(fleet_diff, own_ids)
    items.append(fleet_item)
    paste_back = build_paste_back(items, image, image_digest, reap_report, subject_result, fleet_observation)
    ok = all(item.met for item in items)
    return DemoResult(ok, paste_back, lifecycle_record, graded, reap_report, host_diff, image_digest, subject_result)


# ------------------------------------------------------------------ --control


@dataclass(frozen=True)
class ControlSeed:
    """One seeded failure and whether `--control` caught it. `evidence` is
    built only from facts this process derived itself (dispositions, reap
    outcomes, exit codes, attempt ids) - never raw text from a container or
    a child process - so the block it lands in is leak-checked, never
    trusted to be clean by construction alone."""

    name: str
    caught: bool
    evidence: str


@dataclass(frozen=True)
class ControlResult:
    ok: bool
    paste_back: str
    seeds: tuple[ControlSeed, ...]


#: Issue #122's timeout seed: a subject that sleeps well past a short limit.
#: The gap is wide on purpose - a real daemon's `docker exec` start-up is
#: counted against the limit, so a narrow one could let a slow daemon read
#: as a timeout for the wrong reason, and a sleep that finished first would
#: read as `exited`, never as a false catch.
TIMEOUT_CONTROL_LIMIT = 3.0
TIMEOUT_CONTROL_SLEEP = 30.0

#: Issue #122's cancellation seed: how long the child's exec would run if
#: never interrupted, and the bounded waits for its two readiness signals.
CANCEL_TARGET_SLEEP = 60.0
CANCEL_READY_TIMEOUT = 120.0
CANCEL_LIVE_TIMEOUT = 60.0

#: Printed by `--cancel-target` to stderr, once, as soon as its attempt is
#: planned - BEFORE `prepare()` creates any container (counter-model
#: re-review: announced any later, a parent killing the child in between
#: could not name the container it left). The parent reads the attempt id
#: from it, and nothing else - it is NOT the evidence that the exec is in
#: flight (see `CANCEL_LIVE_FILE`).
CANCEL_READY_MARKER = "skillc: cancel-target attempt="

#: Written into the container's workspace by the cancel-target's own
#: subject, as its first act inside the exec, before it sleeps. The parent
#: sends SIGINT only after reading this file back out of the RUNNING
#: container (counter-model review: a marker printed before `execute()` plus
#: a fixed delay is a timing argument, not evidence a live exec exists).
CANCEL_LIVE_FILE = ".skillc-cancel-live"

#: The fixed line `cmd_demo`'s `KeyboardInterrupt` handler prints - defined
#: here so the handler and the cancellation seed that checks for it cannot
#: drift apart.
INTERRUPT_LINE = (
    "skillc: demo interrupted - containers labelled for this run may remain; "
    "run the reap sweep or re-run to clean up"
)

_ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_CLEANUP_PAIR_RE = re.compile(r"\('([^']+)', '([^']+)'\)")


def _plan_one_attempt(base: Path, experiment: str, label: str) -> tuple[trial.Experiment, str]:
    """One planned attempt in the control store - the same scripted-subject
    trial shape every seed uses, planned through the real controller."""
    store = trial.open_store(base / "control-store", forbidden=[])
    spec: dict[str, object] = {
        "experiment": experiment,
        "trials": [{
            "label": label, "case": {"id": "c", "revision": "r1"},
            "grader": {"id": "g", "revision": "g1"}, "subject": {"digest": "sha256:00"},
            "client": {"name": "scripted", "version": "1"}, "image": {"digest": "sha256:01"},
            "config": {}, "attempts": 1,
        }],
    }
    planned = trial.plan(spec, store)
    [(_t, attempt)] = list(planned.attempts())
    return planned, str(attempt["attempt_id"])


def _sleep_argv(seconds: float) -> list[str]:
    return [verify.PROBE_INTERPRETER, "-c", f"import time; time.sleep({float(seconds)!r})"]


def run_timeout_control(
    *, image: str, docker_bin: Sequence[str], base: Path, timeout: float = 30,
    limit: float = TIMEOUT_CONTROL_LIMIT, sleep: float = TIMEOUT_CONTROL_SLEEP,
    recorded_attempt_ids: list[str] | None = None,
) -> ControlSeed:
    """Issue #122's timeout seed: one attempt, through the real driver,
    whose command sleeps past `limit`. On a real daemon the limit is
    enforced across `docker exec` and `docker kill`, so this is where real
    daemon semantics can differ from the fake's.

    CAUGHT only when every part holds: the stop reason is `timeout` (never
    `exited` - a subject that finished on its own proves nothing about
    enforcement); `confirm_stopped` confirmed the stop from the daemon's own
    `docker inspect`; the disposition is `inconclusive` - a lifecycle status,
    never a grading FAIL charged to the subject; and the reap sweep finds
    nothing left for the attempt (`reaped` or `already-absent`, never
    `left-running` or `unknown`)."""
    name = "timeout: an exec past its limit is stopped, confirmed and cleaned up"
    backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)
    experiment, attempt_id = _plan_one_attempt(base, "control", "timeout")
    if recorded_attempt_ids is not None:
        recorded_attempt_ids.append(attempt_id)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _sleep_argv(sleep), {"demo": "x"}, Limits(timeout=limit), base,
    )
    stop = record.get("stop")
    stop = stop if isinstance(stop, dict) else {}
    outcome = reap.reap(docker_bin, [attempt_id], None, timeout).outcome_for(attempt_id)
    caught = (
        stop.get("reason") == "timeout"
        and stop.get("confirmed") is True
        and record.get("disposition") == "inconclusive"
        and outcome in ("reaped", "already-absent")
    )
    evidence = (
        f"limit={limit}s sleep={sleep}s stop reason={stop.get('reason')} confirmed={stop.get('confirmed')} "
        f"signal={record.get('signal')} disposition={record.get('disposition')} "
        f"attempt={attempt_id} reap={outcome}"
    )
    return ControlSeed(name, caught, evidence)


def _cancel_target_argv(sleep: float) -> list[str]:
    """The cancel-target's subject: mark itself live, then sleep."""
    return [
        verify.PROBE_INTERPRETER, "-c",
        f"import pathlib, time; pathlib.Path({CANCEL_LIVE_FILE!r}).write_text('live'); time.sleep({float(sleep)!r})",
    ]


def _exec_is_live(docker_bin: Sequence[str], attempt_id: str, timeout: float) -> bool:
    """True once `CANCEL_LIVE_FILE` exists in the attempt's RUNNING
    container - asked of the daemon with a second `docker exec`, which
    itself fails on a container that is not running."""
    try:
        proc = subprocess.run(
            [*docker_bin, "exec", "-w", dbe.CONTAINER_WORKSPACE, "--", dbe._container_name(attempt_id),
             "test", "-f", CANCEL_LIVE_FILE],
            capture_output=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def run_cancel_target(
    *, image: str, docker_bin: Sequence[str], base: Path, timeout: float, sleep: float,
    recorded_attempt_ids: list[str],
) -> int:
    """The CHILD side of the cancellation seed (`skillc demo --cancel-target
    SECONDS`, a hidden flag): one attempt whose exec marks itself live
    (`CANCEL_LIVE_FILE`) and sleeps `sleep` seconds, announcing
    `CANCEL_READY_MARKER<attempt id>` on stderr before any container exists
    (see that constant). It runs inside
    `cmd_demo`'s own `try`, so a SIGINT lands on the real
    `KeyboardInterrupt` handler and its scoped sweep - the thing under test,
    not a copy of it. The attempt id is recorded before any backend call, as
    `run_lifecycle_demo` does.

    Returning at all means the interrupt never came: exit 1, never 0."""
    backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)
    experiment, attempt_id = _plan_one_attempt(base, "control", "cancel-target")
    recorded_attempt_ids.append(attempt_id)
    print(f"{CANCEL_READY_MARKER}{attempt_id}", file=sys.stderr, flush=True)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _cancel_target_argv(sleep), {"demo": "x"}, Limits(timeout=sleep + 60), base,
    )
    print(f"skillc: cancel-target was never interrupted - disposition={record.get('disposition')}", file=sys.stderr)
    return 1


def run_cancellation_control(
    *, image: str, docker_bin: Sequence[str], base: Path, timeout: float = 30,
    sleep: float = CANCEL_TARGET_SLEEP, ready_timeout: float = CANCEL_READY_TIMEOUT,
    live_timeout: float = CANCEL_LIVE_TIMEOUT, child_command: Sequence[str] | None = None,
    recorded_attempt_ids: list[str] | None = None,
) -> ControlSeed:
    """Issue #122's cancellation seed: a real SIGINT delivered to a real
    `skillc demo` process while its exec is in flight.

    A FOREIGN skillc-owned container is prepared first - owned, labelled,
    running, and not the child's. The child (`skillc demo --cancel-target`,
    `child_command` overriding only how skillc's CLI is launched) starts in
    its own session and announces its attempt id before creating any
    container. The parent then waits
    until the child's subject has written `CANCEL_LIVE_FILE` inside the
    running container - the evidence that the exec is in flight - and sends
    SIGINT to the child's whole process group, as Ctrl-C in a terminal does,
    so the `docker exec` client gets it too.

    CAUGHT only when every part holds: the exec was observed live; the child
    printed the fixed `INTERRUPT_LINE` and exited 1; its own cleanup line
    reports its attempt `reaped` or `already-absent`; an independent reap
    afterward finds it `already-absent` (`reaped` there would mean the child
    left it running, and this seed removed it); the foreign container was
    still running (`confirm_stopped` NOT_CONFIRMED); and this seed's own
    removal of the foreign container is confirmed. The handler normally
    reports `already-absent`, because the driver's own `finally` tears the
    container down before the handler sweeps - accepted by the owner on
    #122, since the independent reap is what shows nothing was left.

    However this function ends - including an interrupt of `--control`
    itself - the child's process group is killed and waited for, and the
    child's attempt id is appended to `recorded_attempt_ids` the moment it
    is announced, so the caller's own scoped sweep can reach its container."""
    name = "operator cancellation: a real SIGINT mid-exec is handled and scoped to this run"
    foreign_backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)
    foreign_id = f"control-foreign-{secrets.token_hex(6)}"
    if recorded_attempt_ids is not None:
        recorded_attempt_ids.append(foreign_id)
    try:
        foreign = foreign_backend.prepare(foreign_id)
    except dbe.BackendUnavailable:
        return ControlSeed(name, False, "the foreign container could not be prepared - the seed never ran")

    lines: list[str] = []
    ready = threading.Event()
    child_attempt: list[str] = []

    def _read(stream: IO[str]) -> None:
        for raw in stream:
            line = raw.rstrip("\n")
            lines.append(line)
            if line.startswith(CANCEL_READY_MARKER) and not ready.is_set():
                candidate = line[len(CANCEL_READY_MARKER):].strip()
                if _ATTEMPT_ID_RE.match(candidate):
                    child_attempt.append(candidate)
                    if recorded_attempt_ids is not None:
                        recorded_attempt_ids.append(candidate)
                ready.set()

    def _signal_group(proc: subprocess.Popen[str], sig: signal.Signals) -> None:
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass

    proc: subprocess.Popen[str] | None = None
    foreign_removed: Confirmation | None = None
    try:
        argv = [
            *(child_command if child_command is not None else [sys.executable, "-m", "skillc.cli"]),
            "demo", "--cancel-target", str(sleep), "--image", image, "--docker-bin", " ".join(docker_bin),
            "--base", str(base), "--timeout", str(timeout),
        ]
        try:
            proc = subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, errors="replace", start_new_session=True,
            )
        except OSError:
            return ControlSeed(name, False, "the child skillc process could not be started - the seed never ran")
        assert proc.stderr is not None
        reader = threading.Thread(target=_read, args=(proc.stderr,), daemon=True)
        reader.start()

        announced = ready.wait(ready_timeout) and bool(child_attempt)
        live = False
        if announced:
            deadline = time.monotonic() + live_timeout
            while proc.poll() is None and time.monotonic() < deadline:
                if _exec_is_live(docker_bin, child_attempt[0], timeout):
                    live = True
                    break
                time.sleep(0.1)

        sent: float | None = None
        if live:
            _signal_group(proc, signal.SIGINT)
            sent = time.monotonic()
        else:
            _signal_group(proc, signal.SIGKILL)
        try:
            exit_code = proc.wait(timeout=max(60.0, timeout * 4))
        except subprocess.TimeoutExpired:
            _signal_group(proc, signal.SIGKILL)
            exit_code = proc.wait()
        exited_after = time.monotonic() - sent if sent is not None else None
        reader.join(timeout=5)

        attempt = child_attempt[0] if child_attempt else None
        independent = reap.reap(docker_bin, [attempt], None, timeout).outcome_for(attempt) if attempt else None
        foreign_state = foreign_backend.confirm_stopped(foreign)
        foreign_running = foreign_state is Confirmation.NOT_CONFIRMED
        foreign_backend.destroy(foreign)
        foreign_removed = foreign_backend.confirm_absent(foreign)

        if attempt is None:
            return ControlSeed(
                name, False,
                f"the child never announced its attempt (waited {ready_timeout}s) - no SIGINT was sent, exit={exit_code}",
            )
        if not live:
            return ControlSeed(
                name, False,
                f"the child's exec was never observed live (waited {live_timeout}s) - no SIGINT was sent, "
                f"the child was killed; attempt={attempt} independent={independent} "
                f"foreign_removed={foreign_removed.value}",
            )

        interrupt_line = INTERRUPT_LINE in lines
        handler_outcome: str | None = None
        for line in lines:
            if line.startswith("skillc: best-effort cleanup - outcomes="):
                handler_outcome = dict(_CLEANUP_PAIR_RE.findall(line)).get(attempt)
        caught = (
            interrupt_line and exit_code == 1
            and handler_outcome in ("reaped", "already-absent")
            and independent == "already-absent"
            and foreign_running
            and foreign_removed is Confirmation.CONFIRMED
        )
        exited = f"{exited_after:.1f}s" if exited_after is not None else "unknown"
        evidence = (
            f"exec observed live, then SIGINT to the child's process group; "
            f"interrupt_line={'present' if interrupt_line else 'ABSENT'} exit={exit_code} "
            f"child exited {exited} after SIGINT (exec would have run {sleep}s) "
            f"attempt={attempt} handler={handler_outcome} independent={independent} "
            f"foreign={'running (untouched)' if foreign_running else f'NOT running ({foreign_state.value})'} "
            f"foreign_removed={foreign_removed.value}"
        )
        return ControlSeed(name, caught, evidence)
    finally:
        if proc is not None and proc.poll() is None:
            _signal_group(proc, signal.SIGKILL)
            proc.wait()
        if foreign_removed is None:
            foreign_backend.destroy(foreign)
            foreign_backend.confirm_absent(foreign)


#: The reply-only subject: runs, exits 0, never touches the canary.
_REPLY_ONLY_ARGV: tuple[str, ...] = (verify.PROBE_INTERPRETER, "-c", "pathlib_unused = 1")

#: The liveness reason `lifecycle.run_through_backend` records when the
#: canary exists but was never touched - the ONE failure the reply-only
#: seed exists to provoke.
_CANARY_UNTOUCHED = "the canary was never touched"


def _reply_only_seed(record: Mapping[str, object]) -> ControlSeed:
    """CAUGHT only for the specific failure this seed provokes (issue #122,
    from the nit store): the subject genuinely ran - a confirmed stop,
    `exited`, exit code 0 - and the attempt is `inconclusive` because the
    canary was never touched. `!= "captured"` alone accepted ANY failure: a
    launch failure, an unavailable daemon or a timeout never exercised the
    liveness check at all, yet read as caught."""
    stop = record.get("stop")
    stop = stop if isinstance(stop, dict) else {}
    ran = stop.get("reason") == "exited" and stop.get("exit_code") == 0 and stop.get("confirmed") is True
    canary_untouched = _CANARY_UNTOUCHED in str(record.get("reason", ""))
    caught = ran and record.get("disposition") == "inconclusive" and canary_untouched
    return ControlSeed(
        "reply-only client never touches the canary", caught,
        f"lifecycle disposition={record.get('disposition')} stop reason={stop.get('reason')} "
        f"exit_code={stop.get('exit_code')} canary_untouched={canary_untouched}",
    )


def build_control_paste_back(seeds: Sequence[ControlSeed], image: str, image_digest: str | None) -> str:
    prov = provenance.stamp()
    lines = [
        "skillc operator demo --control - paste-back block",
        f"skillc_version={prov.skillc_version} source_commit={prov.source_commit} dirty={prov.dirty}",
        f"image={image} image_digest={image_digest or 'UNKNOWN'}",
        "",
        "seeded failures (each must be CAUGHT for --control to pass):",
    ]
    for seed in seeds:
        lines.append(f"  [{'CAUGHT' if seed.caught else 'NOT CAUGHT'}] {seed.name} - {seed.evidence}")
    return "\n".join(lines) + "\n"


def run_control(
    *, image: str, docker_bin: Sequence[str], base: Path, timeout: float = 30,
    recorded_attempt_ids: list[str] | None = None,
    timeout_limit: float = TIMEOUT_CONTROL_LIMIT, timeout_sleep: float = TIMEOUT_CONTROL_SLEEP,
    cancel_sleep: float = CANCEL_TARGET_SLEEP, cancel_child_command: Sequence[str] | None = None,
) -> ControlResult:
    """Runs the seeded negative controls. `ok` is True only if EVERY one was
    actually caught - never that everything came back clean, which would be
    the wrong verdict for a deliberately broken run. `paste_back` reports
    each seed on its own line (issue #122: the earlier single aggregate line
    left each case entailed but never shown).

    Six seeded failures:
      1. the reply-only client (a subject that never touches the canary) -
         caught by `lifecycle.py`'s own liveness check (`inconclusive`, never
         `captured`).
      2. a container left running - simulated by calling `prepare()` and
         deliberately NEVER calling `destroy()`/`confirm_absent()` on it (a
         stand-in for a crashed controller, per-attempt teardown never
         running at all) - `reap()`'s own independent sweep (#79's second,
         separate layer) must find and remove it. This is the PORTABLE way
         to seed this failure: forcing a REAL daemon's own `docker rm` to
         lie is not something this control can do generically against an
         operator's real daemon, but "teardown never ran" is exactly the
         crash scenario `reap()` exists to catch, and is trivial to seed
         honestly on any daemon, fake or real.
      3. a known-bad grading candidate must FAIL.
      4. a leaky paste-back block must be refused.
      5. a timeout (`run_timeout_control`, issue #122).
      6. an operator cancellation by a real SIGINT (`run_cancellation_control`,
         issue #122).
    The `timeout_*`/`cancel_*` arguments exist so tests against the fake
    `docker` can run the same seeds quickly; the CLI never passes them.
    """
    env = None  # inherit the operator's own ambient environment, like a plain `docker` invocation
    image_digest = resolve_image_digest(docker_bin, image, env, timeout)
    backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)
    seeds: list[ControlSeed] = []

    # 1. Reply-only subject: never touches the canary.
    experiment, attempt_id = _plan_one_attempt(base, "control", "reply-only")
    if recorded_attempt_ids is not None:
        recorded_attempt_ids.append(attempt_id)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, list(_REPLY_ONLY_ARGV), {"demo": "x"}, Limits(timeout=30), base,
    )
    seeds.append(_reply_only_seed(record))

    # 2. A container deliberately left running - reap() must find and
    # remove it (a genuine orphan, teardown never invoked on purpose).
    # `prepare()` itself failing (issue #118: an uncaught BackendUnavailable
    # here printed a raw traceback with the operator's own home directory
    # and username) means the orphan was never even seeded, so this control
    # cannot certify anything - caught, never raised, and read as NOT caught,
    # exactly like any other seeded failure this function fails to catch.
    orphan_backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)
    orphan_attempt_id = "control-orphan-000000000001"
    if recorded_attempt_ids is not None:
        recorded_attempt_ids.append(orphan_attempt_id)
    try:
        orphan_backend.prepare(orphan_attempt_id)  # note: never destroy()'d - that is the seeded failure
    except dbe.BackendUnavailable:
        seeds.append(ControlSeed(
            "container left running is found by the reap sweep", False,
            "prepare failed - the orphan was never seeded",
        ))
    else:
        orphan_outcome = reap.reap(docker_bin, [orphan_attempt_id], env, timeout).outcome_for(orphan_attempt_id)
        seeds.append(ControlSeed(
            "container left running is found by the reap sweep", orphan_outcome == "reaped",
            f"reap outcome={orphan_outcome}",
        ))

    # 3. A known-bad grading candidate must FAIL, not PASS.
    grading_backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)
    graded = run_grading_demo(grading_backend, BAD_CANDIDATE, base)
    seeds.append(ControlSeed(
        "known-bad grading candidate FAILs", graded.status == "FAIL", f"grading status={graded.status}",
    ))

    # 4. A leaky paste-back must be refused, never printed. Built from two
    # fragments on purpose: `skillc/leak.py`'s own docstring names "built at
    # runtime (string concatenation...)" as exactly what its static scan
    # cannot see, and this file IS scanned by the repo-wide `leak-check .`
    # CI gate - a single literal here would make this control fixture itself
    # the leak. `leak_check_text` still catches it below because it scans the
    # ASSEMBLED string, not this source line. Do not join these into one
    # literal.
    seeded_identity = "/home/" + "exampleuser" + "/leaked"
    leaky_block = f"planted host value for the control run: {seeded_identity}\n"
    try:
        print_paste_back(leaky_block)
        leak_caught = False
    except PasteBackRefused:
        leak_caught = True
    seeds.append(ControlSeed(
        "leaky paste-back block is refused", leak_caught,
        "the planted block was refused and not printed" if leak_caught else "the planted block was PRINTED",
    ))

    # 5 and 6: issue #122's real-daemon seeds.
    seeds.append(run_timeout_control(
        image=image, docker_bin=docker_bin, base=base, timeout=timeout,
        limit=timeout_limit, sleep=timeout_sleep, recorded_attempt_ids=recorded_attempt_ids,
    ))
    seeds.append(run_cancellation_control(
        image=image, docker_bin=docker_bin, base=base, timeout=timeout,
        sleep=cancel_sleep, child_command=cancel_child_command, recorded_attempt_ids=recorded_attempt_ids,
    ))

    ok = all(seed.caught for seed in seeds)
    return ControlResult(ok, build_control_paste_back(seeds, image, image_digest), tuple(seeds))
