"""Tests for the lifecycle driver over the execution backend seam (#10, PR1b).

Every scenario here runs through `lifecycle.run_through_backend` - the REAL
driver, never a test-local reimplementation - against `FakeBackend`, which
runs the subject as an ordinary host subprocess and says so in `describe()`'s
`unobserved` claim: it proves the LIFECYCLE state machine and the record for
every path, never a containment boundary. That is the live daemon run's job
(interfaces.md's "Liveness" note and issue #10 comment 5848522578, lesson E17).

`test_liveness_catches_a_noop_client_that_exits_zero` is the committed
negative control for lesson A4: it also proves the check is not vacuous by
showing what happens with the liveness comparison bypassed.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from skillc import lifecycle
from skillc import trial as t
from skillc.backend import (
    BackendDescription,
    BackendUnavailable,
    Confirmation,
    ExecuteResult,
    Limits,
)

FAKE_CLIENT = Path(__file__).resolve().parent / "fixtures" / "backend-lifecycle" / "fake_client.py"


@dataclass
class _Handle:
    attempt_id: str
    root: Path
    proc: subprocess.Popen[bytes] | None = None


class FakeBackend:
    """Runs argv as a real host subprocess - proves the LIFECYCLE, never a
    containment boundary (see `describe()`'s `unobserved` claim). Constructor
    keywords inject each of PR1b's named failure paths."""

    def __init__(
        self,
        base: Path,
        *,
        unavailable: bool = False,
        install_unavailable: bool = False,
        export_fails: bool = False,
        export_fails_once: bool = False,
        raise_in_execute: bool = False,
        force_confirm_stopped: Confirmation | None = None,
        force_confirm_absent: Confirmation | None = None,
        supports_canary: bool = True,
        destroy_raises: bool = False,
        confirm_absent_raises: bool = False,
        force_stdout_truncated: int | None = None,
        image_digest: object = None,
        reports_image: bool = False,
    ) -> None:
        self._base = base
        #: `reports_image` adds `image_digest` to install()'s readiness (#12),
        #: as DockerBackend does; off, the key is absent - a backend making no
        #: claim about its image at all.
        self._image_digest = image_digest
        self._reports_image = reports_image
        self._unavailable = unavailable
        self._install_unavailable = install_unavailable
        self._export_fails = export_fails
        self._export_fails_once = export_fails_once
        self._raise_in_execute = raise_in_execute
        self._destroy_raises = destroy_raises
        self._confirm_absent_raises = confirm_absent_raises
        self._force_confirm_stopped = force_confirm_stopped
        self._force_confirm_absent = force_confirm_absent
        self._supports_canary = supports_canary
        #: When set, `execute()` reports this many TOTAL stdout bytes with
        #: `stdout_truncated=True` (#102) - a real backend's own bounded
        #: drain is `DockerBackend`'s to prove; this fake only needs to prove
        #: `lifecycle.run_through_backend` surfaces the result faithfully.
        self._force_stdout_truncated = force_stdout_truncated
        self.destroyed: set[str] = set()
        self.export_calls = 0

    def describe(self) -> BackendDescription:
        return BackendDescription(
            name="fake-lifecycle", version="0", isolation=(),
            unobserved=("containment - runs as a host subprocess; proves the lifecycle, never a boundary",),
        )

    def prepare(self, attempt_id: str) -> object:
        if self._unavailable:
            raise BackendUnavailable("fake backend forced unavailable")
        root = self._base / f"handle-{attempt_id}"
        root.mkdir(parents=True)
        return _Handle(attempt_id=attempt_id, root=root)

    def install(self, handle: object, surface: Mapping[str, object]) -> dict[str, object]:
        """Leaves a scaffold file behind, like a real skill installation would,
        and - when anything was actually declared - plants the liveness
        canary (lifecycle.CANARY_NONCE_KEY) at `.skillc-canary` and tells the
        driver where to look for proof it was touched. This demonstrates the
        addendum's nonce-canary convention (issue #10 comment 5848522578,
        items 1-2), not just the weaker content-diff fallback."""
        assert isinstance(handle, _Handle)
        if self._install_unavailable:
            raise BackendUnavailable("fake backend install refused")
        nonce = surface.get(lifecycle.CANARY_NONCE_KEY)
        declared = {k: v for k, v in surface.items() if k != lifecycle.CANARY_NONCE_KEY}
        if not declared:
            return {"discovery_canary": "VIOLATED", "baseline_absence": "SATISFIED", "declared": 0}
        (handle.root / "skill-scaffold.txt").write_text("installed skill scaffolding\n")
        readiness: dict[str, object] = {
            "discovery_canary": "SATISFIED", "baseline_absence": "SATISFIED", "declared": len(declared),
        }
        if self._supports_canary and isinstance(nonce, str):
            (handle.root / ".skillc-canary").write_text(nonce)
            readiness["canary_path"] = ".skillc-canary-result"
        if self._reports_image:
            readiness["image_digest"] = self._image_digest
        return readiness

    def exec_in_attempt(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
        cwd: str | None = None, env: object = None,
    ) -> ExecuteResult:
        """#269 added this to the `ExecutionBackend` Protocol; the lifecycle
        driver this fake exercises never calls it - unsupported here,
        satisfied only for structural typing."""
        del handle, argv, limits, cancel, stdin, cwd, env
        return ExecuteResult(reason="unsupported", exit_code=None)

    def resolve_realpath_in_attempt(self, handle: object, path: str, timeout: float = 2.0) -> str | None:
        """#332 added this to the Protocol; the lifecycle driver this fake
        exercises never calls it - `None` unconditionally, satisfied only
        for structural typing."""
        del handle, path, timeout
        return None

    def execute(
        self, handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
    ) -> ExecuteResult:
        assert isinstance(handle, _Handle)
        if self._raise_in_execute:
            raise RuntimeError("fake backend execute() crashed unexpectedly")
        try:
            proc = subprocess.Popen(
                list(argv), cwd=handle.root, env={"PATH": os.environ.get("PATH", os.defpath)},
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
        except OSError as exc:
            return ExecuteResult(reason="launch-failed", exit_code=None, error=str(exc))
        handle.proc = proc
        deadline = time.monotonic() + limits.timeout
        reason = "exited"
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            if cancel is not None and cancel():
                reason = "operator-cancelled"
                break
            time.sleep(0.02)
        if reason != "exited":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=limits.grace)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
        else:
            proc.wait()
        code = proc.returncode
        # A negative returncode IS the signal, per Python's own convention -
        # translate it to a name rather than let a caller guess a cause from
        # the number (issue #10 addendum item 12: "exit 137 is SIGKILL, not
        # OOM"). A real Docker backend gets this from the shell's 128+signal
        # convention or `.State`, but the discipline (name it, never guess) is
        # the same either way.
        signal_name = signal.Signals(-code).name if code is not None and code < 0 else None
        if self._force_stdout_truncated is not None:
            return ExecuteResult(
                reason=reason, exit_code=code, signal=signal_name,
                stdout_truncated=True, stdout_bytes=self._force_stdout_truncated,
            )
        return ExecuteResult(reason=reason, exit_code=code, signal=signal_name)

    def confirm_stopped(self, handle: object) -> Confirmation:
        assert isinstance(handle, _Handle)
        if self._force_confirm_stopped is not None:
            return self._force_confirm_stopped
        if handle.proc is None:
            return Confirmation.UNKNOWN
        return Confirmation.CONFIRMED if handle.proc.poll() is not None else Confirmation.NOT_CONFIRMED

    def export(self, handle: object, dest: Path) -> None:
        assert isinstance(handle, _Handle)
        self.export_calls += 1
        if self._export_fails:
            raise OSError("fake backend export forced to fail")
        if self._export_fails_once and self.export_calls == 1:
            raise OSError("fake backend export forced to fail on its first call (the baseline)")
        for item in handle.root.iterdir():
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)

    def destroy(self, handle: object) -> None:
        assert isinstance(handle, _Handle)
        if self._destroy_raises:
            raise RuntimeError("fake backend destroy() crashed unexpectedly")
        shutil.rmtree(handle.root, ignore_errors=True)
        self.destroyed.add(handle.attempt_id)

    def confirm_absent(self, handle: object) -> Confirmation:
        assert isinstance(handle, _Handle)
        if self._confirm_absent_raises:
            raise RuntimeError("fake backend confirm_absent() crashed unexpectedly")
        if self._force_confirm_absent is not None:
            return self._force_confirm_absent
        return Confirmation.NOT_CONFIRMED if handle.root.exists() else Confirmation.CONFIRMED


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return t.open_store(tmp_path / "store", forbidden=[])


