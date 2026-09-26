"""The one prepared command for #10's live demonstration: `skillc trial-demo
--docker`.

Runs on the SAME MACHINE skillc is checked out on - there is no separate,
dedicated machine set aside for this (operator correction, issue #10
discussion, superseding an earlier "clean machine" framing). The operator's
own machine carries other workloads, which is exactly why the isolation
properties matter MORE, not less: the neutral trial identity, the allowlisted
env, no host mounts beyond the per-trial root, a private empty
`~/.claude`/`~/.codex`, and no docker socket in the trial (see
`docker_backend.py`'s own module docstring for each of these).

WHAT THIS PROVES, AND WHAT IT DOES NOT. This command uses a small, fully
deterministic in-line Python subject - not a real agent CLI - so it proves
the LIFECYCLE end to end (prepare, install, execute, confirm_stopped, export,
capture, destroy, confirm_absent) and the liveness canary, against a REAL
Docker daemon. It does NOT run a real Claude Code or Codex session; that is
future work layered on the same seam. `describe()`'s `unobserved` claims
still apply.

THE COMMITTED NEGATIVE CONTROL (`--control`). Runs the SAME lifecycle with
the addendum's own extended failure client (one that answers plausibly
without touching the canary - see `tests/fixtures/backend-lifecycle/
fake_client.py`'s `reply-only` mode) and asserts it is refused, never
captured. A demo whose only recorded outcome is ever "PASS" is not
evidence; this is the instrument's own proof that it can report the other
verdict, run through the real Docker backend, not just the fake CLI this
package's own test suite uses.

THE PASTE-BACK BLOCK is deliberately the ONLY thing this command asks an
operator to return: a short, neutral summary carrying no machine identities.
It is passed through `skillc leak-check` (via `leak.scan_text`) before this
command ever prints it - printing a self-check the operator does not have to
redo, not merely a claim that it was clean.

HOST STATE CHECK. A small, DECLARED set of host paths (never a general host
integrity scan - stated explicitly, because "exercised and clean" is not
"never exercised") is snapshotted before and after. Any change outside the
trial's own root is reported, never silently accepted.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from . import docker_backend, leak, lifecycle, provenance, trial
from .backend import BackendUnavailable, Limits

#: A public, unmodified image - this project does not yet build or pin its
#: own trial image (that is separate follow-up work, not #10's demo). Real
#: use should pin by digest; see docker_backend.py's own note on why the
#: digest that RAN is recorded regardless of what was asked for.
DEMO_IMAGE = "python:3.12-slim"

#: A small, DECLARED set of host paths whose absence-of-change is this
#: demo's own check that nothing outside the trial root moved. Deliberately
#: small and named explicitly: this is not a general host integrity scan,
#: and the printed report says so.
WATCHED_HOST_PATHS: tuple[Path, ...] = (Path.home() / ".claude", Path.home() / ".codex")

SUBJECT_SCRIPT_WORK = (
    "import pathlib\n"
    "canary = pathlib.Path('.skillc-canary')\n"
    "if canary.is_file():\n"
    "    pathlib.Path('.skillc-canary-result').write_text('touched:' + canary.read_text())\n"
    "pathlib.Path('out.txt').write_text('hello from the demo subject\\n')\n"
)

#: The addendum's own extended negative control: plausible output, canary
#: never touched (issue #10 comment 5848577772, lesson 2).
SUBJECT_SCRIPT_REPLY_ONLY = (
    "import pathlib\n"
    "pathlib.Path('out.txt').write_text(\"Sure, I've completed the task. Everything looks good!\\n\")\n"
)

SETUP_LINES = """\
git clone https://github.com/cooneycw/skillc.git
cd skillc
uv sync
uv run skillc trial-demo --docker
"""


def _watched_snapshot() -> dict[str, object]:
    """A shallow listing (names only, never content) of each watched path -
    enough to notice something appeared, disappeared or was renamed, without
    this demo reading through a real client's transcripts. Keyed by
    `_display_path`, never the raw absolute path: a changed-path report built
    from this snapshot (`_host_state_report`) can end up in the printed
    paste-back block, and the raw form would put the operator's real
    `/home/<name>` into it - `_display_path` is what keeps that block
    leak-safe on a real host, not just in this function's own callers."""
    snapshot: dict[str, object] = {}
    for path in WATCHED_HOST_PATHS:
        key = _display_path(path)
        if not path.exists():
            snapshot[key] = None
        elif path.is_dir():
            snapshot[key] = sorted(p.name for p in path.iterdir())
        else:
            snapshot[key] = path.stat().st_size
    return snapshot


