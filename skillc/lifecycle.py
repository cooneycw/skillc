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
is carried in this driver's own return value, under `backend_teardown`, and
(#127) in the journal as a `backend-teardown` DETAIL event - journal-only,
like `workspace`, so the lifecycle record's schema is unchanged. A caller who
reads only the lifecycle record still misses it; the journal beside it has it.
The image the attempt actually ran in (#12) travels the same way: a
`backend-identity` DETAIL event, written after `install()`, carrying the
backend's reported `image_digest` beside the ledger's planned digest.

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

WHICH METHOD PROVED IT, NEVER LEFT IMPLICIT. A capture that passed through
the weaker content-diff fallback is otherwise indistinguishable, in the
journal and in this driver's return value, from one the nonce canary proved -
yet the `reply-only` control above exists precisely because the fallback is
defeatable. So every attempt that reaches execution records
`liveness_method` (`"canary"` or `"content-diff"`) on the `stopped` journal
event and in the returned record, whether or not it goes on to capture, so a
grader or reader can see which guarantee actually applied rather than assume
the stronger one.

STRUCTURALLY UNABLE TO LAUNCH A REAL AGENT (addendum item 51). Every call
into a backend's `execute()` passes first through `_refuse_real_agent`, which
raises `RealAgentBlocked` when `claude` or `codex` appears ANYWHERE in argv -
not only at `argv[0]` - unless `SKILLC_ALLOW_REAL_AGENT=1` is set. Checking
only `argv[0]` would leave `["/usr/bin/env", "codex"]` or
`["sh", "-c", "claude ..."]` unblocked (found by cross-model review); scanning
the whole argv is not a perfect sandbox either, but it closes the obvious
wrapper bypass rather than checking a position an attacker or a typo would
not need to use. This is the harness's OWN safety property, not a backend
concern: a test (or an operator's typo) must never spend against a real
subscription through this driver by accident - which is also why the tests
for this guard explicitly clear the opt-in variable rather than trust
whatever the ambient environment happens to hold.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from . import trial
from .backend import BackendUnavailable, Confirmation, ExecuteResult, ExecutionBackend, Limits

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


#: Wrappers whose NEXT meaningful argument is the real command, not the
#: wrapper itself - `env codex ...` and `sh -c "codex ..."` both name the
#: agent somewhere other than argv[0].
SHELL_WRAPPERS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
_REAL_AGENT_WORD = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in REAL_AGENT_BINARIES) + r")\b"
)


def _blocked(name: str) -> RealAgentBlocked:
    return RealAgentBlocked(
        f"refusing to launch {name!r} without {ALLOW_REAL_AGENT_ENV}=1 - this would run a real "
        f"agent CLI, possibly against a paid subscription (issue #10 addendum item 51)"
    )


def _refuse_real_agent(argv: Sequence[str]) -> None:
    if os.environ.get(ALLOW_REAL_AGENT_ENV) == "1" or not argv:
        return

    # An exact basename match against EVERY argv element - not just argv[0]
    # (found by cross-model review) - already catches `["codex", ...]` and
    # `["/usr/bin/env", "codex"]` alike, since "codex" is its own distinct
    # element either way. It does NOT false-positive on an ordinary path
    # merely installed under a directory named "claude" or "codex" (measured
    # on this very host: its own home directory), because a basename compares
    # only the final path component, never a substring of the whole path.
    for arg in argv:
        name = Path(str(arg)).name
        if name in REAL_AGENT_BINARIES:
            raise _blocked(name)

    # `sh -c "codex ..."` is the one shape basename matching cannot see: the
    # whole command sits inside ONE argv element as a string with other
    # words. Scoped to exactly the argument right after `-c` for a
    # recognized shell wrapper - never a blanket scan of every argv element,
    # which would reintroduce the false positive above (a path is not a
    # command line, and searching one as if it were finds words that were
    # never a command).
    first = Path(str(argv[0])).name
    if first in SHELL_WRAPPERS and "-c" in argv:
        idx = list(argv).index("-c")
        if idx + 1 < len(argv):
            match = _REAL_AGENT_WORD.search(str(argv[idx + 1]))
            if match:
                raise _blocked(match.group(1))


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
    raw = workspace / canary_path
    # Checked BEFORE resolving: .resolve() follows a symlink chain to its
    # target, so a check made against the resolved path can never see the
    # symlink that got it there - `target.is_symlink()` after `.resolve()`
    # is always False, which is dead code (found by cross-model review). A
    # leaf-level symlink into a real proof file elsewhere must be refused
    # here, before resolution ever runs.
    if raw.is_symlink():
        return False
    target = raw.resolve()
    if not target.is_relative_to(workspace.resolve()) or not target.is_file():
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
    observe_before_teardown: Callable[[ExecutionBackend, object], Mapping[str, object]] | None = None,
    before_execute: Callable[[ExecutionBackend, object], None] | None = None,
    nonce: str | None = None,
) -> dict[str, object]:
    """Drive `attempt_id` through `backend` from prepare to teardown, and
    finalize it. Returns `trial.finalize`'s lifecycle record, plus
    `backend_teardown` and `signal` (see the module docstring).

    `observe_before_teardown` (issue #106) is a GENERIC extension point -
    this module stays subject-agnostic and knows nothing about clients,
    transcripts, or skills. It runs once, after `confirm_stopped()` and
    before `export()`/`destroy()` (so it can read anything that only exists
    while the backend's resources are still alive - e.g. a container's home
    directory, which `export()` structurally cannot reach), and returns a
    `Mapping` recorded VERBATIM under the returned record's `observation`
    key. A hook that RAISES never blocks teardown - the record instead gets
    `{"status": "unknown", "reason": str(exc)}` under that same key, exactly
    like every other unconfirmable fact in this driver (`backend_teardown`
    on a `destroy()`/`confirm_absent()` failure, above). Omitting the
    argument omits the `observation` key from the returned record entirely,
    so every EXISTING caller's record is byte-identical to before this
    parameter existed.

    `before_execute` (issue #106) runs on the OTHER side of the attempt from
    `observe_before_teardown`: once, after `install()` succeeds and before
    the liveness baseline/`execute()`. Same structural motive -
    `install()`'s own `surface` argument can only ever reach
    `CONTAINER_WORKSPACE`, never a backend's home directory, so delivering
    something there (a credential, #98) has no other seam to run from - but
    a DIFFERENT failure semantics, deliberately not symmetric with the
    teardown hook: `observe_before_teardown` failing loses an OBSERVATION,
    so recording it as unknown and continuing to teardown is right.
    `before_execute` failing means the attempt's PRECONDITION was never
    met (the credential was never delivered, say) - letting `execute()` run
    anyway would start the agent without whatever the hook was meant to
    provide and record its no-op or garbage transcript as a genuine
    attempt, exactly the silent failure #78 and #98 both exist to prevent.
    So a raise here BLOCKS the attempt: `execute()` is never called, and
    this reuses the exact same path `install()`'s own `BackendUnavailable`
    already takes - the attempt is finalized `unavailable` with the hook's
    exception as the reason. Teardown (`destroy()`/`confirm_absent()`)
    still happens regardless, unconditionally, in the shared `finally`
    below - cleanup is never contingent on why an attempt was blocked.
    Omitting the argument changes nothing, for the same reason
    `observe_before_teardown`'s omission does.

    `nonce` (issue #106) lets a caller supply the liveness canary's nonce
    itself, rather than one this function mints internally. This exists for
    exactly one reason: a caller composing a REAL agent's prompt (which
    becomes part of `argv`, fixed before this function is ever called) needs
    to embed the SAME nonce the backend will plant, so the agent's own canary
    instruction and `install()`'s backend-planted file-content canary are ONE
    proof, not two independent ones with two different nonces - unifying them
    minimizes prompt contamination in the very behaviour being measured
    (cross-model review). Omitted (the default, every pre-#106 caller),
    a fresh nonce is minted exactly as before.

    TEARDOWN IS UNCONDITIONAL once `prepare()` has returned a handle
    (found by cross-model review: the first version of this function let an
    exception from `install()`, the baseline export, `execute()` or
    `confirm_stopped()` escape before `destroy()`/`confirm_absent()` ever
    ran, which could leave a backend's resources alive with nothing left to
    tear them down). Everything from `install()` onward runs inside a
    `try/finally` whose `finally` always calls `destroy()` and
    `confirm_absent()`, however the body ends - including for a genuinely
    unexpected exception, which still propagates to the caller AFTER
    teardown, never silently swallowed.

    TEARDOWN'S OWN EXCEPTIONS ARE ALSO NEVER ALLOWED TO SKIP ACCOUNTING (#79).
    `destroy()` or `confirm_absent()` raising - not merely returning
    `NOT_CONFIRMED`/`UNKNOWN` - used to propagate straight out of this
    function, so `trial.finalize()`/`trial.cleanup_workspace()` below never
    ran and the attempt was left with no lifecycle record at all, whatever
    the subject itself did. Both calls are now individually caught; a raise
    from either is folded into `backend_teardown="unknown"` (never a guessed
    `confirmed`) plus a `backend_teardown_error` string in the returned
    record, and `trial.finalize()` still runs. A resource this leaves behind
    is exactly what `skillc/reap.py`'s label-scoped sweep exists to find
    later - this driver's own per-attempt teardown and that independent sweep
    are two layers, not one.
    """
    _refuse_real_agent(argv)

    try:
        handle = backend.prepare(attempt_id)
    except BackendUnavailable as exc:
        record = trial.finalize(experiment, attempt_id, disposition="unavailable", reason=str(exc))
        return {
            **record, "backend_teardown": None, "backend_teardown_error": None,
            "readiness": None, "signal": None, "liveness_method": None,
            # #102: no execution was ever attempted (prepare() itself failed),
            # so there is nothing to have truncated - explicit `False`/`None`
            # keeps this dict's schema the same shape as the normal-path
            # return below, matching `signal`'s own existing convention here.
            "observations_truncated": False, "observations_bytes": None,
        }

    workspace = trial.allocate_workspace(experiment, attempt_id, base, forbidden or [])
    nonce = nonce if nonce is not None else secrets.token_hex(16)
    readiness: dict[str, object] | None = None
    result: object = None
    unavailable_reason: str | None = None
    liveness_method: str | None = None
    observation: dict[str, object] | None = None

    try:
        try:
            readiness = backend.install(handle, {**surface, CANARY_NONCE_KEY: nonce})
        except BackendUnavailable as exc:
            # Reachable a moment ago (prepare() succeeded); not reachable now.
            # Not the pre-flight case, but still nothing dispatched - the
            # controller never guesses a cause beyond what the backend
            # reported. Teardown still happens, in the shared `finally` below.
            unavailable_reason = str(exc)
        else:
            _record_identity(experiment, attempt_id, readiness)
            if before_execute is not None:
                try:
                    before_execute(backend, handle)
                except Exception as exc:  # noqa: BLE001 - a pre-execute hook failure blocks the attempt, never a guess
                    # Symmetric to install()'s own BackendUnavailable handling
                    # right above: nothing has been dispatched yet, so this
                    # reuses the SAME "unavailable" path rather than inventing
                    # a second one - teardown still happens, in the shared
                    # `finally` below, exactly as it does for install()'s
                    # failure.
                    unavailable_reason = str(exc)

            if unavailable_reason is None:
                canary_path = readiness.get("canary_path") if isinstance(readiness, dict) else None
                # Recorded whichever path is taken (PR #70 review): a capture
                # that passed the weaker content-diff fallback
                # is otherwise indistinguishable in the journal from one proven
                # by the nonce canary, and the reply-only control shows the
                # fallback alone is defeatable. A reader must be able to see
                # which guarantee this attempt actually got.
                liveness_method = "canary" if canary_path else "content-diff"
                try:
                    before = None if canary_path else _snapshot_via_export(backend, handle, base)
                except OSError:
                    # Cannot establish a baseline; fall back to "empty" rather than
                    # crash. This WEAKENS the content-diff check for this one
                    # attempt (any output at all now reads as "live"), but
                    # trial.capture's own empty-capture rule still refuses a
                    # subject that produces nothing, and a genuinely broken
                    # export() will fail again, loudly, at the real export below.
                    before = {}

                experiment.record(attempt_id, "dispatched")
                experiment.record(attempt_id, "started")
                result = backend.execute(handle, argv, limits, cancel)
                assert isinstance(result, ExecuteResult)
                if result.reason != "exited":
                    experiment.record(attempt_id, "stop-requested", reason=result.reason)

                stop_confirmation = backend.confirm_stopped(handle)
                confirmed = stop_confirmation is Confirmation.CONFIRMED
                stop: dict[str, object] = {
                    "reason": result.reason, "confirmed": confirmed, "exit_code": result.exit_code,
                    "liveness_method": liveness_method,
                }
                if result.error is not None:
                    stop["error"] = result.error
                if result.signal is not None:
                    stop["signal"] = result.signal
                if result.stdout_truncated:
                    # #102: the subject wrote more than the backend retained -
                    # say so explicitly, with the true total, rather than let a
                    # reader of `observations` (the bounded capture itself)
                    # mistake it for the subject's whole output.
                    stop["observations_truncated"] = True
                    stop["observations_bytes"] = result.stdout_bytes
                experiment.record(attempt_id, "stopped", **stop)
                experiment.record(attempt_id, "stop-confirmed" if confirmed else "stop-unconfirmed")

                if observe_before_teardown is not None:
                    try:
                        observation = dict(observe_before_teardown(backend, handle))
                    except Exception as exc:  # noqa: BLE001 - an observation hook must never block teardown
                        observation = {"status": "unknown", "reason": str(exc)}

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
                                pass  # capture() already recorded capture-failed; nothing more here
    finally:
        # TEARDOWN FAILURE IS ITS OWN FAILURE PATH (#79), never a reason to
        # skip accounting. Before this fix, an exception from `destroy()` or
        # `confirm_absent()` propagated straight out of this function -
        # `trial.finalize()`/`trial.cleanup_workspace()` below never ran, and
        # the attempt was left with NO lifecycle record at all, whatever the
        # subject itself did. Neither call is trusted to succeed any more
        # than its own return value already was: both are wrapped so a raise
        # is captured as UNKNOWN (never guessed CONFIRMED, never allowed to
        # skip the finalize below) and surfaced in the returned record - a
        # left-behind resource this leaves for `skillc/reap.py`'s
        # label-scoped sweep to find later, exactly as an unreachable-daemon
        # `Confirmation.UNKNOWN` already does.
        try:
            backend.destroy(handle)
        except Exception as exc:  # noqa: BLE001 - never let teardown skip accounting
            destroy_error: str | None = str(exc)
        else:
            destroy_error = None
        try:
            teardown_confirmation = backend.confirm_absent(handle)
        except Exception as exc:  # noqa: BLE001 - see above
            confirm_absent_error: str | None = str(exc)
            teardown_confirmation = Confirmation.UNKNOWN
        else:
            confirm_absent_error = None
        teardown_errors = [e for e in (destroy_error, confirm_absent_error) if e is not None]
        # Journalled HERE, inside `finally` (#127 review): an unexpected raise
        # from execute() propagates past everything below, and this event is
        # then the only surviving account of whether the container went away.
        experiment.record(
            attempt_id, "backend-teardown", confirmation=teardown_confirmation.value,
            error="; ".join(teardown_errors) if teardown_errors else None,
        )

    # CLEAN BEFORE FINALIZING (#127): finalize() derives the persisted record's
    # `cleanup` from the journal's `cleaned` event, so the reverse order wrote
    # `partial / never cleaned up` on every attempt, whatever cleanup then did.
    trial.cleanup_workspace(experiment, attempt_id)
    if unavailable_reason is not None:
        record = trial.finalize(experiment, attempt_id, disposition="unavailable", reason=unavailable_reason)
    else:
        record = trial.finalize(experiment, attempt_id)
    output: dict[str, object] = {
        **record, "backend_teardown": teardown_confirmation.value,
        "backend_teardown_error": "; ".join(teardown_errors) if teardown_errors else None,
        "readiness": readiness,
        # trial.finalize's `stop` field is filtered to {reason, confirmed, exit_code}
        # (trial.py's own fixed tuple) - `signal` never survives that filter, even
        # though it IS written to the raw journal event. Surfaced here so a caller
        # is never left guessing a cause from a bare negative exit code (addendum
        # item 12: "exit 137 is SIGKILL, not OOM").
        "signal": result.signal if isinstance(result, ExecuteResult) else None,
        # #102, surfaced for the identical reason `signal` is: a subject that
        # wrote more stdout than the backend retained. `observations_bytes`
        # is only meaningful when `observations_truncated` is True.
        "observations_truncated": result.stdout_truncated if isinstance(result, ExecuteResult) else False,
        "observations_bytes": result.stdout_bytes if isinstance(result, ExecuteResult) else None,
        # Which liveness proof this attempt used - "canary" (the nonce
        # convention) or "content-diff" (the weaker fallback) - so a grader
        # or reader can see when only the weaker guarantee applied. None when
        # the attempt never reached execution at all (PR #70 review).
        "liveness_method": liveness_method,
    }
    # Present ONLY when the caller opted in (this function's own docstring) -
    # an omitted argument must leave every existing caller's record
    # byte-identical to before this parameter existed.
    if observe_before_teardown is not None:
        output["observation"] = observation
    return output