@pytest.fixture
def base(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


def _planned(store: Path) -> tuple[t.Experiment, str]:
    spec: dict[str, object] = {
        "experiment": "lifecycle",
        "trials": [{
            "label": "t", "case": {"id": "c", "revision": "r1"}, "grader": {"id": "g", "revision": "g1"},
            "subject": {"digest": "sha256:00"}, "client": {"name": "fake", "version": "1"},
            "image": {"digest": "sha256:01"}, "config": {}, "attempts": 1,
        }],
    }
    experiment = t.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    return experiment, str(attempt["attempt_id"])


def _identity_events(experiment: t.Experiment, attempt_id: str) -> list[dict[str, object]]:
    return [e for e in experiment.events(attempt_id) if e.get("event") == "backend-identity"]


def _argv(mode: str) -> list[str]:
    return [sys.executable, str(FAKE_CLIENT), mode]


def _stop(record: dict[str, object]) -> dict[str, object]:
    """`record["stop"]` (trial.finalize's own field), filtered to
    `{reason, confirmed, exit_code}` by trial.py's fixed tuple - fields this
    driver adds, like `signal` or `liveness_method`, never survive it."""
    stop = record["stop"]
    assert isinstance(stop, dict)
    return stop


def _normalize_timestamps(value: object) -> object:
    """Strip wall-clock timestamp values (the journal's own `"at"` field)
    recursively, so two otherwise-identical records from two SEPARATE
    attempts can be compared for equality without every comparison failing
    on nothing but when each one happened to run."""
    if isinstance(value, dict):
        return {k: ("<at>" if k == "at" else _normalize_timestamps(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_timestamps(v) for v in value]
    return value


def _journaled_stopped_event(experiment: t.Experiment, attempt_id: str) -> dict[str, object]:
    """The RAW `stopped` journal event, unfiltered - where `signal` and
    `liveness_method` actually live once written (see `_stop` above)."""
    stopped = [e for e in experiment.events(attempt_id) if e.get("event") == "stopped"]
    assert stopped
    return stopped[-1]


def test_success_is_captured_and_teardown_confirmed(store: Path, base: Path) -> None:
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured"
    assert record["backend_teardown"] == "confirmed"
    assert attempt_id in backend.destroyed
    assert record["liveness_method"] == "canary"
    assert _journaled_stopped_event(experiment, attempt_id)["liveness_method"] == "canary"


def test_liveness_method_is_recorded_on_the_content_diff_path_too(store: Path, base: Path) -> None:
    """PR #70 review: a capture that passed the weaker
    content-diff fallback must not be indistinguishable, in the record, from
    one the nonce canary proved."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, supports_canary=False)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured"
    assert record["liveness_method"] == "content-diff"
    assert _journaled_stopped_event(experiment, attempt_id)["liveness_method"] == "content-diff"


def test_semantic_failure_still_captures_a_nonzero_exit(store: Path, base: Path) -> None:
    """The subject ran and produced output, but exited nonzero - still a
    captured attempt. Whether it PASSES is verify.py's question, not this
    driver's (protocol.md; capture.md's disposition table)."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("fail"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured"
    assert _stop(record)["exit_code"] == 1


def test_a_timeout_is_captured_not_omitted(store: Path, base: Path) -> None:
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("hang"), {"skill": "x"}, Limits(timeout=0.3, grace=0.5), base,
    )
    assert record["disposition"] == "captured"
    assert _stop(record)["reason"] == "timeout"


def test_an_operator_cancellation_is_captured_and_reported(store: Path, base: Path) -> None:
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    # A short head start before cancelling, not an immediate `lambda: True`:
    # the fake client needs a moment to touch its canary and write output
    # before the driver tears it down, or this test would measure a startup
    # race instead of a cancellation.
    deadline = time.monotonic() + 0.15
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("hang"), {"skill": "x"}, Limits(timeout=5, grace=0.5), base,
        cancel=lambda: time.monotonic() > deadline,
    )
    assert record["disposition"] == "captured"
    assert _stop(record)["reason"] == "operator-cancelled"