def _host_state_report(before: dict[str, object], after: dict[str, object]) -> list[str]:
    changes = [key for key in before if before[key] != after.get(key)]
    return changes


def _display_path(path: Path) -> str:
    """A leak-safe display form: `~`-relative when `path` sits under the real
    home directory, never the resolved absolute path with the operator's
    actual username in it. `WATCHED_HOST_PATHS` is built from `Path.home()`,
    so printing it unqualified would put a real `/home/<name>` path into the
    block on every run on a real host - which `leak.scan_text` would then
    correctly refuse, since only `/home/candidate` is allowlisted (found
    while adding the watched-path report: it is not a hypothetical, it fires
    on the very first real invocation)."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _paste_back_block(
    disposition: str, liveness_method: str | None, backend_teardown: str | None,
    readiness: dict[str, object] | None, host_changes: list[str], control: bool,
    watched_paths: tuple[Path, ...] = WATCHED_HOST_PATHS,
) -> str:
    stamp = provenance.stamp().as_dict()
    image_digest = readiness.get("image_digest") if isinstance(readiness, dict) else None
    lines = [
        "--- skillc trial-demo paste-back (return this block verbatim) ---",
        f"mode: {'control (expects a red verdict)' if control else 'demo'}",
        f"disposition: {disposition}",
        f"liveness_method: {liveness_method}",
        f"backend_teardown: {backend_teardown}",
        f"image_digest: {image_digest}",
        f"skillc_version: {stamp['skillc_version']}",
        f"source_commit: {stamp['source_commit']}",
        f"source_dirty: {stamp['dirty']}",
        # A small, DECLARED population, not a general host integrity scan
        # (bug found by cross-model review: the earlier block reported
        # "unchanged" with no statement of what was even looked at, which
        # reads as a stronger claim than it is). Named here explicitly so a
        # reader of the pasted block - not just this module's docstring -
        # knows the check's own scope.
        f"host_state_watched_paths: {[_display_path(p) for p in watched_paths]}",
        f"host_state_unchanged: {not host_changes}",
    ]
    if host_changes:
        lines.append(f"host_state_changed_paths: {host_changes}")
    lines.append("--- end paste-back ---")
    return "\n".join(lines)


def run(
    control: bool = False, base: Path | None = None,
    docker_bin: Sequence[str] = ("docker",), image: str = DEMO_IMAGE,
) -> int:
    """Runs the demo (or, with `control=True`, its own committed negative
    control). Returns the process exit code: 0 success, 1 an unexpected
    failure, 2 the daemon is unavailable (never a host fallback).

    `docker_bin` and `image` default to the real `docker` CLI and a public
    image; tests substitute a fake CLI (no daemon is available in this
    package's own test environment) - see interfaces.md's "Liveness" note
    and issue #10 comment 5848577772, lesson E17, for what a fake CLI can and
    cannot prove."""
    version = docker_backend.probe_daemon(docker_bin)
    if version is None:
        print("skillc trial-demo: docker daemon unreachable.\n", file=sys.stderr)
        print("Setup (a skillc checkout, Docker, git and uv - nothing else):\n", file=sys.stderr)
        print(SETUP_LINES, file=sys.stderr)
        return 2

    before = _watched_snapshot()
    with tempfile.TemporaryDirectory(prefix="skillc-trial-demo-") as tmp:
        workdir = base or Path(tmp)
        store = trial.open_store(workdir / "store", forbidden=[])
        spec: dict[str, object] = {
            "experiment": "demo",
            "trials": [{
                "label": "control" if control else "demo",
                "case": {"id": "skillc-trial-demo", "revision": "1"},
                "grader": {"id": "none", "revision": "1"},
                "subject": {"digest": "sha256:demo"},
                "client": {"name": "skillc-demo-subject", "version": "1"},
                "image": {"digest": "sha256:demo"},
                "config": {}, "attempts": 1,
            }],
        }
        experiment = trial.plan(spec, store)
        [(_trial, attempt)] = list(experiment.attempts())
        attempt_id = str(attempt["attempt_id"])

        backend = docker_backend.DockerBackend(
            image=image, base_dir=workdir / "backend", docker_bin=docker_bin,
        )
        script = SUBJECT_SCRIPT_REPLY_ONLY if control else SUBJECT_SCRIPT_WORK
        try:
            record = lifecycle.run_through_backend(
                backend, experiment, attempt_id, ["python3", "-c", script], {"skill": "demo"},
                Limits(timeout=60), workdir / "base",
            )
        except BackendUnavailable as exc:
            print(f"skillc trial-demo: {exc}\n", file=sys.stderr)
            return 2

        after = _watched_snapshot()
        host_changes = _host_state_report(before, after)

        disposition = str(record.get("disposition"))
        liveness_method = record.get("liveness_method")
        backend_teardown = record.get("backend_teardown")
        reason = record.get("reason")
        raw_readiness = record.get("readiness")
        readiness = raw_readiness if isinstance(raw_readiness, dict) else None

        block = _paste_back_block(
            disposition,
            liveness_method if isinstance(liveness_method, str) or liveness_method is None else None,
            backend_teardown if isinstance(backend_teardown, str) or backend_teardown is None else None,
            readiness, host_changes, control, WATCHED_HOST_PATHS,
        )
        # A self-check the operator does not have to redo, not merely a
        # claim that this block is clean.
        findings = list(leak.scan_text(block, leak.load_denylist(None)))
        if findings:
            print("skillc trial-demo: REFUSING to print the paste-back block - it leaked:", file=sys.stderr)
            # NEVER print `matched` (bug found by cross-model review): that is
            # the actual sensitive text the refusal exists to withhold, and
            # printing it here would defeat the whole point of refusing.
            # `line_no`/`kind` are enough to act on the refusal without
            # reproducing what was found.
            for line_no, kind, _matched in findings:
                print(f"  line {line_no}: {kind}", file=sys.stderr)
            return 1

        print(block)
        if host_changes:
            print(
                f"\nskillc trial-demo: WARNING - {len(host_changes)} watched host path(s) "
                f"changed outside the trial root: {host_changes}",
                file=sys.stderr,
            )

        # Confirmed teardown is required either way (bug found by cross-model
        # review: neither branch used to check it at all) - a captured or
        # correctly-refused attempt whose container was never confirmed gone
        # is not a clean demonstration of the lifecycle, whatever its
        # disposition says.
        teardown_confirmed = backend_teardown == "confirmed"
        if control:
            # The control must go red BECAUSE the liveness check caught the
            # reply-only client - not merely "inconclusive for some other
            # reason" (bug found by cross-model review), which would prove
            # nothing about the liveness check this control exists to test.
            liveness_refused = (
                disposition == "inconclusive"
                and liveness_method is not None
                and isinstance(reason, str)
                and "liveness" in reason
            )
            if liveness_refused and teardown_confirmed:
                return 0
            print(
                "skillc trial-demo --control: expected a liveness-caused inconclusive refusal "
                f"AND a confirmed teardown, got disposition={disposition!r} reason={reason!r} "
                f"backend_teardown={backend_teardown!r} - the control did NOT go red as expected",
                file=sys.stderr,
            )
            return 1
        if disposition == "captured" and teardown_confirmed:
            return 0
        print(
            f"skillc trial-demo: expected disposition=captured and a confirmed teardown, got "
            f"disposition={disposition!r} backend_teardown={backend_teardown!r}",
            file=sys.stderr,
        )
        return 1
