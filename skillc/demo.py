"""The one prepared command for #10's live demonstration: `skillc trial-demo
--docker`.

Runs on the SAME MACHINE skillc is checked out on. There is no dedicated
evaluation VM (operator correction, issue #10 discussion, superseding an
earlier "clean machine" framing) - the operator's own machine carries other
workloads, which is exactly why the isolation properties matter MORE, not
less: the neutral trial identity, the allowlisted env, no host mounts beyond
the per-trial root, a private empty `~/.claude`/`~/.codex`, and no docker
socket in the trial (see `docker_backend.py`'s own module docstring for each
of these).

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
    this demo reading through a real client's transcripts."""
    snapshot: dict[str, object] = {}
    for path in WATCHED_HOST_PATHS:
        if not path.exists():
            snapshot[str(path)] = None
        elif path.is_dir():
            snapshot[str(path)] = sorted(p.name for p in path.iterdir())
        else:
            snapshot[str(path)] = path.stat().st_size
    return snapshot


def _host_state_report(before: dict[str, object], after: dict[str, object]) -> list[str]:
    changes = [key for key in before if before[key] != after.get(key)]
    return changes


def _paste_back_block(
    disposition: str, liveness_method: str | None, backend_teardown: str | None,
    readiness: dict[str, object] | None, host_changes: list[str], control: bool,
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
        f"host_state_unchanged: {not host_changes}",
    ]
    if host_changes:
        lines.append(f"host_state_changed_paths: {host_changes}")
    lines.append("--- end paste-back ---")
    return "\n".join(lines)


def run(control: bool = False, base: Path | None = None) -> int:
    """Runs the demo (or, with `control=True`, its own committed negative
    control). Returns the process exit code: 0 success, 1 an unexpected
    failure, 2 the daemon is unavailable (never a host fallback)."""
    docker_bin = ("docker",)
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

        backend = docker_backend.DockerBackend(image=DEMO_IMAGE, base_dir=workdir / "backend")
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
        raw_readiness = record.get("readiness")
        readiness = raw_readiness if isinstance(raw_readiness, dict) else None

        block = _paste_back_block(
            disposition,
            liveness_method if isinstance(liveness_method, str) or liveness_method is None else None,
            backend_teardown if isinstance(backend_teardown, str) or backend_teardown is None else None,
            readiness, host_changes, control,
        )
        # A self-check the operator does not have to redo, not merely a
        # claim that this block is clean.
        findings = list(leak.scan_text(block, leak.load_denylist(None)))
        if findings:
            print("skillc trial-demo: REFUSING to print the paste-back block - it leaked:", file=sys.stderr)
            for line_no, kind, matched in findings:
                print(f"  line {line_no}: {kind}: {matched}", file=sys.stderr)
            return 1

        print(block)
        if host_changes:
            print(
                f"\nskillc trial-demo: WARNING - {len(host_changes)} watched host path(s) "
                f"changed outside the trial root: {host_changes}",
                file=sys.stderr,
            )

        if control:
            if disposition == "inconclusive" and liveness_method is not None:
                return 0
            print(
                f"skillc trial-demo --control: expected an inconclusive liveness refusal, "
                f"got disposition={disposition!r} - the control did NOT go red",
                file=sys.stderr,
            )
            return 1
        return 0 if disposition == "captured" else 1