def test_provider_unavailable_before_dispatch_is_unavailable(store: Path, base: Path) -> None:
    """The structural property PR1a's test only illustrated - earned here
    against the REAL driver."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, unavailable=True)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "unavailable"
    events = [e.get("event") for e in experiment.events(attempt_id)]
    assert "dispatched" not in events


def test_install_failure_is_unavailable_and_still_tears_down(store: Path, base: Path) -> None:
    """Cross-model review: the first version of this path called destroy()
    but skipped confirm_absent() and workspace cleanup, inconsistent with
    every other path's teardown discipline. Both now run through the shared
    `finally`."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, install_unavailable=True)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "unavailable"
    events = [e.get("event") for e in experiment.events(attempt_id)]
    assert "dispatched" not in events
    assert attempt_id in backend.destroyed, "a failed install must still be torn down"
    assert record["backend_teardown"] == "confirmed"
    cleaned = [e for e in experiment.events(attempt_id) if e.get("event") == "cleaned"]
    assert cleaned, "the allocated workspace must still be cleaned up, not merely the backend handle"


def test_export_failure_is_inconclusive_with_its_own_reason(store: Path, base: Path) -> None:
    """C10: export before destroy, and export failure is its own disposition
    reason, distinct from other capture failures."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, export_fails=True)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "inconclusive"
    assert "export failed" in str(record["reason"])
    assert attempt_id in backend.destroyed, "a failed real export must still tear the backend down"


def test_baseline_export_failure_does_not_crash_the_driver(store: Path, base: Path) -> None:
    """Cross-model review: the pre-execution baseline export (used by the
    content-diff fallback) ran outside any error handler in the first version
    - an OSError there escaped uncaught, skipping finalize/destroy/cleanup
    entirely. It now degrades to an empty baseline instead, and the attempt
    still completes and tears down normally."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, supports_canary=False, export_fails_once=True)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured", (
        "an empty baseline still correctly reads 'work' mode's real output as live"
    )
    assert attempt_id in backend.destroyed


