"""Tests for the execution backend seam (#10, PR1a).

This module defines a `Protocol`, not an implementation - there is nothing here
to selftest or control in ADR 0001's sense (no rule, no discriminating input).

What these tests show, and what they do NOT: `test_finalize_supports_an_
unavailable_backend_with_no_dispatch` proves `trial.finalize`'s EXISTING
`disposition="unavailable"` override can represent "this backend was never
reachable, nothing was dispatched" - using a five-line helper defined right in
this test file, not any real driver. That is a claim about `trial.py`'s
machinery, not yet a "structural" claim about skillc's actual lifecycle
driver; PR1b's driver is where that claim gets made and earned, against this
same fake backend or one like it wired through the real code path.

`test_confirmation_unknown_is_never_treated_as_confirmed` shows the other
open question fix from the PR #65 review: a backend that cannot observe
returns `Confirmation.UNKNOWN`, and nothing here (or in `Confirmation` itself)
lets `UNKNOWN` be mistaken for `CONFIRMED`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from skillc import backend as b
from skillc import trial as t


class _UnavailableBackend:
    """A backend whose `prepare()` always refuses - the daemon-absent case.
    Every other method raises if reached, because reaching them would mean
    something ran on the host despite `prepare()` never granting isolation."""

    def describe(self) -> b.BackendDescription:
        return b.BackendDescription(name="fake-down", version="0", isolation=(), unobserved=())

    def prepare(self, attempt_id: str) -> object:
        raise b.BackendUnavailable("no daemon reachable")

    def install(self, handle: object, surface: Mapping[str, object]) -> dict[str, object]:
        raise AssertionError("must never be called: prepare() already refused")

    def execute(
        self, handle: object, argv: Sequence[str], limits: b.Limits,
        cancel: Callable[[], bool] | None = None,
    ) -> b.ExecuteResult:
        raise AssertionError("must never be called: prepare() already refused")

    def confirm_stopped(self, handle: object) -> b.Confirmation:
        raise AssertionError("must never be called: nothing was ever started")

    def export(self, handle: object, dest: Path) -> None:
        raise AssertionError("must never be called: nothing was ever started")

    def destroy(self, handle: object) -> None:
        pass

    def confirm_absent(self, handle: object) -> b.Confirmation:
        return b.Confirmation.CONFIRMED


class _UnobservableBackend(_UnavailableBackend):
    """A backend that DID start (unlike `_UnavailableBackend`) but has since
    lost the ability to ask itself anything - a daemon that died mid-attempt.
    Only the two confirm_* methods are exercised by the test below; the rest
    inherit `_UnavailableBackend`'s "must never be called" shape because this
    fake never reaches `prepare()` successfully either, for simplicity."""

    def confirm_stopped(self, handle: object) -> b.Confirmation:
        return b.Confirmation.UNKNOWN

    def confirm_absent(self, handle: object) -> b.Confirmation:
        return b.Confirmation.UNKNOWN


def _dispatch_or_declare_unavailable(
    backend: b.ExecutionBackend, experiment: t.Experiment, attempt_id: str,
) -> dict[str, object]:
    """A minimal illustration of the property PR1b's real driver must have -
    NOT the driver itself. An unavailable backend ends the attempt through
    finalize(disposition="unavailable"), and the subject's real argv is never
    constructed or run on the host."""
    try:
        backend.prepare(attempt_id)
    except b.BackendUnavailable as exc:
        return t.finalize(experiment, attempt_id, disposition="unavailable", reason=str(exc))
    raise AssertionError("this fake backend always refuses prepare()")


def _planned_attempt(tmp_path: Path) -> tuple[t.Experiment, str]:
    store = t.open_store(tmp_path / "store", forbidden=[])
    spec: dict[str, object] = {
        "experiment": "seam-check",
        "trials": [{
            "label": "t", "case": {"id": "c", "revision": "r1"}, "grader": {"id": "g", "revision": "g1"},
            "subject": {"digest": "sha256:00"}, "client": {"name": "fake", "version": "1"},
            "image": {"digest": "sha256:01"}, "config": {}, "attempts": 1,
        }],
    }
    experiment = t.plan(spec, store)
    [(_trial, attempt)] = list(experiment.attempts())
    return experiment, str(attempt["attempt_id"])


def test_finalize_supports_an_unavailable_backend_with_no_dispatch(tmp_path: Path) -> None:
    """trial.finalize's EXISTING machinery, unchanged by this seam, can
    represent "backend unreachable, nothing dispatched" - see the module
    docstring for what this does and does not claim about a real driver."""
    experiment, attempt_id = _planned_attempt(tmp_path)

    record = _dispatch_or_declare_unavailable(_UnavailableBackend(), experiment, attempt_id)

    assert record["disposition"] == "unavailable"
    assert "no daemon reachable" in str(record["reason"])
    events = [e.get("event") for e in experiment.events(attempt_id)]
    assert "dispatched" not in events, "an unavailable backend must never dispatch on the host"


def test_confirmation_unknown_is_never_treated_as_confirmed() -> None:
    """A backend that cannot observe returns UNKNOWN, not a guessed
    CONFIRMED or NOT_CONFIRMED - and UNKNOWN must never compare equal to, or
    be mistaken for, a confirmation (PR #65 review)."""
    backend = _UnobservableBackend()
    stopped = backend.confirm_stopped(object())
    absent = backend.confirm_absent(object())

    assert stopped is b.Confirmation.UNKNOWN
    assert absent is b.Confirmation.UNKNOWN
    for value in (stopped, absent):
        assert value != b.Confirmation.CONFIRMED
        assert value != b.Confirmation.NOT_CONFIRMED


def test_the_protocol_is_runtime_checkable_against_a_conforming_backend() -> None:
    """A sanity check that `_UnavailableBackend` (and so any real backend
    shaped like it) actually satisfies `ExecutionBackend`, not just by
    convention but by `isinstance`."""
    assert isinstance(_UnavailableBackend(), b.ExecutionBackend)
