"""Drives one attempt through an ExecutionBackend, end to end (#10, PR1b).

Ties `backend.py`'s Protocol to `trial.py`'s controller-owned accounting: the
nine lifecycle steps, backend-side and controller-side, in one function. This
is the REAL driver PR1a's own test only illustrated the shape of:
`BackendUnavailable` becomes `trial.finalize(disposition="unavailable")` here
because THIS function's control flow makes that the only path, not because a
test re-implements it.

JOURNAL EVENTS. A backend-driven attempt still writes exactly the events
`trial.py`'s other functions already understand - `dispatched`, `started`,
`stopped`, `stop-confirmed`/`stop-unconfirmed`, `workspace`, `cleaned` - so
`trial.capture()`, `trial.finalize()` and `trial.cleanup_workspace()` all work
UNCHANGED. `trial.allocate_workspace` still allocates the host-owned directory
`trial.capture()` reads; the backend never receives that path itself, it
`export()`s this attempt's output INTO it, after which capture proceeds
exactly as it does for a host-executed subject.

CONFIRMATION, NEVER A GUESS. `backend.confirm_stopped()` returns a
`Confirmation`, and only `Confirmation.CONFIRMED` is ever written into the
journal's `stopped.confirmed` field as `True` - `NOT_CONFIRMED` and `UNKNOWN`
both become `False`. `trial.finalize` already derives `inconclusive` from an
unconfirmed stop, so this one mapping is enough to make an unobservable
backend read exactly like a subject whose stop was never confirmed - never
like a clean one.

`backend.confirm_absent()` (step 9) has no equivalent field in `trial.py`'s
existing lifecycle-record schema, AND `LIFECYCLE_EVENTS` (records.py) is a
closed vocabulary this driver must not widen - "backend-torn-down" is not a
legal journal event, exactly as an unknown frontmatter field is refused
elsewhere in this codebase. Extending that version-2 record contract is out
of scope for this PR (see records.md). So `confirm_absent()`'s `Confirmation`
is carried ONLY in this driver's own return value, under `backend_teardown` -
never written to the journal, so a caller who reads only the lifecycle record
would miss it entirely.

LIVENESS: A NONCE THE BACKEND NEVER SEES IN ADVANCE (issue #10, comment
5848522578 lesson A4, and the addendum comment items 1-2). A trivial canary
("reply OK") proves nothing about whether a skill or a tool actually ran -
measured concretely: `claude -p 'reply OK'` passed while every skill,
command, MCP server and Python interpreter was missing. So this driver mints
a random per-attempt nonce and passes it to `install()` inside `surface`
under `CANARY_NONCE_KEY`. A backend that supports the canary convention
plants that nonce somewhere the subject's real work would have to touch, and
tells the driver where to find the proof afterward via
`readiness["canary_path"]` (a path relative to the exported output). The
driver then requires the exported file at that path to read exactly
`f"touched:{nonce}"` - content the subject could not have produced without
actually reading the planted input, and could not have guessed, since the
nonce is generated fresh per attempt and never appears in the prompt.

A backend that does NOT support the canary convention (declines to set
`canary_path`) falls back to the weaker, fully generic check: `export()` is
called once right after `install()` (before `execute()` runs anything) and
once after, and the two snapshots are compared by content digest. Identical
snapshots mean nothing observable happened, whatever the exit code says. This
fallback exists for a `surface` that legitimately installs nothing (the
"empty task selection" case) and for any future backend that has not wired
the canary convention yet - it does not excuse a real backend from
implementing the canary once it can.

Either way, a failed liveness check finalizes the attempt `inconclusive` with
a `liveness` reason; `trial.capture` is never even called. A client that
answers plausibly without touching the planted canary
(`tests/fixtures/backend-lifecycle/fake_client.py`'s `reply-only` mode) is
the addendum's own extended negative control: it defeats the content-diff
fallback (new prose IS a content change) but not the nonce canary.

STRUCTURALLY UNABLE TO LAUNCH A REAL AGENT (addendum item 51). Every call
into a backend's `execute()` passes first through `_refuse_real_agent`, which
raises `RealAgentBlocked` for `claude` or `codex` as `argv[0]` unless
`SKILLC_ALLOW_REAL_AGENT=1` is set. This is the harness's OWN safety property,
not a backend concern: a test (or an operator's typo) can never spend against
a real subscription through this driver by accident.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from . import trial
from .backend import BackendUnavailable, Confirmation, ExecutionBackend, Limits

#: The key `surface` carries the per-attempt liveness nonce under, passed to
#: `install()`. Never sent in the prompt or any other input the subject reads
#: directly - only a backend that plants it as a canary can make it reappear.
CANARY_NONCE_KEY = "_skillc_liveness_nonce"

REAL_AGENT_BINARIES = frozenset({"claude", "codex"})
ALLOW_REAL_AGENT_ENV = "SKILLC_ALLOW_REAL_AGENT"


class RealAgentBlocked(Exception):
    """Refused: this argv would launch a REAL agent CLI - possibly against a
    paid subscription - with no explicit opt-in (issue #10 addendum item 51:
    "the harness's own test suite must be structurally unable to launch a
    real agent"). Set `SKILLC_ALLOW_REAL_AGENT=1` to opt in deliberately."""


def _refuse_real_agent(argv: Sequence[str]) -> None:
    if not argv:
        return
    name = Path(str(argv[0])).name
    if name in REAL_AGENT_BINARIES and os.environ.get(ALLOW_REAL_AGENT_ENV) != "1":
        raise RealAgentBlocked(
            f"refusing to launch {name!r} without {ALLOW_REAL_AGENT_ENV}=1 - this would run a "
            f"real agent CLI, possibly against a paid subscription (issue #10 addendum item 51)"
        )


def _snapshot(root: Path) -> dict[str, str]:
    """A cheap liveness signature: every regular file's relative path to its
    content digest. Not a security control (unlike `verify.py`'s own
    snapshot, this is never asked to catch a forger) - only asked to catch
    "nothing changed"; the canary check above is the stronger proof when a
    backend supports it."""
    digests: dict[str, str] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = str(path.relative_to(root))
            digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _canary_proof(workspace: Path, canary_path: object, nonce: str) -> bool:
    if not isinstance(canary_path, str) or not canary_path:
        return False
    target = (workspace / canary_path).resolve()
    if not target.is_relative_to(workspace.resolve()) or target.is_symlink() or not target.is_file():
        return False
    return target.read_text(encoding="utf-8", errors="replace") == f"touched:{nonce}"


def _ensure_spool_files(experiment: trial.Experiment, attempt_id: str) -> None:
    """`trial.capture()` unconditionally reads `spool/<attempt_id>.{stdout,stderr}`,
    which `trial.run_attempt` normally creates while redirecting the subject's
    real output into them. This driver never calls `run_attempt` - a backend
    runs the subject inside its own isolation, not as a host subprocess this
    process controls - so nothing has created those files. `ExecutionBackend`
    has no method for a backend to hand its own captured stdio back through
    this exact channel yet (a real backend's stdio becomes an ordinary
    exported artifact today, not the `client-events`/`client-stderr`
    observation streams `run_attempt`-driven attempts get). Creating them
    empty here is the honest interim answer - EMPTY, not absent - not a claim
    that the subject produced no output. Extending the Protocol with a
    stdio-handoff method is future work, out of scope for this PR."""
    spool = experiment.root / trial.SPOOL
    for suffix in ("stdout", "stderr"):
        path = spool / f"{attempt_id}.{suffix}"
        if not path.exists():
            path.touch(mode=trial.FILE_MODE)


def run_through_backend(
    backend: ExecutionBackend,
    experiment: trial.Experiment,
    attempt_id: str,
    argv: Sequence[str],
    surface: Mapping[str, object],
    limits: Limits,
    base: Path,
    forbidden: list[Path] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Drive `attempt_id` through `backend` from prepare to teardown, and
    finalize it. Returns `trial.finalize`'s lifecycle record, plus
    `backend_teardown` (see the module docstring)."""
    _refuse_real_agent(argv)

    try:
        handle = backend.prepare(attempt_id)
    except BackendUnavailable as exc:
        record = trial.finalize(experiment, attempt_id, disposition="unavailable", reason=str(exc))
        return {**record, "backend_teardown": None}

    workspace = trial.allocate_workspace(experiment, attempt_id, base, forbidden or [])
    nonce = secrets.token_hex(16)
    try:
        readiness = backend.install(handle, {**surface, CANARY_NONCE_KEY: nonce})
    except BackendUnavailable as exc:
        # Reachable a moment ago (prepare() succeeded); not reachable now. Not
        # the pre-flight case, but still nothing dispatched - the controller
        # never guesses a cause beyond what the backend reported.
        backend.destroy(handle)
        record = trial.finalize(experiment, attempt_id, disposition="unavailable", reason=str(exc))
        return {**record, "backend_teardown": None, "readiness": None}

    canary_path = readiness.get("canary_path") if isinstance(readiness, dict) else None
    before = None if canary_path else _snapshot_via_export(backend, handle, base / f"{attempt_id}-preexec")

    experiment.record(attempt_id, "dispatched")
    experiment.record(attempt_id, "started")
    result = backend.execute(handle, argv, limits, cancel)
    if result.reason != "exited":
        experiment.record(attempt_id, "stop-requested", reason=result.reason)

    stop_confirmation = backend.confirm_stopped(handle)
    confirmed = stop_confirmation is Confirmation.CONFIRMED
    stop: dict[str, object] = {"reason": result.reason, "confirmed": confirmed, "exit_code": result.exit_code}
    if result.error is not None:
        stop["error"] = result.error
    if result.signal is not None:
        stop["signal"] = result.signal
    experiment.record(attempt_id, "stopped", **stop)
    experiment.record(attempt_id, "stop-confirmed" if confirmed else "stop-unconfirmed")

    if confirmed and result.reason != "launch-failed":
        try:
            backend.export(handle, workspace)
        except OSError as exc:
            experiment.record(attempt_id, "capture-failed", reason=f"export failed: {exc}")
        else:
            live = (
                _canary_proof(workspace, canary_path, nonce) if canary_path
                else _snapshot(workspace) != before
            )
            if not live:
                experiment.record(
                    attempt_id, "capture-failed",
                    reason="liveness: no proof the subject actually ran - "
                           + ("the canary was never touched" if canary_path else
                              "no observable change between install and execute"),
                )
            else:
                _ensure_spool_files(experiment, attempt_id)
                try:
                    trial.capture(experiment, attempt_id)
                except trial.Refused:
                    pass  # capture() already recorded capture-failed; nothing more to add here

    backend.destroy(handle)
    teardown_confirmation = backend.confirm_absent(handle)

    record = trial.finalize(experiment, attempt_id)
    trial.cleanup_workspace(experiment, attempt_id)
    return {
        **record, "backend_teardown": teardown_confirmation.value, "readiness": readiness,
        # trial.finalize's `stop` field is filtered to {reason, confirmed, exit_code}
        # (trial.py's own fixed tuple) - `signal` never survives that filter, even
        # though it IS written to the raw journal event. Surfaced here so a caller
        # is never left guessing a cause from a bare negative exit code (addendum
        # item 12: "exit 137 is SIGKILL, not OOM").
        "signal": result.signal,
    }


def _snapshot_via_export(backend: ExecutionBackend, handle: object, into: Path) -> dict[str, str]:
    """The pre-execution liveness baseline for the content-diff fallback:
    exported through the same `export()` a real capture uses, so the
    comparison is over exactly what a capture would see. `into` is scratch,
    never the attempt's real workspace - nothing here is captured or
    recorded, and it is removed once read."""
    into.mkdir(parents=True, exist_ok=True)
    try:
        backend.export(handle, into)
        return _snapshot(into)
    finally:
        shutil.rmtree(into, ignore_errors=True)
