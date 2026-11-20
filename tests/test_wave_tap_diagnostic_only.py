"""#626 P1, owner ruling 2026-11-20 (option A): the helper tap never feeds the
verdict. Parent-compatible: it uses whatever join the module has. On the
parent, `protocol_evidence` replaces the verdict input's protocol stream and
complete tap coverage plus a correct task PASSES, so this fails by assertion;
on this change there is no such join and the same inputs read UNKNOWN."""
from __future__ import annotations

from typing import Any

from test_wave_tap import boundary, request, wave_inputs  # noqa: F401 - boundary is a fixture

from skillc import wave_tap_join as join


def test_complete_tap_coverage_alone_never_passes(boundary: Any) -> None:  # noqa: F811
    assert request(boundary)["accepted"]
    assert request(boundary, "complete")["accepted"]
    boundary.executor.stopped = True
    collection = boundary.tap.finalize()
    lw, plan, evidence, grade = wave_inputs(boundary)
    old = getattr(join, "protocol_evidence", None)
    fed = old(plan, evidence, collection, boundary.tap.root) if old is not None else evidence
    result = lw.verdict(plan, fed, grade)
    assert result["status"] == "UNKNOWN", result["status"]
    assert f"{plan.roles[0].role}:protocol-unavailable" in result["unknown"]
