"""Assembly contract version 2 (#620 PR-B, B6): a real sealed controller
journal replaces authored protocol bytes.

This module imports only names the parent commit already has, plus the
journal fixture builder, so on the parent it COLLECTS and every v2 test fails
on `freeze()` refusing version 2. The v1 control passes on both."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
import task_protocol_fixture as tpf
import test_wave_export as exported
from test_live_wave_assembly import DIGEST, fixture

from skillc import live_wave_assembly as assembly
from skillc import wave_wake_capture

STEPS = [("integrator", "offer", 1, 100_000_000), ("worker", "offer", 1, 200_000_000),
         ("integrator", "ack", 2, 1_000_000_000), ("worker", "ack", 2, 1_100_000_000),
         ("worker", "complete", 3, 2_100_000_000), ("integrator", "complete", 3, 4_000_000_000)]


def _to_v2(steps: list[Any] = STEPS, *, keep_v1_protocol: bool = False,
           capacity_for: tuple[str, ...] = (), outside: bool = False) -> Any:
    def alter(source: Path, catalogue: dict[str, Any], raw: dict[str, Any]) -> None:
        raw["version"] = 2
        entries = catalogue["entries"]
        for index, row in enumerate(raw["waves"]):
            if not keep_v1_protocol:
                for capture in row["roles"]:
                    capture["protocol"] = None
            wave = catalogue["waves"][index]
            plan = assembly._plan(row["plan"])
            captures = [r["path"] for r in wave["records"] if r["kind"] == "capture"]
            if index or not captures:
                root = wave["wave_id"] + "/not-a-capture/journal"
                built = None
            elif outside:
                # Built away from the export, named at a path no capture covers.
                root = wave["wave_id"] + "/outside-journal"
                built = tpf.build(source.parent / "outside-build", plan,
                                  catalogue["declaration_digest"], DIGEST, steps)
            else:
                root = captures[0] + "/protocol-journal"
                built = tpf.build(source / root, plan, catalogue["declaration_digest"], DIGEST,
                                  steps, capacity_for=capacity_for)
                for name in (root, root + "/objects"):
                    entries[name] = {"kind": "directory", "mode": 0o700}
                obj = root + "/objects/" + built.reference.digest[7:]
                data = (source / obj).read_bytes()
                entries[obj] = {"kind": "file", "mode": 0o400, "bytes": len(data),
                                "sha256": exported.sha(data)}
            if built is None:
                built = tpf.build(source.parent / f"unused-{index}", plan,
                                  catalogue["declaration_digest"], DIGEST, [],
                                  unbound=[r.role for r in plan.roles])
            wake = (wave_wake_capture.parse_context(row["wake"]["context"])
                    if row["wake"] is not None else None)
            row["protocol_v2"] = {
                "root": root, "reference": asdict(built.reference),
                "context": built.context.fields(), "inventory": built.inventory.fields(),
                "deadline_ns": built.deadline_ns,
                "clock_join": {"inventory_digest": built.inventory.digest,
                               "wake_context_digest": wake.digest if wake else None,
                               "origin_ns": built.inventory.clock_origin_ns}}
    return alter


def test_version_1_is_unchanged(tmp_path: Path) -> None:
    """The control: passes on the parent and on this change."""
    arrival, expected, graders, _raw = fixture(tmp_path)
    result = assembly.report(arrival, expected, graders)
    assert result["primary"]["pass"] == 1
    assert result["coverage"]["semantic_protocol_producer"] == "caller-supplied-captured-bytes"
    assert "protocol_diagnostic" not in result["waves"][0]


def test_a_real_journal_replaces_authored_bytes_and_reaches_pass(tmp_path: Path) -> None:
    arrival, expected, graders, _raw = fixture(tmp_path, alter=_to_v2())
    result = assembly.report(arrival, expected, graders)
    assert result["primary"] == {"unit": "wave", "planned": 2, "completed": 1, "pass": 1,
                                 "fail": 0, "unknown": 1}
    assert result["coverage"]["semantic_protocol_producer"] == "controller-journal-v2"
    diagnostic = result["waves"][0]["protocol_diagnostic"]
    assert diagnostic["status"] == "CAPTURED" and diagnostic["seal_outcome"] == "CLOSED"
    assert diagnostic["primary_effect"] == "none (decision 5)"


def test_a_b3_violation_is_diagnostic_and_keeps_the_primary_verdict(tmp_path: Path) -> None:
    """Decision 5 / #626: with clean projected rows, a protocol violation is
    reported separately and does not change the primary verdict."""
    steps = STEPS + [("worker", "complete", 4, 5_000_000_000)]
    arrival, expected, graders, _raw = fixture(tmp_path, alter=_to_v2(steps))
    result = assembly.report(arrival, expected, graders)
    assert result["waves"][0]["status"] == "PASS"
    roles = result["waves"][0]["protocol_diagnostic"]["roles"]
    assert roles["worker"]["violations"] == {"after-complete": 1}


def test_unknown_coverage_never_reaches_pass(tmp_path: Path) -> None:
    arrival, expected, graders, _raw = fixture(tmp_path, alter=_to_v2(capacity_for=("worker",)))
    result = assembly.report(arrival, expected, graders)
    assert result["waves"][0]["status"] == "UNKNOWN"
    assert "worker:protocol-unavailable" in result["waves"][0]["unknown"]


def test_a_journal_outside_the_wave_capture_joins_nothing(tmp_path: Path) -> None:
    arrival, expected, graders, _raw = fixture(tmp_path, alter=_to_v2(outside=True))
    result = assembly.report(arrival, expected, graders)
    assert result["waves"][0]["status"] == "UNKNOWN"
    assert result["waves"][0]["protocol_diagnostic"]["reasons"] == [
        "journal-root-outside-wave-capture"]


def test_version_2_with_authored_protocol_bytes_is_refused(tmp_path: Path) -> None:
    with pytest.raises(assembly.AssemblyRefused):
        fixture(tmp_path, alter=_to_v2(keep_v1_protocol=True))
