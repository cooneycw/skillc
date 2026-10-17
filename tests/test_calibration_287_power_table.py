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


REPORT_237 = Path(__file__).resolve().parent.parent / "evals" / "uptake-study" / "report.md"


def _report_token_cells(text: str) -> dict[tuple[str, str], tuple[int, int]]:
    """{(case, arm): (attempts, mean tokens)} parsed from #237's results
    table: attempts from the `Task PASS` denominator, tokens from `~NNNk`."""
    cells: dict[tuple[str, str], tuple[int, int]] = {}
    for line in text.splitlines():
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) != 6 or not cols[5].startswith("~") or not cols[5].endswith("k"):
            continue
        case = "intended-use" if cols[0].startswith("intended-use") else cols[0]
        attempts = int(cols[3].split("/")[1])
        cells[(case, cols[1])] = (attempts, int(cols[5][1:-1]) * 1000)
    return cells


def test_the_cited_token_cells_are_the_ones_237_measured():
    """The table's token input is cited as MEASURED; this ties every cited
    cell to #237's committed report, so a cell edited to a convenient number
    (or a report re-run) fails here instead of silently resizing the study."""
    measured = _report_token_cells(REPORT_237.read_text(encoding="utf-8"))
    assert len(measured) == 4, measured
    cited = {tuple(c.split("/")): (n, mean) for c, n, mean in pct.MEASURED_TOKEN_CELLS}
    assert cited == measured


def test_a_cell_off_by_one_attempt_is_detected():
    """Red case for the check above: the same parser on a copy of the report
    with one denominator changed must disagree with the cited cells."""
    text = REPORT_237.read_text(encoding="utf-8").replace("| near-miss | published | 0/10 | 10/10 |",
                                                         "| near-miss | published | 0/10 | 10/11 |")
    cited = {tuple(c.split("/")): (n, mean) for c, n, mean in pct.MEASURED_TOKEN_CELLS}
    assert cited != _report_token_cells(text)


def test_the_measured_mean_is_the_attempt_weighted_mean_of_the_cells():
    """140,500 = (20x175k + 20x137k + 10x103k + 10x116k) / 60, by hand."""
    assert pct.MEASURED_MEAN_TOKENS_PER_ATTEMPT == 140_500
    assert pct.MEASURED_UPPER_TOKENS_PER_ATTEMPT == 175_000


def test_totals_scale_per_attempt_across_both_two_arm_declarations():
    """Catches a per-arm (not per-attempt) multiplication, and a return to
    the superseded 3-shared-arm design: n=10 is 2 declarations x 2 arms x 10."""
    row = next(r for r in pct.build_table() if r["n_per_arm"] == 10)
    assert row["total_attempts_both_declarations"] == 40
    assert row["tokens_at_measured_mean"] == 40 * 140_500
    assert row["wall_seconds"] == "UNKNOWN"
