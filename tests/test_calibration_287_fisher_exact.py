"""Tests for `evals/calibration-287/fisher_exact.py`: the general one-sided
two-proportion exact Fisher's test the power simulation relies on.

The committed red case the orchestrator asked for: a known-answer check
against claude-power-pack#1084's own computed boundary table (comment
6014163660), reproduced exactly here, not re-derived from this module's own
code - if this module and that issue's independently-computed numbers ever
disagree, this test is what catches it."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "evals" / "calibration-287" / "fisher_exact.py"
_spec = importlib.util.spec_from_file_location("fisher_exact_287", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
fe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fe)


def test_a_feasible_pass_count_outside_its_own_total_is_refused() -> None:
    with pytest.raises(ValueError, match="a_pass"):
        fe.fisher_one_sided_greater(11, 10, 5, 10)
    with pytest.raises(ValueError, match="b_pass"):
        fe.fisher_one_sided_greater(5, 10, -1, 10)


def test_identical_arms_never_reach_significance() -> None:
    """Two arms with the same pass count can never show A > B."""
    p = fe.fisher_one_sided_greater(5, 10, 5, 10)
    assert p >= 0.05


def test_the_better_arm_at_ceiling_matches_power_cost_tables_special_case() -> None:
    """Cross-check against the OTHER committed module's special-case formula
    (power_cost_table.py's better-arm-at-n/n derivation) - both compute the
    same quantity by different routes and must agree."""
    # n=10, worse arm passes 6: power_cost_table.py's own committed result.
    p = fe.fisher_one_sided_greater(10, 10, 6, 10)
    assert p < 0.05
    p_one_more = fe.fisher_one_sided_greater(10, 10, 7, 10)
    assert p_one_more >= 0.05


# --------------------------------------- claude-power-pack#1084's boundary table


_CPP_1084_BOUNDARIES = [
    # (n, weaker_arm_pass, minimum_stronger_arm_pass_for_significance)
    (10, 0, 4),
    (10, 2, 7),
    (10, 4, 9),
    (10, 6, 10),
    (20, 10, 16),
    (20, 15, 20),
]


@pytest.mark.parametrize(("n", "weak", "strong_min"), _CPP_1084_BOUNDARIES)
def test_matches_cpp_1084s_computed_boundary_table(n: int, weak: int, strong_min: int) -> None:
    """Known-answer check (orchestrator review, #287): at the stated minimum
    the stronger arm must reach significance; one pass fewer must not."""
    at_boundary = fe.fisher_one_sided_greater(strong_min, n, weak, n)
    assert at_boundary < 0.05, f"n={n} weak={weak}: expected p<0.05 at strong={strong_min}, got {at_boundary}"
    if strong_min > weak:
        below_boundary = fe.fisher_one_sided_greater(strong_min - 1, n, weak, n)
        assert below_boundary >= 0.05, (
            f"n={n} weak={weak}: expected p>=0.05 at strong={strong_min - 1}, got {below_boundary}"
        )


def test_red_case_an_off_by_one_hypergeometric_margin_would_fail_this_table() -> None:
    """Mutation check: a plausible off-by-one (summing from a_pass+1 instead
    of a_pass, i.e. a strict-greater tail instead of at-least) must disagree
    with claude-power-pack#1084's boundary table at the point JUST BELOW
    each threshold - omitting the `a_pass` term only ever shrinks the
    p-value, so at the passing threshold itself the mutation can only agree
    (p drops, stays under 0.05); the discriminating point is one pass
    fewer, where the mutation's smaller p-value can wrongly cross below
    0.05 and claim significance the correct computation refuses."""

    def off_by_one(a_pass: int, a_total: int, b_pass: int, b_total: int) -> float:
        population, successes, draws = a_total + b_total, a_pass + b_pass, a_total
        x_max = min(draws, successes)
        return sum(fe._hypergeom_pmf(x, population, successes, draws) for x in range(a_pass + 1, x_max + 1))

    disagreements = 0
    for n, weak, strong_min in _CPP_1084_BOUNDARIES:
        if strong_min == weak:
            continue
        below = strong_min - 1
        correct = fe.fisher_one_sided_greater(below, n, weak, n)
        mutated = off_by_one(below, n, weak, n)
        assert correct >= 0.05, f"n={n} weak={weak}: expected p>=0.05 at {below}, got {correct}"
        if (correct < 0.05) != (mutated < 0.05):
            disagreements += 1
    assert disagreements > 0, "the off-by-one mutation agreed with every boundary pair - this red case is inert"
