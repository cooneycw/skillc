"""Tests for the execution backend seam (#10, PR1a).

This module defines a `Protocol`, not an implementation - there is nothing here
to selftest or control in ADR 0001's sense (no rule, no discriminating input).
What IS load-bearing now is the structural guarantee interfaces.md's
"Execution backend" section states: an unavailable backend becomes a
`finalize(disposition="unavailable")` record and never a dispatched attempt.
PR1b wires this into the real lifecycle driver; this test proves the wiring is
possible with `trial.py`'s EXISTING machinery, unchanged by this seam.
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

    def confirm_stopped(self, handle: object) -> bool:
        raise AssertionError("must never be called: nothing was ever started")

    def export(self, handle: object, dest: Path) -> None:
        raise AssertionError("must never be called: nothing was ever started")

    def destroy(self, handle: object) -> None:
        pass

    def confirm_absent(self, handle: object) -> bool:
        return True


def _dispatch_or_declare_unavailable(
    backend: b.ExecutionBackend, experiment: t.Experiment, attempt_id: str,
) -> dict[str, object]:
    """The property PR1b's real driver must have: an unavailable backend ends
    the attempt through finalize(disposition="unavailable"), and the subject's
    real argv is never constructed or run on the host."""
    try:
        backend.prepare(attempt_id)
    except b.BackendUnavailable as exc:
        return t.finalize(experiment, attempt_id, disposition="unavailable", reason=str(exc))
    raise AssertionError("this fake backend always refuses prepare()")


def test_an_unavailable_backend_is_a_refusal_never_a_dispatch(tmp_path: Path) -> None:
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
    attempt_id = str(attempt["attempt_id"])

    record = _dispatch_or_declare_unavailable(_UnavailableBackend(), experiment, attempt_id)

    assert record["disposition"] == "unavailable"
    assert "no daemon reachable" in str(record["reason"])
    events = [e.get("event") for e in experiment.events(attempt_id)]
    assert "dispatched" not in events, "an unavailable backend must never dispatch on the host"


def test_the_protocol_is_runtime_checkable_against_a_conforming_backend() -> None:
    """A sanity check that `_UnavailableBackend` (and so any real backend
    shaped like it) actually satisfies `ExecutionBackend`, not just by
    convention but by `isinstance`."""
    assert isinstance(_UnavailableBackend(), b.ExecutionBackend)
