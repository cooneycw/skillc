"""#626 a1 (owner ruling 2026-11-20, "626 empty: a1"), end to end through
assembly v2: a fully observed, naturally exiting role with ZERO projected
protocol events reads FAIL (`unfinished-role`) instead of UNKNOWN.

Imports only names the parent already has, so on the parent it collects and
the a1 cases fail by assertion (the parent reads UNKNOWN, worker:protocol-
unavailable). The capacity control reads UNKNOWN on both."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_live_wave_assembly import fixture
from test_live_wave_assembly_v2 import STEPS, _to_v2

from skillc import live_wave_assembly as assembly

INTEGRATOR_ONLY = [s for s in STEPS if s[0] == "integrator"]
# Steps must be in elapsed order: the fixture's injected clock follows them and
# the journal refuses a clock that goes backwards.
OFFER_ONLY = sorted(INTEGRATOR_ONLY + [("worker", "offer", 1, 200_000_000)], key=lambda s: s[3])


@pytest.mark.parametrize("steps", [INTEGRATOR_ONLY, OFFER_ONLY], ids=["no-events", "offer-only"])
def test_a_proven_empty_natural_exit_reads_fail(tmp_path: Path,
                                                steps: list[tuple[object, ...]]) -> None:
    arrival, expected, graders, _raw = fixture(tmp_path, alter=_to_v2(steps))
    wave = assembly.report(arrival, expected, graders)["waves"][0]
    assert wave["status"] == "FAIL", wave
    assert "worker:unfinished-role" in wave["failures"]
    assert "worker:protocol-unavailable" not in wave["unknown"]
    assert "integrator:unfinished-role" not in wave["failures"]


def test_a_zero_event_role_with_a_capacity_event_stays_unknown(tmp_path: Path) -> None:
    """The control: reads UNKNOWN on the parent and on a1."""
    arrival, expected, graders, _raw = fixture(
        tmp_path, alter=_to_v2(INTEGRATOR_ONLY, capacity_for=("worker",)))
    wave = assembly.report(arrival, expected, graders)["waves"][0]
    assert wave["status"] == "UNKNOWN" and "worker:protocol-unavailable" in wave["unknown"]
    assert "worker:unfinished-role" not in wave["failures"]