def test_an_unexpected_exception_in_execute_still_tears_down(store: Path, base: Path) -> None:
    """Cross-model review: a backend that raises something other than
    BackendUnavailable or OSError (a genuine bug, not a modelled failure path)
    must not leak its resources. The exception still propagates - it is not
    silently swallowed - but destroy()/confirm_absent() run first."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, raise_in_execute=True)
    with pytest.raises(RuntimeError, match="crashed unexpectedly"):
        lifecycle.run_through_backend(
            backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
        )
    assert attempt_id in backend.destroyed, "teardown must run even when execute() raises unexpectedly"
    # #127 review: the teardown outcome is journalled on this path too, where
    # no return value exists to carry it.
    teardown = [e for e in experiment.events(attempt_id) if e.get("event") == "backend-teardown"]
    assert [e["confirmation"] for e in teardown] == ["confirmed"]


def test_an_empty_surface_still_completes_with_readiness_reflecting_it(store: Path, base: Path) -> None:
    """PR1b's reading of "empty task selection": nothing was declared to
    install. The driver does not crash or silently treat it as ready - the
    readiness evidence install() returned says so, for a later grading pass
    to read."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {}, Limits(timeout=5), base,
    )
    assert record["readiness"] == {"discovery_canary": "VIOLATED", "baseline_absence": "SATISFIED", "declared": 0}
    assert record["disposition"] == "captured"  # installation readiness is verify.py's gate, not this driver's


def test_teardown_not_confirmed_is_recorded_never_as_clean(store: Path, base: Path) -> None:
    """confirm_absent()'s Confirmation has no field in trial.py's lifecycle
    record (LIFECYCLE_EVENTS is a closed vocabulary this driver must not
    widen - see the module docstring), so this driver's own return value is
    the only place a caller can see it. It must never read as clean when it
    is not."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, force_confirm_absent=Confirmation.NOT_CONFIRMED)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["backend_teardown"] == "not-confirmed"


def test_a_destroy_exception_still_finalizes_the_attempt(store: Path, base: Path) -> None:
    """Teardown failure (#79): before this fix, `destroy()` raising propagated
    straight out of `run_through_backend` - `trial.finalize()` never ran, and
    the attempt was left with NO lifecycle record at all. Confirmed to
    reproduce on the pre-fix code before this test was written."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, destroy_raises=True)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured"
    # destroy() raised before it could remove the handle's root, so the
    # still-independent confirm_absent() call correctly reports NOT_CONFIRMED
    # (the resource really is still there) rather than a guessed CONFIRMED -
    # confirm_absent() is never skipped just because destroy() itself raised.
    assert record["backend_teardown"] == "not-confirmed"
    assert "crashed unexpectedly" in str(record["backend_teardown_error"])


def test_a_confirm_absent_exception_still_finalizes_the_attempt(store: Path, base: Path) -> None:
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, confirm_absent_raises=True)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured"
    assert record["backend_teardown"] == "unknown"
    assert "crashed unexpectedly" in str(record["backend_teardown_error"])
    # destroy() itself still ran and was not skipped by confirm_absent()'s own raise.
    assert attempt_id in backend.destroyed


def test_teardown_success_reports_no_error(store: Path, base: Path) -> None:
    """The new `backend_teardown_error` field is `None` on the ordinary path,
    not merely absent - a consumer checking it need not guess between
    "no error" and "field doesn't exist"."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["backend_teardown"] == "confirmed"
    assert record["backend_teardown_error"] is None


def _persisted_lifecycle(experiment: t.Experiment, attempt_id: str) -> dict[str, object]:
    """The lifecycle record AS WRITTEN TO THE STORE - what a later reader
    consults - never the driver's in-memory return value."""
    import json

    return json.loads((experiment.root / f"lifecycle-{attempt_id}.json").read_text(encoding="utf-8"))


