"""#622 / #620 PR-B B8a: the wake capture records its own clock origin.

The original six-field Context is unchanged; OriginContext adds a required
integer origin_ns as a second closed shape. The committed six-field capture
(controls/wave-wake-origin/, generated without running this module) still
verifies, and tests/test_wave_wake_old_shape.py proves on the parent API
that it is genuinely old-shape. The task-protocol adapter's clock join
requires the wake capture's own origin."""

from __future__ import annotations

import json
import sys
import types
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
import task_protocol_fixture as tpf

from skillc import task_protocol_adapter as adapter
from skillc import wave_wake_capture as wc

ROOT = Path(__file__).resolve().parent.parent
CONTROL = ROOT / "controls" / "wave-wake-origin"
BINDING = json.loads((CONTROL / "binding.json").read_text())


def _canonical(value: Any) -> str:
    """Compare serializations, not Python containers (a tuple of roles and its
    JSON list are the same context)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def test_the_committed_six_field_capture_still_verifies() -> None:
    context = wc.parse_context(BINDING["context"])
    reference = wc.parse_reference(BINDING["reference"])
    assert type(context) is wc.Context and context.clock_origin_ns is None
    assert _canonical(asdict(context)) == _canonical(BINDING["context"])
    assert context.digest == reference.context_digest
    assert wc.verify(CONTROL / "capture", reference, context)["status"] == "CAPTURED"


def _base() -> wc.Context:
    return wc.parse_context(BINDING["context"])


def _origin(origin_ns: int) -> wc.OriginContext:
    return wc.OriginContext(**asdict(_base()), origin_ns=origin_ns)


def test_an_origin_context_is_a_second_closed_shape() -> None:
    with_origin = _origin(5_000_000_000)
    assert asdict(with_origin)["origin_ns"] == 5_000_000_000
    assert wc.parse_context(asdict(with_origin)) == with_origin
    assert with_origin.digest != _base().digest and with_origin != _base()


@pytest.mark.parametrize("value", [None, -1, True, 1.5, "5"])
def test_a_null_or_malformed_origin_is_refused(value: Any) -> None:
    with pytest.raises(ValueError):
        wc.parse_context({**BINDING["context"], "origin_ns": value})


def test_an_eighth_key_is_refused() -> None:
    with pytest.raises(ValueError):
        wc.parse_context({**asdict(_origin(1)), "unexpected": None})


def _seal(root: Path, context: wc.Context, origin: float) -> wc.Reference:
    capture = wc.Capture(root, context, origin)
    return capture.seal("UNKNOWN", [{"role": r, "session_id": None} for r in context.roles])


def test_a_capture_must_start_at_its_recorded_origin(tmp_path: Path) -> None:
    context = _origin(5_000_000_000)
    reference = _seal(tmp_path / "ok", context, 5.0)
    assert wc.verify(tmp_path / "ok", reference, context)["status"] == "CAPTURED"
    with pytest.raises(wc.CaptureUnavailable):
        wc.Capture(tmp_path / "wrong", context, 5.1)


def test_an_origin_capture_does_not_verify_against_another_origin(tmp_path: Path) -> None:
    reference = _seal(tmp_path / "c", _origin(5_000_000_000), 5.0)
    for other in (_base(), _origin(6_000_000_000)):
        assert wc.verify(tmp_path / "c", reference, other)["status"] == "UNKNOWN"


# The task-protocol join now requires the wake capture's own origin.

DECL = "sha256:" + "d" * 64
DEADLINE = "sha256:" + "ab" * 32
ROLES = ("integrator", "worker")
STEPS = [("integrator", "offer", 1, 1), ("integrator", "ack", 2, 2)]


def _wake(plan: Any, origin_ns: int | None) -> wc.Context:
    base = wc.Context(plan.wave_id, DECL, "sha256:" + "f" * 64, ROLES, DEADLINE, "monotonic")
    return base if origin_ns is None else wc.OriginContext(**asdict(base), origin_ns=origin_ns)


def _adapt(module: Any, tmp_path: Path, origin: int | None) -> dict[str, Any]:
    plan = tpf.plan_of(ROLES)
    built = tpf.build(tmp_path / "j", plan, DECL, DEADLINE, STEPS)
    wake = _wake(plan, origin)
    join = module.ClockJoin(built.inventory.digest, wake.digest, built.inventory.clock_origin_ns)
    result: dict[str, Any] = module.adapt(built.root, built.reference, built.context,
                                          built.inventory, plan, built.deadline_ns, join, wake)
    return result


@pytest.mark.parametrize("origin,expected",
                         [(0, "CAPTURED"), (None, "UNKNOWN"), (7, "UNKNOWN")],
                         ids=["matches-inventory", "old-shape", "differs"])
def test_the_join_requires_the_wake_capture_origin(tmp_path: Path, origin: int | None,
                                                   expected: str) -> None:
    result = _adapt(adapter, tmp_path, origin)
    assert result["status"] == expected
    if expected == "UNKNOWN":
        assert result["reasons"] == ["clock-join-unavailable"]


def test_a_join_without_the_origin_comparison_is_caught(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """A source mutant of the REAL adapter with the origin check removed. It is
    registered as a module so its dataclasses resolve, then shown to ACCEPT
    the old-shape wake capture that the real adapter refuses."""
    source = Path(adapter.__file__).read_text()
    anchor = ("\n                or wake.clock_origin_ns is None"
              " or wake.clock_origin_ns != inventory.clock_origin_ns")
    assert source.count(anchor) == 1
    blind = types.ModuleType("skillc._blind_adapter")
    blind.__package__ = "skillc"
    monkeypatch.setitem(sys.modules, blind.__name__, blind)
    code = compile(source.replace(anchor, ""), "<blind-adapter>", "exec")
    exec(code, blind.__dict__)  # noqa: S102
    assert _adapt(adapter, tmp_path / "real", None)["status"] == "UNKNOWN"
    assert _adapt(blind, tmp_path / "blind", None)["status"] == "CAPTURED"
