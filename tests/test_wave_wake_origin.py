"""#622 / #620 PR-B B8a: the wake capture records its own clock origin.

The original six-field capture shape stays verifiable, pinned by a capture
committed in controls/wave-wake-origin/ that was generated without running
this module. An origin-bearing capture proves its clock join from sealed
bytes, and the task-protocol adapter's join requires it."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
import task_protocol_fixture as tpf

from skillc import task_protocol_adapter as adapter
from skillc import wave_wake_capture as wc

ROOT = Path(__file__).resolve().parent.parent
CONTROL = ROOT / "controls" / "wave-wake-origin"
BINDING = json.loads((CONTROL / "binding.json").read_text())


def test_the_committed_six_field_capture_still_verifies() -> None:
    context = wc.parse_context(BINDING["context"])
    reference = wc.parse_reference(BINDING["reference"])
    assert context.origin_ns is None and context.fields() == BINDING["context"]
    assert context.digest == reference.context_digest
    assert wc.verify(CONTROL / "capture", reference, context)["status"] == "CAPTURED"
    seven = {**BINDING["context"], "origin_ns": None}
    assert wc.parse_context(seven) == context  # asdict() of an old context parses too


def _context(origin_ns: int | None) -> wc.Context:
    return replace(wc.parse_context(BINDING["context"]), origin_ns=origin_ns)


def test_an_origin_changes_the_digest_and_round_trips() -> None:
    with_origin = _context(5_000_000_000)
    assert with_origin.fields()["origin_ns"] == 5_000_000_000
    assert wc.parse_context(with_origin.fields()) == with_origin
    assert with_origin.digest != _context(None).digest


def _seal(root: Path, context: wc.Context, origin: float) -> wc.Reference:
    capture = wc.Capture(root, context, origin)
    return capture.seal("UNKNOWN", [{"role": r, "session_id": None} for r in context.roles])


def test_a_capture_must_start_at_its_recorded_origin(tmp_path: Path) -> None:
    context = _context(5_000_000_000)
    reference = _seal(tmp_path / "ok", context, 5.0)
    assert wc.verify(tmp_path / "ok", reference, context)["status"] == "CAPTURED"
    with pytest.raises(wc.CaptureUnavailable):
        wc.Capture(tmp_path / "wrong", context, 5.1)


def test_an_origin_capture_does_not_verify_against_another_origin(tmp_path: Path) -> None:
    reference = _seal(tmp_path / "c", _context(5_000_000_000), 5.0)
    for other in (None, 6_000_000_000):
        assert wc.verify(tmp_path / "c", reference, _context(other))["status"] == "UNKNOWN"


@pytest.mark.parametrize("value", [-1, True, 1.5, "5"])
def test_a_malformed_origin_is_refused(value: Any) -> None:
    with pytest.raises(ValueError):
        wc.parse_context({**BINDING["context"], "origin_ns": value})


# The task-protocol join now requires the wake capture's own origin.

DECL = "sha256:" + "d" * 64
DEADLINE = "sha256:" + "ab" * 32
ROLES = ("integrator", "worker")
STEPS = [("integrator", "offer", 1, 1), ("integrator", "ack", 2, 2)]


def _wake(plan: Any, origin_ns: int | None) -> wc.Context:
    return wc.Context(plan.wave_id, DECL, "sha256:" + "f" * 64, ROLES, DEADLINE, "monotonic",
                      origin_ns=origin_ns)


@pytest.mark.parametrize("origin,expected",
                         [(0, "CAPTURED"), (None, "UNKNOWN"), (7, "UNKNOWN")],
                         ids=["matches-inventory", "old-shape", "differs"])
def test_the_join_requires_the_wake_capture_origin(tmp_path: Path, origin: int | None,
                                                   expected: str) -> None:
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, STEPS)
    wake = _wake(plan, origin)
    join = adapter.ClockJoin(built.inventory.digest, wake.digest, built.inventory.clock_origin_ns)
    result = adapter.adapt(built.root, built.reference, built.context, built.inventory, plan,
                           built.deadline_ns, join, wake)
    assert result["status"] == expected
    if expected == "UNKNOWN":
        assert result["reasons"] == ["clock-join-unavailable"]


def test_a_join_without_the_origin_comparison_is_caught(tmp_path: Path) -> None:
    """A source mutant of the real adapter that drops the origin check."""
    source = Path(adapter.__file__).read_text()
    anchor = ("\n                or wake.origin_ns is None"
              " or wake.origin_ns != inventory.clock_origin_ns")
    assert source.count(anchor) == 1
    namespace: dict[str, Any] = {"__name__": "skillc._blind_adapter", "__package__": "skillc"}
    exec(compile(source.replace(anchor, ""), "<blind-adapter>", "exec"), namespace)  # noqa: S102
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, STEPS)
    wake = _wake(plan, None)
    join = namespace["ClockJoin"](built.inventory.digest, wake.digest, 0)
    blind = namespace["adapt"](built.root, built.reference, built.context, built.inventory, plan,
                               built.deadline_ns, join, wake)
    assert blind["status"] == "CAPTURED"  # the old-shape capture would have joined


def test_asdict_and_fields_agree_on_the_digest_for_an_old_context() -> None:
    context = _context(None)
    assert wc.parse_context(asdict(context)).digest == context.digest
