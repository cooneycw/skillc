"""Tests for `evals/calibration-287/power_simulation.py`: the pilot-to-main
sizing rule (P1-P6, orchestrator review on #287).

The committed red case the orchestrator asked for: a mutation where a
plug-in raw 1.0 (instead of the Jeffreys estimate, P3) changes the chosen
n - demonstrating concretely why P3 matters, not just asserting it."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "evals" / "calibration-287" / "power_simulation.py"
_spec = importlib.util.spec_from_file_location("power_simulation_287", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
ps = importlib.util.module_from_spec(_spec)
# dataclasses resolves annotations via sys.modules[cls.__module__] at class-
# creation time, so SizingResult's @dataclass fails with a bare AttributeError
# unless this module is registered in sys.modules BEFORE exec_module runs.
sys.modules[_spec.name] = ps
_spec.loader.exec_module(ps)


def test_jeffreys_estimate_is_never_a_raw_boundary_proportion() -> None:
    assert ps.jeffreys_estimate(10, 10) == pytest.approx(10.5 / 11)
    assert ps.jeffreys_estimate(0, 10) == pytest.approx(0.5 / 11)
    assert 0.0 < ps.jeffreys_estimate(10, 10) < 1.0
    assert 0.0 < ps.jeffreys_estimate(0, 10) < 1.0


def test_jeffreys_estimate_refuses_zero_evaluable() -> None:
    with pytest.raises(ValueError, match="evaluable"):
        ps.jeffreys_estimate(0, 0)


def test_jeffreys_estimate_refuses_an_infeasible_pass_count() -> None:
    with pytest.raises(ValueError, match="passes"):
        ps.jeffreys_estimate(11, 10)


def test_simulate_power_is_deterministic_for_a_fixed_seed() -> None:
    """The sizing rule's whole point (P6: 'fixed and recorded... before the
    pilot runs') depends on this: the same inputs and seed must always
    give the same power estimate, never a fresh random draw each call."""
    a = ps.simulate_power(0.9, 0.3, 20, n_sim=2000, seed=42)
    b = ps.simulate_power(0.9, 0.3, 20, n_sim=2000, seed=42)
    assert a == b


def test_simulate_power_is_near_zero_when_arms_are_identical() -> None:
    power = ps.simulate_power(0.5, 0.5, 20, n_sim=2000, seed=7)
    assert power < 0.10  # a one-sided test on identical arms should rarely reach significance


def test_simulate_power_is_high_for_a_large_true_effect() -> None:
    power = ps.simulate_power(0.95, 0.1, 30, n_sim=2000, seed=7)
    assert power > 0.90


# ------------------------------------------- choose_n's pre-declared outcomes


def test_no_candidate_reaching_discrimination_power_is_not_run() -> None:
    """P4: identical intact/degraded rates can never show discrimination at
    any n up to the candidate ceiling - the pre-declared non-run outcome,
    never an operator escalation."""
    result = ps.choose_n(0.5, 0.5, 0.9, 0.5, seed=1, candidates=(10, 15, 20))
    assert result.verdict == ps.NOT_RUN_NO_DISCRIMINATION
    assert result.chosen_n is None


def test_discrimination_powered_but_improvement_shortfall_escalates() -> None:
    """P4's other half: discrimination reaches target easily, but the
    improvement test's assumed effect is too small to reach 80% power even
    at the largest candidate - this DOES escalate to the operator."""
    result = ps.choose_n(0.95, 0.1, 0.55, 0.5, seed=2, candidates=(10, 15, 20))
    assert result.verdict == ps.ESCALATE_IMPROVEMENT_SHORTFALL
    assert result.chosen_n is None


def test_a_real_detectable_effect_sizes_to_the_smallest_sufficient_n() -> None:
    result = ps.choose_n(0.95, 0.1, 0.9, 0.1, seed=3, candidates=(10, 15, 20, 30))
    assert result.verdict == ps.SIZED
    assert result.chosen_n in ps.CANDIDATE_NS


# ------------------------------------------------- P3's red case, concretely


def test_red_case_p3_a_raw_1_0_plug_in_changes_the_chosen_n() -> None:
    """The orchestrator's named red case: at n_pilot=10, a 10/10 pilot arm
    plugged in RAW (1.0) makes that arm's simulated draw deterministic
    (`Binomial(n, 1.0)` always passes), overstating power relative to the
    Jeffreys-adjusted estimate - and the overstated power changes the
    SIZING OUTCOME, not just the power numbers, for a concrete, realistic
    pilot result (10/10 intact and cpp, 5/10 degraded and baseline)."""
    candidates = (10, 15, 20, 25, 30)
    degraded_estimate = ps.jeffreys_estimate(5, 10)
    jeffreys_intact = ps.jeffreys_estimate(10, 10)

    raw = ps.choose_n(1.0, degraded_estimate, 1.0, degraded_estimate, seed=20261006, candidates=candidates)
    jeffreys = ps.choose_n(
        jeffreys_intact, degraded_estimate, jeffreys_intact, degraded_estimate,
        seed=20261006, candidates=candidates,
    )

    assert raw.verdict == ps.SIZED
    assert jeffreys.verdict == ps.SIZED
    assert raw.chosen_n is not None
    assert jeffreys.chosen_n is not None
    assert raw.chosen_n < jeffreys.chosen_n, (
        f"expected the raw 1.0 plug-in to choose a SMALLER (underpowered) n than the Jeffreys "
        f"estimate - got raw={raw.chosen_n}, jeffreys={jeffreys.chosen_n}; if these now agree, "
        f"this red case no longer demonstrates P3's concern"
    )
