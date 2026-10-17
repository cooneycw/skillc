"""The general one-sided two-proportion exact Fisher's test (#287).

`power_cost_table.py`'s own derivation is a SPECIAL case - the better arm
pinned at its ceiling (n/n) - chosen there because it collapses the
hypergeometric sum to one term. The power simulation in
`power_simulation.py` needs the GENERAL case: two arbitrary pass counts, out
of two arbitrary (here always equal) totals, because a Monte Carlo draw
almost never lands a whole arm at its ceiling.

THE TEST. Table:

              pass      fail        total
    A        a_pass   a_total-a_pass   a_total
    B        b_pass   b_total-b_pass   b_total
    -------------------------------------------
    total  a_pass+b_pass   ...         a_total+b_total

H1: P(pass | A) > P(pass | B). Fixing both margins, A's pass count follows
Hypergeometric(N=a_total+b_total, K=a_pass+b_pass, n=a_total). The one-sided
p-value is P(X >= a_pass) - every table at least as extreme in A's favour,
summed exactly via `math.comb` (arbitrary-precision integers, never a
floating-point approximation of the tail).

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import math


def _hypergeom_pmf(x: int, population: int, successes: int, draws: int) -> float:
    """P(X = x) for Hypergeometric(population, successes, draws): draw `draws`
    items without replacement from `population`, of which `successes` are
    "successes"; `x` of the draw are successes."""
    return math.comb(successes, x) * math.comb(population - successes, draws - x) / math.comb(population, draws)


def fisher_one_sided_greater(a_pass: int, a_total: int, b_pass: int, b_total: int) -> float:
    """The one-sided exact p-value for H1: P(pass|A) > P(pass|B), given the
    observed (a_pass, a_total) and (b_pass, b_total). Refuses a pass count
    outside its own total (that is not a table, it is a typo)."""
    if not (0 <= a_pass <= a_total):
        raise ValueError(f"a_pass={a_pass!r} must be between 0 and a_total={a_total!r}")
    if not (0 <= b_pass <= b_total):
        raise ValueError(f"b_pass={b_pass!r} must be between 0 and b_total={b_total!r}")
    population = a_total + b_total
    successes = a_pass + b_pass
    draws = a_total
    x_min_feasible = max(0, draws - (population - successes))
    x_max_feasible = min(draws, successes)
    if not (x_min_feasible <= a_pass <= x_max_feasible):
        raise ValueError(f"a_pass={a_pass!r} is not a feasible draw for this margin")
    return sum(_hypergeom_pmf(x, population, successes, draws) for x in range(a_pass, x_max_feasible + 1))