def _record_identity(experiment: trial.Experiment, attempt_id: str, readiness: object) -> None:
    """Journal the image this attempt ACTUALLY ran in (#12), beside the digest
    the ledger planned, when the backend reports one (`image_digest` in its
    readiness evidence). `matches_ledger` is `None` whenever either side is
    unknown - an unresolved digest is never read as a match or a mismatch.
    A backend that does not report `image_digest` at all writes nothing:
    absence of the key says this backend makes no such claim."""
    if not isinstance(readiness, dict) or "image_digest" not in readiness:
        return
    ran = readiness["image_digest"]
    image = experiment.trial_of(attempt_id).get("image")
    planned = image.get("digest") if isinstance(image, dict) else None
    known = isinstance(ran, str) and isinstance(planned, str) and planned.startswith("sha256:")
    experiment.record(
        attempt_id, "backend-identity", image_digest=ran, ledger_image_digest=planned,
        matches_ledger=(ran == planned) if known else None,
    )


def _snapshot_via_export(backend: ExecutionBackend, handle: object, base: Path) -> dict[str, str]:
    """The pre-execution liveness baseline for the content-diff fallback:
    exported through the same `export()` a real capture uses, so the
    comparison is over exactly what a capture would see. Scratch, never the
    attempt's real workspace - nothing here is captured or recorded, and it
    is removed once read.

    `tempfile.mkdtemp`, not a deterministic `<attempt_id>-preexec` path
    (found by cross-model review): a deterministic path can already exist -
    from a stale run, or anything else - and `mkdir(exist_ok=True)` would
    silently adopt it, folding its contents into the baseline and then
    `rmtree`-ing something this call never created. `mkdtemp` is exclusively
    created and impossible to collide with an existing directory."""
    into = Path(tempfile.mkdtemp(dir=base))
    try:
        backend.export(handle, into)
        return _snapshot(into)
    finally:
        shutil.rmtree(into, ignore_errors=True)
