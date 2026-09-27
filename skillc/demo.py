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
import secrets
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import docker_backend as dbe
from . import leak, lifecycle, materialize, provenance, reap, trial, verify
from .backend import Limits

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


def run_grading_demo(backend: dbe.DockerBackend, candidate_dir: Path, base: Path) -> verify.Graded:
    """Grade `candidate_dir` against the certified `slug-small-fix` task
    through `backend` - a fresh instance, never the lifecycle demo's own (the
    same "separate backend instance, same seam" interfaces.md step 8
    requires)."""
    grader = verify.GraderDef.load(GRADER_ROOT)
    files = _candidate_files(candidate_dir)
    return verify.grade_files(grader, files, base, backend=backend)


# --------------------------------------------------------------- subject demo


#: `CODEX_HOME` for the installed collection, relative to `CONTAINER_HOME` -
#: `materialize.Arm.codex_home`'s own convention (`<home>/.codex`), aimed at
#: a real container's home instead of a host arm directory.
_SUBJECT_CODEX_HOME_RELPATH = ".codex"
_SUBJECT_SKILLS_PREFIX = f"{_SUBJECT_CODEX_HOME_RELPATH}/skills"


@dataclass(frozen=True)
class SubjectFile:
    directory: str  # the skill's own directory name under the subject's skills_root
    rel: str  # relative to that directory, e.g. "SKILL.md"
    skill: str  # the skill's declared `name`, from its own frontmatter
    digest: str

    @property
    def container_relpath(self) -> str:
        return f"{_SUBJECT_SKILLS_PREFIX}/{self.directory}/{self.rel}"


def subject_surface_files(source: materialize.Source, entries: list[materialize.SkillEntry]) -> list[SubjectFile]:
    """Every file across every selected skill, as a flat list ready to
    deliver into a container's home - `entries` is `inventory()`'s own
    output, so a `--subject` whose `select` names a skill absent from the
    surface never reaches here at all: `inventory()` raises
    `materialize.Refused` first (translated to `SubjectRefused` by the
    caller), before any Docker work starts."""
    return [
        SubjectFile(entry.directory, str(f["path"]), entry.name, str(f["digest"]))
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
) -> tuple[dict[str, str], str | None]:
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
    `selected`, or every one of them mapped to `"UNMEASURED"` with a reason
    string when the listing could not run at all (a launch failure, a
    nonzero exit, no `observations` file, or output the shared parser
    cannot read) - never dropped, never a silent partial result."""

    def unmeasured(reason: str) -> tuple[dict[str, str], str | None]:
        return {name: "UNMEASURED" for name in selected}, reason

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
    return {name: ("discovered" if name in listed else "not-discovered") for name in selected}, None


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
        files = subject_surface_files(source, entries)
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
            discovery, discovery_reason = run_subject_discovery(
                backend, handle, client_argv if client_argv is not None else ["codex"],
                selected, Limits(timeout=timeout), base,
            )
        finally:
            backend.destroy(handle)
            backend.confirm_absent(handle)

        reap_report = reap.reap(docker_bin, [attempt_id], env, timeout)
        host_after = reap.snapshot_host_paths(host_paths)
        host_diff = reap.diff_host_paths(host_before, host_after)
        return SubjectResult(
            subject_name, subject.revision, receipt, digest_status, mismatches, discovery, discovery_reason,
            host_diff, reap_report,
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
    subject_result: SubjectResult | None = None,
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
    interrupt). The grading demo's own internal probe attempt id is not
    threaded through - `verify.grade_files` does not expose it - so an
    interrupt during grading alone leaves nothing recorded to sweep; that is
    the accepted, narrower gap this fix leaves in place rather than widening
    `verify.py`'s own API for it."""
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

    lifecycle_record = run_lifecycle_demo(lifecycle_backend, base, recorded_attempt_ids=recorded_attempt_ids)
    graded = run_grading_demo(grading_backend, GOOD_CANDIDATE, base)

    subject_result: SubjectResult | None = None
    if subject_name is not None:
        subject_result = run_subject_demo(
            subject_name=subject_name, image=image, docker_bin=docker_bin, base=base, timeout=timeout,
            checkout=subject_checkout, client_argv=subject_client,
            recorded_attempt_ids=recorded_attempt_ids,
        )

    attempt_ids = [str(lifecycle_record["attempt_id"])]
    reap_report = reap.reap(docker_bin, attempt_ids, env, timeout)

    fleet_after = reap.snapshot(docker_bin, env, timeout)
    fleet_diff = reap.diff(fleet_before, fleet_after)
    host_after = reap.snapshot_host_paths(host_paths)
    host_diff = reap.diff_host_paths(host_before, host_after)

    items = _acceptance_items(lifecycle_record, graded, reap_report, host_diff, image_digest)
    if subject_result is not None:
        items += _subject_acceptance_items(subject_result)
    if fleet_diff.comparable and (fleet_diff.leaked or fleet_diff.foreign_vanished):
        items.append(AcceptanceItem(
            "no unexpected container leak or foreign disappearance", False,
            f"leaked={list(fleet_diff.leaked)}, foreign_vanished={list(fleet_diff.foreign_vanished)}",
        ))
    paste_back = build_paste_back(items, image, image_digest, reap_report, subject_result)
    ok = all(item.met for item in items)
    return DemoResult(ok, paste_back, lifecycle_record, graded, reap_report, host_diff, image_digest, subject_result)


def run_control(
    *, image: str, docker_bin: Sequence[str], base: Path, timeout: float = 30,
    recorded_attempt_ids: list[str] | None = None,
) -> bool:
    """Runs the seeded negative controls and returns True only if EVERY one
    was actually caught - never that everything came back clean, which would
    be the wrong verdict for a deliberately broken run.

    Three seeded failures, matching the issue's own list:
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
      3. a leaky composition - the known-bad grading candidate, and a
         planted host value in a synthesized paste-back block.
    """
    env = None  # inherit the operator's own ambient environment, like a plain `docker` invocation
    backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)

    # 1. Reply-only subject: never touches the canary.
    store = trial.open_store(base / "control-store", forbidden=[])
    spec: dict[str, object] = {
        "experiment": "control",
        "trials": [{
            "label": "reply-only", "case": {"id": "c", "revision": "r1"},
            "grader": {"id": "g", "revision": "g1"}, "subject": {"digest": "sha256:00"},
            "client": {"name": "scripted", "version": "1"}, "image": {"digest": "sha256:01"},
            "config": {}, "attempts": 1,
        }],
    }
    experiment = trial.plan(spec, store)
    [(_t, attempt)] = list(experiment.attempts())
    attempt_id = str(attempt["attempt_id"])
    if recorded_attempt_ids is not None:
        recorded_attempt_ids.append(attempt_id)
    reply_only_argv = [verify.PROBE_INTERPRETER, "-c", "pathlib_unused = 1"]  # does nothing; never touches the canary
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, reply_only_argv, {"demo": "x"}, Limits(timeout=30), base,
    )
    reply_only_caught = record.get("disposition") != "captured"

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
        left_running_caught = False
    else:
        orphan_report = reap.reap(docker_bin, [orphan_attempt_id], env, timeout)
        left_running_caught = orphan_report.outcome_for(orphan_attempt_id) == "reaped"

    # 3. A known-bad grading candidate must FAIL, not PASS.
    grading_backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)
    graded = run_grading_demo(grading_backend, BAD_CANDIDATE, base)
    bad_candidate_caught = graded.status == "FAIL"

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

    return reply_only_caught and left_running_caught and bad_candidate_caught and leak_caught
