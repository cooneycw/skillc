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
adapters now exist (issue #106, its first split PR); the driver loop that
would run a real agent through this command and consume them is the second
half of #106, not built here - this demo's liveness canary uses
`lifecycle.py`'s own file-content mechanism instead, which has no such gap
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
import stat
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import docker_backend as dbe
from . import leak, lifecycle, provenance, reap, trial, verify
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


def run_lifecycle_demo(backend: dbe.DockerBackend, base: Path) -> dict[str, object]:
    """One attempt, through the REAL driver (`lifecycle.run_through_backend`),
    against `backend`. Returns the same lifecycle record shape that driver
    always returns - `record["disposition"]` is `"captured"` on a genuine
    success, through a real daemon, with liveness proven by the canary file's
    content (never a claim from an exit code alone)."""
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


# ------------------------------------------------------------ acceptance items


@dataclass(frozen=True)
class AcceptanceItem:
    name: str
    met: bool
    evidence: str


def _acceptance_items(
    lifecycle_record: dict[str, object], graded: verify.Graded,
    reap_report: reap.ReapReport, host_diff: reap.HostPathDiff, image_digest: str | None,
) -> list[AcceptanceItem]:
    lifecycle_ok = lifecycle_record.get("disposition") == "captured"
    grading_ok = graded.status == "PASS"
    reap_ok = reap_report.daemon_reachable and not reap_report.left_running and not reap_report.unknown
    host_ok = not host_diff.changed and not host_diff.unresolved
    digest_ok = image_digest is not None
    return [
        AcceptanceItem("full Docker trial lifecycle (prepare..confirm_absent)", lifecycle_ok,
                        f"lifecycle disposition={lifecycle_record.get('disposition')}"),
        AcceptanceItem("grades through the verifier's backend seam (#76)", grading_ok,
                        f"grading status={graded.status}, detail={graded.detail}"),
        AcceptanceItem("cleanup sweep confirms no owned container left running", reap_ok,
                        f"reap outcomes={[o.outcome for o in reap_report.outcomes]}"),
        AcceptanceItem("declared host paths unchanged", host_ok,
                        f"changed={list(host_diff.changed)}, unresolved={list(host_diff.unresolved)}"),
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


def build_paste_back(
    items: list[AcceptanceItem], image: str, image_digest: str | None, reap_report: reap.ReapReport,
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
        lines.append(f"  [{'MET' if item.met else 'NOT MET'}] {item.name} - {item.evidence}")
    lines.append("")
    lines.append("cleanup (reap outcomes, four possible values: reaped/already-absent/left-running/unknown):")
    for outcome in reap_report.outcomes:
        lines.append(f"  {outcome.attempt_id}: {outcome.outcome}")
    lines.append(f"  daemon_reachable={reap_report.daemon_reachable}")
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


def run_demo(*, image: str, docker_bin: Sequence[str], base: Path, timeout: float = 30) -> DemoResult:
    """The command's own normal-mode run: the success path, end to end,
    against a real daemon. Two SEPARATE `DockerBackend` instances are used -
    one for the lifecycle demo, one for grading - never shared, matching
    interfaces.md step 8's "separate backend instance, same seam"
    requirement literally, not just in spirit. `--control`'s own run is
    `run_control()` below, a genuinely different verdict shape (every SEEDED
    failure must be CAUGHT), not this function with a flag flipped."""
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

    lifecycle_record = run_lifecycle_demo(lifecycle_backend, base)
    graded = run_grading_demo(grading_backend, GOOD_CANDIDATE, base)

    attempt_ids = [str(lifecycle_record["attempt_id"])]
    reap_report = reap.reap(docker_bin, attempt_ids, env, timeout)

    fleet_after = reap.snapshot(docker_bin, env, timeout)
    fleet_diff = reap.diff(fleet_before, fleet_after)
    host_after = reap.snapshot_host_paths(host_paths)
    host_diff = reap.diff_host_paths(host_before, host_after)

    items = _acceptance_items(lifecycle_record, graded, reap_report, host_diff, image_digest)
    if fleet_diff.comparable and (fleet_diff.leaked or fleet_diff.foreign_vanished):
        items.append(AcceptanceItem(
            "no unexpected container leak or foreign disappearance", False,
            f"leaked={list(fleet_diff.leaked)}, foreign_vanished={list(fleet_diff.foreign_vanished)}",
        ))
    paste_back = build_paste_back(items, image, image_digest, reap_report)
    ok = all(item.met for item in items)
    return DemoResult(ok, paste_back, lifecycle_record, graded, reap_report, host_diff, image_digest)


def run_control(*, image: str, docker_bin: Sequence[str], base: Path, timeout: float = 30) -> bool:
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
    reply_only_argv = [verify.PROBE_INTERPRETER, "-c", "pathlib_unused = 1"]  # does nothing; never touches the canary
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, reply_only_argv, {"demo": "x"}, Limits(timeout=30), base,
    )
    reply_only_caught = record.get("disposition") != "captured"

    # 2. A container deliberately left running - reap() must find and
    # remove it (a genuine orphan, teardown never invoked on purpose).
    orphan_backend = dbe.DockerBackend(image=image, base_dir=base, docker_bin=docker_bin, daemon_timeout=timeout)
    orphan_attempt_id = "control-orphan-000000000001"
    orphan_backend.prepare(orphan_attempt_id)  # note: never destroy()'d - that is the seeded failure
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
