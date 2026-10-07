"""Equivalence guard for claims-outran-evidence's duplicated gate-witness
logic (#271), the identical pattern
`tests/test_gate_stops_early_witness_equivalence.py` already uses for
#270's `flow_check_honest()`.

`evals/level3/claims-outran-evidence/grade_claims_outran_evidence.py`
cannot import `skillc` (its own module docstring explains why:
`skillc.verify._judge` stages the judge file ALONE, `-I -S -B`, with no
`skillc` package reachable). So it carries its own small copies of
`skillc.gate_witness.GateRecord.execution_observed()`
(`_execution_observed`) and `skillc.stale_tree.last_run_is_fresh()`
(`_last_run_is_fresh`). A copy that silently diverges from skillc's own
would grade against a DIFFERENT rule than the one the real gate-witness
implements, and nothing in the judge's own tests could ever notice - they
never see the canonical functions to compare against. This test runs in
the NORMAL suite, where `skillc` IS importable, specifically to close
that gap.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from skillc.gate_witness import GateRecord, GateRunRecord

TASK = Path(__file__).resolve().parent.parent / "evals" / "level3" / "claims-outran-evidence"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"level3_claims_outran_evidence_{name}", TASK / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


judge = _load("grade_claims_outran_evidence")

FRESH = "sha256:fresh-tree"
STALE = "sha256:stale-tree"


def _run_dict(digest: str) -> dict[str, object]:
    return {"requested_at": 1.0, "completed_at": 1.1, "exit_code": 0, "reason": "exited",
            "tree_digest_at_start": digest, "stop_confirmed": None}


def _run_record(digest: str) -> GateRunRecord:
    return GateRunRecord(requested_at=1.0, completed_at=1.1, exit_code=0, reason="exited",
                        tree_digest_at_start=digest, stop_confirmed=None)


EXECUTION_OBSERVED_CASES = [
    ("normal (complete)", "complete", False),
    ("not-observed, no exclusivity", "not-observed", False),
    ("not-observed, exclusivity asserted (NOT_CONFIRMED)", "not-observed", True),
    ("launch-failed", "launch-failed", False),
    ("channel-unavailable", "channel-unavailable", False),
    ("interrupted", "interrupted", False),
]


@pytest.mark.parametrize("label,coverage,exclusivity_asserted", EXECUTION_OBSERVED_CASES)
def test_execution_observed_matches_canonical(label: str, coverage: str, exclusivity_asserted: bool) -> None:
    canonical = GateRecord(coverage=coverage, runs=(), exclusivity_asserted=exclusivity_asserted,
                           exclusivity_basis="equivalence test").execution_observed()
    duplicated = judge._execution_observed(coverage, exclusivity_asserted)
    assert duplicated == canonical, f"{label}: judge copy {duplicated} != canonical {canonical}"


FRESHNESS_CASES = [
    ("zero runs -> None", [], FRESH),
    ("single fresh run -> True", [FRESH], FRESH),
    ("single stale run -> False", [STALE], FRESH),
    ("edit-then-rerun: last run decides, not the first", [STALE, FRESH], FRESH),
    ("a rerun that drifted away from the graded tree", [FRESH, STALE], FRESH),
]


@pytest.mark.parametrize("label,digests,graded_digest", FRESHNESS_CASES)
def test_last_run_is_fresh_matches_canonical(label: str, digests: list[str], graded_digest: str) -> None:
    # `skillc.stale_tree` landed on main via #270 (PR #337, 5f2c484,
    # 2026-10-07) - this import now always succeeds. Kept as
    # `importorskip` rather than a plain import so a future checkout that
    # somehow lacks the module degrades to an honest skip instead of a
    # collection error, never falling back to a second duplicated copy of
    # the comparison logic that could drift the same way the thing it
    # guards against drifts.
    stale_tree = pytest.importorskip(
        "skillc.stale_tree",
        reason="skillc.stale_tree is unexpectedly absent; cannot cross-check against it",
    )
    canonical_record = GateRecord(coverage="complete", runs=tuple(_run_record(d) for d in digests),
                                  exclusivity_asserted=False, exclusivity_basis="equivalence test")
    canonical = stale_tree.last_run_is_fresh(canonical_record, graded_digest)
    duplicated = judge._last_run_is_fresh([_run_dict(d) for d in digests], graded_digest)
    assert duplicated == canonical, f"{label}: judge copy {duplicated!r} != canonical {canonical!r}"