def test_the_persisted_record_reports_the_workspace_cleanup_that_happened(store: Path, base: Path) -> None:
    """#127: `run_through_backend` finalized BEFORE `cleanup_workspace()`, so
    the persisted record said `partial / the workspace was never cleaned up`
    on every backend attempt - including #11's live PASS runs, whose journals
    said `removed`. Red on the pre-fix order."""
    experiment, attempt_id = _planned(store)
    record = lifecycle.run_through_backend(
        FakeBackend(base), experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured"
    assert _persisted_lifecycle(experiment, attempt_id)["cleanup"] == {"status": "removed", "failures": []}
    assert record["cleanup"] == {"status": "removed", "failures": []}


def test_the_persisted_record_still_reports_a_real_cleanup_failure(
    store: Path, base: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other verdict: a cleanup that fails must still land in the persisted
    record, not be papered over by the reordering."""
    def failing_remove(path: Path, nonce: str) -> dict[str, object]:
        return {"status": "partial", "errors": ["planted: could not remove"]}

    monkeypatch.setattr(t, "remove_owned", failing_remove)
    experiment, attempt_id = _planned(store)
    lifecycle.run_through_backend(
        FakeBackend(base), experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert _persisted_lifecycle(experiment, attempt_id)["cleanup"] == {
        "status": "partial", "failures": ["planted: could not remove"],
    }


def _teardown_events(experiment: t.Experiment, attempt_id: str) -> list[dict[str, object]]:
    return [e for e in experiment.events(attempt_id) if e.get("event") == "backend-teardown"]


def test_container_teardown_is_journalled(store: Path, base: Path) -> None:
    """#127: `confirm_absent()`'s outcome lived only in the return value, so a
    reader of the store could not tell whether the container was removed."""
    experiment, attempt_id = _planned(store)
    lifecycle.run_through_backend(
        FakeBackend(base), experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    [event] = _teardown_events(experiment, attempt_id)
    assert event["confirmation"] == "confirmed"
    assert event["error"] is None


def test_an_unconfirmed_container_teardown_is_journalled_as_unknown(store: Path, base: Path) -> None:
    experiment, attempt_id = _planned(store)
    lifecycle.run_through_backend(
        FakeBackend(base, confirm_absent_raises=True), experiment, attempt_id, _argv("work"),
        {"skill": "x"}, Limits(timeout=5), base,
    )
    [event] = _teardown_events(experiment, attempt_id)
    assert event["confirmation"] == "unknown"
    assert "crashed unexpectedly" in str(event["error"])


def test_launch_failed_is_unavailable(store: Path, base: Path) -> None:
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, ["this-command-does-not-exist-xyz"], {"skill": "x"},
        Limits(timeout=5), base,
    )
    assert record["disposition"] == "unavailable"


def test_liveness_canary_catches_a_noop_client_that_exits_zero(store: Path, base: Path) -> None:
    """The committed negative control for lesson A4 (issue #10 comment
    5848522578): a client that exits 0 having done nothing must never read as
    captured. This exercises the CANARY path (the default; FakeBackend
    supports it whenever anything is declared)."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("noop"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "inconclusive"
    assert "liveness" in str(record["reason"])


def test_liveness_canary_check_is_not_vacuous(store: Path, base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The redcase for the redcase. `install()` leaves a scaffold file behind
    (like a real skill installation would), so the noop client's capture is
    NONEMPTY - trial.capture()'s own pre-existing empty-capture rule cannot
    catch it; only the canary can. With `_canary_proof` forced to always say
    "touched", the same noop client the test above correctly refuses is
    wrongly reported CAPTURED - proving the canary check, not some
    coincidental other rule, is what makes that test pass."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    monkeypatch.setattr(lifecycle, "_canary_proof", lambda workspace, canary_path, nonce: True)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("noop"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured", (
        "with the canary check disabled, a client that did nothing is wrongly captured "
        "as if it had run - exactly what lesson A4 warns must never happen"
    )


def test_liveness_content_diff_fallback_catches_a_noop_when_canary_unsupported(store: Path, base: Path) -> None:
    """A backend that has not wired the canary convention (`canary_path` is
    never set) falls back to the weaker content-diff comparison. This is the
    fallback's own coverage, distinct from the canary's."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, supports_canary=False)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("noop"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "inconclusive"
    assert "liveness" in str(record["reason"])


def test_reply_only_defeats_the_fallback_but_not_the_canary(store: Path, base: Path) -> None:
    """The addendum's own point (issue #10 comment 5848522578, items 1-2): a
    client that answers plausibly without touching the actual skill/tool
    defeats a bare content-diff check (new prose IS a content change) but
    must not defeat the nonce canary."""
    experiment, attempt_id = _planned(store)

    fallback_only = FakeBackend(base, supports_canary=False)
    fooled = lifecycle.run_through_backend(
        fallback_only, experiment, attempt_id, _argv("reply-only"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert fooled["disposition"] == "captured", (
        "demonstrates the weakness the addendum names: a content-diff-only check is "
        "fooled by plausible prose that never touched the skill"
    )

    experiment2, attempt_id2 = _planned(store)
    canary_backend = FakeBackend(base)
    caught = lifecycle.run_through_backend(
        canary_backend, experiment2, attempt_id2, _argv("reply-only"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert caught["disposition"] == "inconclusive"
    assert "liveness" in str(caught["reason"]), "the canary must catch what the fallback alone cannot"


def test_the_protocol_runtime_check_passes_for_fake_backend(base: Path) -> None:
    from skillc.backend import ExecutionBackend
    assert isinstance(FakeBackend(base), ExecutionBackend)


def test_a_signal_kill_records_the_signal_name_not_a_guess(store: Path, base: Path) -> None:
    """Issue #10 addendum item 12: exit 137 is SIGKILL, not OOM - record the
    signal, never a guessed cause. A short timeout against `hang` mode forces
    the driver's own TERM escalation, delivering a REAL signal FakeBackend
    must translate by name, not by a hard-coded assumption."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("hang"), {"skill": "x"}, Limits(timeout=0.3, grace=0.5), base,
    )
    stop = record["stop"]
    assert isinstance(stop, dict)
    assert stop["exit_code"] is not None and stop["exit_code"] < 0
    # trial.finalize's `stop` field is filtered to a fixed key set and drops
    # `signal` even though it is written to the raw journal event - this
    # driver surfaces it separately so a caller is never left guessing.
    assert record["signal"] == "SIGTERM"


def test_truncated_stdout_is_surfaced_on_the_record_not_only_the_journal(store: Path, base: Path) -> None:
    """#102: a backend that had to bound its captured stdout must have that
    fact survive into the RECORD a caller actually reads, not only the raw
    journal event - the same gap `signal` (above) already closes for a kill
    cause, now closed for a truncated capture too."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base, force_stdout_truncated=200_000)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    stop = record["stop"]
    assert isinstance(stop, dict)
    # trial.finalize's own fixed key set would drop this too, exactly like
    # `signal` - surfaced separately for the identical reason.
    assert record["observations_truncated"] is True
    assert record["observations_bytes"] == 200_000


def test_untruncated_stdout_reports_no_truncation_on_the_record(store: Path, base: Path) -> None:
    """Green case beside the red one: an ordinary attempt must not report
    truncation - proves the field is not simply always set."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["observations_truncated"] is False


def test_real_agent_binaries_are_blocked_without_explicit_opt_in(
    store: Path, base: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #10 addendum item 51: the harness's own test suite must be
    structurally unable to launch a real agent. Nothing is even prepared -
    the refusal fires before any backend call, so no attempt is dispatched
    and nothing here could ever spend against a real subscription."""
    monkeypatch.delenv(lifecycle.ALLOW_REAL_AGENT_ENV, raising=False)
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    with pytest.raises(lifecycle.RealAgentBlocked):
        lifecycle.run_through_backend(
            backend, experiment, attempt_id, ["claude", "-p", "do the task"], {"skill": "x"},
            Limits(timeout=5), base,
        )
    events = [e.get("event") for e in experiment.events(attempt_id)]
    assert "dispatched" not in events


@pytest.mark.parametrize("name", ["claude", "codex"])
def test_real_agent_binaries_are_named_explicitly(
    name: str, store: Path, base: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicitly cleared, never inherited (cross-model review): if the
    ambient environment already carries SKILLC_ALLOW_REAL_AGENT=1 - a leftover
    from an unrelated manual run - this test must still exercise the BLOCKED
    path, not silently attempt a real launch because the opt-in happened to
    already be set."""
    monkeypatch.delenv(lifecycle.ALLOW_REAL_AGENT_ENV, raising=False)
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    with pytest.raises(lifecycle.RealAgentBlocked, match=name):
        lifecycle.run_through_backend(
            backend, experiment, attempt_id, [name], {"skill": "x"}, Limits(timeout=5), base,
        )


@pytest.mark.parametrize("argv", [["/usr/bin/env", "codex"], ["sh", "-c", "claude --whatever"]])
def test_real_agent_wrapper_bypasses_are_blocked(
    argv: list[str], store: Path, base: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-model review: checking only argv[0] left `env`/`sh -c` wrappers
    unblocked. The guard scans the whole argv, not just its first element."""
    monkeypatch.delenv(lifecycle.ALLOW_REAL_AGENT_ENV, raising=False)
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    with pytest.raises(lifecycle.RealAgentBlocked):
        lifecycle.run_through_backend(
            backend, experiment, attempt_id, argv, {"skill": "x"}, Limits(timeout=5), base,
        )


def test_a_path_merely_containing_the_word_claude_is_not_blocked() -> None:
    """The negative case for the fix above: an early version scanned every
    argv element for the whole word "claude"/"codex" anywhere in its text,
    which false-positived on a real interpreter path measured during this
    PR's own review - a host whose account name happened to be "claude" made
    `_refuse_real_agent` refuse every single test in this file, since
    `sys.executable` resolved under it. A path is not a command line; only an
    exact basename, or the argument right after a shell's `-c`, may trigger
    the guard. The account name here is a placeholder, not this host's."""
    account_flavoured_path = "/home/some-claude-shaped-account/.venv/bin/python3"
    lifecycle._refuse_real_agent([account_flavoured_path, "-c", "print('hi')"])  # must not raise


def test_real_agent_binaries_proceed_with_explicit_opt_in(
    store: Path, base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The opt-in exists for a deliberate, explicit run - never for a test to
    reach for casually. This test proves only that the gate can be opened on
    purpose, using a harmless stand-in named `codex`, never a real CLI."""
    monkeypatch.setenv(lifecycle.ALLOW_REAL_AGENT_ENV, "1")
    fake_as_codex = tmp_path / "codex"
    fake_as_codex.write_text("#!/usr/bin/env python3\n" + FAKE_CLIENT.read_text(encoding="utf-8"))
    fake_as_codex.chmod(0o700)
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, [str(fake_as_codex), "work"], {"skill": "x"}, Limits(timeout=5), base,
    )
    assert record["disposition"] == "captured"


# ------------------------------------------------------- _canary_proof edge cases


def test_canary_proof_accepts_a_correct_plain_file(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("touched:abc123")
    assert lifecycle._canary_proof(tmp_path, "result.txt", "abc123") is True


def test_canary_proof_rejects_a_stale_nonce_from_another_attempt(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("touched:some-other-attempts-nonce")
    assert lifecycle._canary_proof(tmp_path, "result.txt", "abc123") is False


def test_canary_proof_rejects_a_missing_file(tmp_path: Path) -> None:
    assert lifecycle._canary_proof(tmp_path, "never-written.txt", "abc123") is False


def test_canary_proof_rejects_a_leaf_symlink_to_a_valid_proof(tmp_path: Path) -> None:
    """Cross-model review: `.resolve()` follows a symlink chain, so checking
    `is_symlink()` AFTER resolving can never see the symlink that got there -
    that check was dead code. A symlink at the leaf must be refused even when
    it points at a file that would otherwise pass."""
    real = tmp_path / "real-result.txt"
    real.write_text("touched:abc123")
    link = tmp_path / "result.txt"
    link.symlink_to(real)
    assert lifecycle._canary_proof(tmp_path, "result.txt", "abc123") is False


def test_canary_proof_rejects_a_path_that_escapes_the_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-result.txt"
    outside.write_text("touched:abc123")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    try:
        assert lifecycle._canary_proof(workspace, "../outside-result.txt", "abc123") is False
    finally:
        outside.unlink()


def test_canary_proof_rejects_a_non_string_path(tmp_path: Path) -> None:
    assert lifecycle._canary_proof(tmp_path, None, "abc123") is False
    assert lifecycle._canary_proof(tmp_path, "", "abc123") is False


# --------------------------------------- observe_before_teardown (#106)

def test_no_hook_leaves_the_record_byte_identical(store: Path, base: Path) -> None:
    """Control (#106's own acceptance): a hook of `None` (the default -
    every existing caller) changes nothing. `observation` must be ABSENT
    from the record, not merely `None`, so an existing caller's record is
    byte-identical to before this parameter existed."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert "observation" not in record


def test_a_successful_hook_result_is_recorded_verbatim(store: Path, base: Path) -> None:
    """Control (#106's own acceptance): the hook's own returned mapping is
    recorded under the record's `observation` key, unchanged."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    seen: list[tuple[object, object]] = []

    def hook(be: object, handle: object) -> dict[str, object]:
        seen.append((be, handle))
        return {"transcript_found": True, "skill": "demo-skill"}

    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
        observe_before_teardown=hook,
    )
    assert record["observation"] == {"transcript_found": True, "skill": "demo-skill"}
    assert seen and seen[0][0] is backend


def test_a_raising_hook_is_recorded_as_unknown_and_teardown_still_runs(store: Path, base: Path) -> None:
    """Control (#106's own acceptance): a hook that raises must never block
    teardown - `destroy()`/`confirm_absent()` must still run, and the
    record must show the observation as unknown with the hook's own
    reason, never crash the whole attempt."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)

    def hook(be: object, handle: object) -> dict[str, object]:
        raise RuntimeError("could not read the transcript back")

    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
        observe_before_teardown=hook,
    )
    assert record["observation"] == {"status": "unknown", "reason": "could not read the transcript back"}
    assert record["backend_teardown"] == "confirmed"
    assert attempt_id in backend.destroyed


def test_the_hook_runs_before_destroy_not_after(store: Path, base: Path) -> None:
    """The hook is meant to read state (e.g. a container's home directory)
    that only exists while the backend's resources are still alive - it
    must run BEFORE destroy(), never after."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    order: list[str] = []
    real_destroy = backend.destroy

    def tracking_destroy(handle: object) -> None:
        order.append("destroy")
        real_destroy(handle)

    backend.destroy = tracking_destroy  # type: ignore[method-assign]

    def hook(be: object, handle: object) -> dict[str, object]:
        order.append("hook")
        return {}

    lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
        observe_before_teardown=hook,
    )
    assert order == ["hook", "destroy"]


# ------------------------------------------------- before_execute (#106)

def test_no_before_execute_hook_changes_nothing(store: Path, base: Path) -> None:
    """Control (#106's own acceptance): a hook of `None` (the default -
    every existing caller) changes nothing.

    Cross-model review: comparing two calls that BOTH omit `before_execute`
    only proves the function is deterministic, not that adding the
    parameter changed nothing - and checking four cherry-picked fields lets
    a regression in any OTHER field pass silently. This instead compares an
    omitted argument against an EXPLICIT `before_execute=None` (the two
    ways an existing caller's code could read after this parameter was
    added) over the ENTIRE returned record, normalizing only `attempt_id`
    (the one field that legitimately differs between two separately
    planned attempts)."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    omitted = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    experiment2, attempt_id2 = _planned(store)
    backend2 = FakeBackend(base)
    explicit_none = lifecycle.run_through_backend(
        backend2, experiment2, attempt_id2, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
        before_execute=None,
    )
    assert set(omitted) == set(explicit_none)
    for key in omitted:
        if key == "attempt_id":
            continue
        assert _normalize_timestamps(omitted[key]) == _normalize_timestamps(explicit_none[key]), key


def test_before_execute_runs_after_install_and_before_execute_call(store: Path, base: Path) -> None:
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    order: list[str] = []
    real_install = backend.install
    real_execute = backend.execute

    def tracking_install(handle: object, surface: Mapping[str, object]) -> dict[str, object]:
        order.append("install")
        return real_install(handle, surface)

    def tracking_execute(
        handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
    ) -> ExecuteResult:
        order.append("execute")
        return real_execute(handle, argv, limits, cancel, stdin)

    backend.install = tracking_install  # type: ignore[method-assign]
    backend.execute = tracking_execute  # type: ignore[method-assign,assignment]

    def hook(be: object, handle: object) -> None:
        order.append("before_execute")

    lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
        before_execute=hook,
    )
    assert order == ["install", "before_execute", "execute"]


def test_a_raising_before_execute_hook_blocks_the_attempt_as_unavailable(store: Path, base: Path) -> None:
    """Control (#106's own acceptance: "credential below the threshold: the
    attempt is BLOCKED before launch, and no container remains"). A raising
    hook must reuse the SAME `unavailable` path install() failure takes -
    never dispatch, never execute - and teardown must still run."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)
    executed = False
    real_execute = backend.execute

    def tracking_execute(
        handle: object, argv: Sequence[str], limits: Limits,
        cancel: Callable[[], bool] | None = None, stdin: bytes | None = None,
    ) -> ExecuteResult:
        nonlocal executed
        executed = True
        return real_execute(handle, argv, limits, cancel, stdin)

    backend.execute = tracking_execute  # type: ignore[method-assign,assignment]

    def hook(be: object, handle: object) -> None:
        raise RuntimeError("credential has 10s remaining, below the required 300s")

    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
        before_execute=hook,
    )
    assert not executed
    assert record["disposition"] == "unavailable"
    reason = record["reason"]
    assert isinstance(reason, str) and "credential has 10s remaining" in reason
    assert attempt_id in backend.destroyed
    assert record["backend_teardown"] == "confirmed"


def test_before_execute_and_observe_before_teardown_compose(store: Path, base: Path) -> None:
    """Both hooks are independent extension points - using one must not
    disturb the other."""
    experiment, attempt_id = _planned(store)
    backend = FakeBackend(base)

    def before(be: object, handle: object) -> None:
        return None

    def after(be: object, handle: object) -> dict[str, object]:
        return {"read_back": True}

    record = lifecycle.run_through_backend(
        backend, experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
        before_execute=before, observe_before_teardown=after,
    )
    assert record["disposition"] == "captured"
    assert record["observation"] == {"read_back": True}


# ------------------------------------------------------ backend identity (#12)


@pytest.mark.parametrize(("ran", "matches"), [
    ("sha256:01", True),       # the image the ledger planned
    ("sha256:ff", False),      # a tag republished between planning and the run
    (None, None),              # the backend could not say - never read as a match
])
def test_the_image_that_ran_is_journaled_beside_the_planned_one(
    store: Path, base: Path, ran: str | None, matches: bool | None,
) -> None:
    experiment, attempt_id = _planned(store)
    lifecycle.run_through_backend(
        FakeBackend(base, reports_image=True, image_digest=ran), experiment, attempt_id,
        _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    [event] = _identity_events(experiment, attempt_id)
    assert event["image_digest"] == ran
    assert event["ledger_image_digest"] == "sha256:01"
    assert event["matches_ledger"] is matches


def test_a_backend_that_reports_no_image_journals_no_identity(store: Path, base: Path) -> None:
    """Absence of the key is a backend making no claim, not an unknown image."""
    experiment, attempt_id = _planned(store)
    lifecycle.run_through_backend(
        FakeBackend(base), experiment, attempt_id, _argv("work"), {"skill": "x"}, Limits(timeout=5), base,
    )
    assert _identity_events(experiment, attempt_id) == []
