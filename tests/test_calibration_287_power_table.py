"""Negative control for evals/calibration-287/power_cost_table.py (#287 prep,
claude-power-pack CLAUDE.md's Negative Control rule): this table sizes n per
arm for a study nobody will independently re-derive before spending on it, so
its formula needs a committed case that distinguishes a correct hypergeometric
parameterization from a plausible, wrong one - not just a demonstration that
the current code runs without raising.

Imports the module by path rather than adding evals/ to the package, since
evals/ is data/artifacts, not an importable package (no __init__.py; matches
how tests/test_matched_pilot.py and tests/test_selection_probe.py already read
their own evals/*/run-manifest.json directly rather than importing code from
alongside it).
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "evals" / "calibration-287" / "power_cost_table.py"

_spec = importlib.util.spec_from_file_location("power_cost_table_287", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
pct = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pct)


def test_n10_matches_hand_computed_fractions():
    """Positive control: n=10's breakpoint and its two surrounding
    probabilities, computed independently here by hand-expanding
    math.comb (not calling the same helper), must match the module's
    `max_lower_pass_for_alpha(10)` exactly."""
    n = 10
    denom = math.comb(20, 10)
    assert denom == 184756
    # k=6: C(16,10)/C(20,10)
    p6 = math.comb(16, 10) / denom
    assert math.comb(16, 10) == 8008
    # k=7: C(17,10)/C(20,10)
    p7 = math.comb(17, 10) / denom
    assert math.comb(17, 10) == 19448

    assert p6 < 0.05 <= p7, "the hand-computed fractions themselves must straddle alpha, or this case tests nothing"

    k, p = pct.max_lower_pass_for_alpha(n)
    assert k == 6
    assert p == p6


def test_every_declared_n_straddles_alpha_correctly():
    """For every n in the module's own N_PER_ARM, p(k) < alpha <= p(k+1) -
    the returned k is exactly the breakpoint, not merely some value below
    alpha (which an off-by-one could satisfy while still being wrong)."""
    for n in pct.N_PER_ARM:
        k, p = pct.max_lower_pass_for_alpha(n)
        denom = math.comb(2 * n, n)
        assert p == math.comb(n + k, n) / denom
        assert p < pct.ALPHA
        p_next = math.comb(n + k + 1, n) / denom
        assert p_next >= pct.ALPHA, f"n={n}: k={k} is not the breakpoint - k+1 also stays below alpha"


def test_red_case_wrong_parameterization_gives_a_different_wrong_answer():
    """Red case: a plausible off-by-one mistake (using the hypergeometric
    numerator C(n+k-1, n) instead of C(n+k, n) - i.e. mis-pinning the
    better arm's margin one short of its actual ceiling) must produce a
    DIFFERENT breakpoint than the correct one, proving this suite would
    catch that mistake rather than passing regardless of the formula."""

    def wrong_max_lower_pass(n: int, alpha: float = 0.05) -> int:
        denom = math.comb(2 * n, n)
        best_k = -1
        for k in range(n + 1):
            numerator = math.comb(max(n + k - 1, 0), n)  # the planted defect
            p = numerator / denom
            if p < alpha:
                best_k = k
            else:
                break
        return best_k

    for n in pct.N_PER_ARM:
        correct_k, _ = pct.max_lower_pass_for_alpha(n)
        wrong_k = wrong_max_lower_pass(n)
        assert wrong_k != correct_k, (
            f"n={n}: the planted off-by-one formula accidentally agrees with the correct one "
            f"({wrong_k}) - this red case is inert at this n and proves nothing"
        )


def test_quota_equivalent_is_a_pure_linear_function_of_attempts():
    """`quota_equivalent_usd` must scale linearly with total attempts at the
    module's fixed per-attempt token assumption - catches a stray per-arm
    (rather than per-attempt) multiplication, which would be flat instead."""
    one = pct.quota_equivalent_usd(1)
    ten = pct.quota_equivalent_usd(10)
    assert one > 0
    assert math.isclose(ten, one * 10, rel_tol=1e-9)
