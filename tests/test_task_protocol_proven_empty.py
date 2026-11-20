"""#626 a1: the adapter's controller-proven-empty marker and the kernel's
reading of it. Each of the five proof items, missing alone, keeps the role
UNKNOWN; a blind twin of the REAL adapter with that check removed emits the
marker, and is asserted to DISAGREE with the real result.

Journal verification enforces that a CLOSED seal means complete coverage and
no capacity event for every principal. So a twin dropping only the per-role
coverage or capacity term is still held by the CLOSED term, and would be
blind by construction; those two twins drop the term AND the CLOSED term."""

from __future__ import annotations

import hashlib
import sys
import types
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import task_protocol_fixture as tpf
from test_live_wave import fixture, grade

from skillc import live_wave as lw
from skillc import task_protocol_adapter as adapter

DECL = "sha256:" + "d" * 64
DEADLINE = "sha256:" + "ab" * 32
ROLES = ("integrator", "worker")
INTEGRATOR = [("integrator", "offer", 1, 1), ("integrator", "ack", 2, 2),
              ("integrator", "complete", 3, 3)]

CLOSED = ' and verified["outcome"] == "CLOSED"'
#: Source edits that remove one proof check from the REAL adapter.
TWINS: dict[str, list[tuple[str, str]]] = {
    "barrier": [("(principal in bound and coverage", "(coverage")],
    "coverage": [(' and coverage.get(principal) == "complete"', ""), (CLOSED, "")],
    "capacity": [('                and principal not in capacity' + CLOSED + "\n", "")],
    "closed": [(CLOSED, "")],
    "join": [(" or join.origin_ns != inventory.clock_origin_ns", "")],
}
#: (case, build kwargs, join origin offset)
CASES = {
    "barrier": ({"unbound": ["worker"]}, 0),
    "coverage": ({"unknown_coverage": ["worker"]}, 0),
    "capacity": ({"capacity_for": ["worker"]}, 0),
    "closed": ({"unknown_coverage": ["integrator"]}, 0),
    "join": ({}, 1),
}


def _adapt(module: Any, root: Path, kwargs: dict[str, Any], offset: int) -> dict[str, Any]:
    plan = tpf.plan_of(ROLES)
    root.mkdir(parents=True)
    built = tpf.build(root / "j", plan, DECL, DEADLINE, INTEGRATOR, **kwargs)
    join = module.ClockJoin(built.inventory.digest, None, built.inventory.clock_origin_ns + offset)
    result: dict[str, Any] = module.adapt(built.root, built.reference, built.context,
                                          built.inventory, plan, built.deadline_ns, join)
    return result


def _twin(name: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    source = Path(adapter.__file__).read_text()
    for old, new in TWINS[name]:
        assert source.count(old) == 1, old
        source = source.replace(old, new)
    module = types.ModuleType("skillc._blind_adapter_" + name)
    module.__package__ = "skillc"
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(source, f"<blind-adapter-{name}>", "exec"), module.__dict__)  # noqa: S102
    return module


def test_a_fully_proven_zero_event_role_is_marked(tmp_path: Path) -> None:
    result = _adapt(adapter, tmp_path / "ok", {}, 0)
    assert result["status"] == "CAPTURED" and result["proven_empty"] == ["worker"]
    assert result["projections"]["worker"] is None  # never empty bytes
    assert result["projections"]["integrator"] is not None


@pytest.mark.parametrize("name", list(CASES))
def test_each_missing_proof_keeps_the_role_unmarked(tmp_path: Path, name: str) -> None:
    kwargs, offset = CASES[name]
    assert "worker" not in _adapt(adapter, tmp_path / "real", kwargs, offset)["proven_empty"]


@pytest.mark.parametrize("name", list(CASES))
def test_a_twin_without_that_check_disagrees(tmp_path: Path, name: str,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs, offset = CASES[name]
    real = _adapt(adapter, tmp_path / "real", kwargs, offset)["proven_empty"]
    blind = _adapt(_twin(name, monkeypatch), tmp_path / "blind", kwargs, offset)["proven_empty"]
    assert "worker" not in real and "worker" in blind
    assert real != blind


# -- the kernel: the marker is zero rows, then the EXISTING rules ------------------------------

EMPTY = lw.ProvenEmpty(b"", hashlib.sha256(b"").hexdigest())


def _verdict(**changes: Any) -> dict[str, Any]:
    plan, evidence = fixture()
    roles = list(evidence.roles)
    roles[1] = replace(roles[1], **changes)
    name = roles[1].role
    result = lw.verdict(plan, replace(evidence, roles=tuple(roles)), grade)
    result["_role"] = name
    return result


def test_the_marker_fails_a_fully_observed_clean_natural_exit() -> None:
    result = _verdict(protocol=EMPTY)
    assert result["status"] == "FAIL"
    assert f"{result['_role']}:unfinished-role" in result["failures"]


@pytest.mark.parametrize("changes", [
    {"stop_reason": "deadline"}, {"stop_reason": "infrastructure-cancelled"},
    {"stop_reason": "operator-cancelled"}, {"exit_code": 7}, {"capture_complete": False},
    {"stop_reason": "exited", "exit_code": None}],
    ids=["stopped-deadline", "killed-infrastructure", "killed-operator", "crashed",
         "capture-incomplete", "exit-unobserved"])
def test_stopped_killed_or_crashed_roles_stay_unknown(changes: dict[str, Any]) -> None:
    result = _verdict(protocol=EMPTY, **changes)
    role = result["_role"]
    assert f"{role}:unfinished-role" not in result["failures"]
    assert f"{role}:protocol-unavailable" in result["unknown"]


@pytest.mark.parametrize("blob", [lw.Blob(b"", hashlib.sha256(b"").hexdigest()),
                                  lw.ProvenEmpty(b"\n", hashlib.sha256(b"\n").hexdigest()),
                                  lw.ProvenEmpty(b"", "0" * 64)],
                         ids=["plain-empty-bytes", "marker-with-bytes", "marker-bad-digest"])
def test_anything_but_the_exact_marker_is_a_missing_capture(blob: lw.Blob) -> None:
    result = _verdict(protocol=blob)
    role = result["_role"]
    assert f"{role}:unfinished-role" not in result["failures"]
    assert f"{role}:protocol-unavailable" in result["unknown"]
