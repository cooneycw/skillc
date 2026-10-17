"""The pilot-to-main sizing rule for #287 (orchestrator review, decisions
P1-P6 on the declaration plan, comment 6025311708).

THE RULE, fixed before the pilot runs so no one can tune it after seeing the
data (P6's "state the rule before the pilot" condition, restated here in
code rather than only in prose):

1. The pilot (`evals/calibration-287/README.md`'s own section) estimates
   four pass rates from n_pilot=10/arm: intact (from the discrimination
   pilot), degraded, cpp (from the improvement pilot - a SEPARATE pilot
   declaration per P2, so this is a second, independent measurement of the
   same arm, not reused from the discrimination pilot), and baseline.
2. Each raw proportion is converted to a JEFFREYS estimate (P3) before it
   is used: `p_tilde = (passes + 0.5) / (evaluable + 1)`. At n=10 a raw
   10/10 or 0/10 makes the simulated draw `Binomial(n, 1.0)` or `(n, 0.0)`
   DETERMINISTIC - every simulated trial identical, which overstates power
   relative to the true uncertainty a single pilot of 10 actually carries.
3. For each candidate n in `CANDIDATE_NS`, Monte Carlo `N_SIM` synthetic
   trials estimate the power of EACH test (discrimination: intact vs
   degraded; improvement: cpp vs baseline) at that n, using a FIXED,
   RECORDED seed - the same seed given the same pilot numbers always
   reproduces the same chosen n.
4. (P4) If discrimination power never reaches `TARGET_POWER` by the
   largest candidate, the main study is NOT run - a pre-declared outcome,
   reported back to skillc#270's case design, never an operator question.
   Only an improvement-only shortfall escalates to the operator.

Stdlib only (AGENTS.md): `random.Random(seed)` for the simulation,
`fisher_exact.fisher_one_sided_greater` (same package) for the exact
p-value - no numpy, no scipy.
"""

from __future__ import annotations

import importlib.util
import random
from dataclasses import dataclass
from pathlib import Path

_fe_spec = importlib.util.spec_from_file_location(
    "fisher_exact_287", Path(__file__).resolve().parent / "fisher_exact.py"
)
assert _fe_spec is not None and _fe_spec.loader is not None
fisher_exact = importlib.util.module_from_spec(_fe_spec)
_fe_spec.loader.exec_module(fisher_exact)

ALPHA = 0.05
TARGET_POWER = 0.80
N_SIM = 10_000
CANDIDATE_NS: tuple[int, ...] = (10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200)

NOT_RUN_NO_DISCRIMINATION = "NOT_RUN_NO_DISCRIMINATION_POWER"
ESCALATE_IMPROVEMENT_SHORTFALL = "ESCALATE_IMPROVEMENT_SHORTFALL"
SIZED = "SIZED"


def jeffreys_estimate(passes: int, evaluable: int) -> float:
    """P3: never a raw proportion. Refuses a pilot with zero evaluable
    attempts outright - there is nothing to estimate from, and a 0/0
    Jeffreys estimate (0.5) would silently stand in for data that was
    never collected."""
    if evaluable < 1:
        raise ValueError("evaluable must be at least 1 - a pilot with no evaluable attempts has no rate to estimate")
    if not (0 <= passes <= evaluable):
        raise ValueError(f"passes={passes!r} must be between 0 and evaluable={evaluable!r}")
    return (passes + 0.5) / (evaluable + 1)


def simulate_power(p_a: float, p_b: float, n: int, *, n_sim: int, seed: int) -> float:
    """Fraction of `n_sim` simulated (A, B) draws, each `Binomial(n, p)` via
    a fixed `random.Random(seed)` stream, for which the exact one-sided
    Fisher's test (H1: P(pass|A) > P(pass|B)) reaches p < ALPHA."""
    rng = random.Random(seed)
    significant = 0
    for _ in range(n_sim):
        a_pass = sum(1 for _ in range(n) if rng.random() < p_a)
        b_pass = sum(1 for _ in range(n) if rng.random() < p_b)
        p_value = fisher_exact.fisher_one_sided_greater(a_pass, n, b_pass, n)
        if p_value < ALPHA:
            significant += 1
    return significant / n_sim


@dataclass(frozen=True)
class SizingResult:
    verdict: str  # SIZED | NOT_RUN_NO_DISCRIMINATION | ESCALATE_IMPROVEMENT_SHORTFALL
    chosen_n: int | None
    discrimination_power_by_n: dict[int, float]
    improvement_power_by_n: dict[int, float]


def choose_n(
    p_intact: float, p_degraded: float, p_cpp: float, p_baseline: float,
    *, candidates: tuple[int, ...] = CANDIDATE_NS, n_sim: int = N_SIM, seed: int,
) -> SizingResult:
    """P1-P6's sizing rule. `p_intact`/`p_degraded`/`p_cpp`/`p_baseline` are
    already-Jeffreys-adjusted estimates (callers compute them with
    `jeffreys_estimate`, never pass raw proportions) - this function does
    not re-check that, since it cannot tell a deliberately-passed 1.0 from
    an adjusted one; that is the test suite's job (see the committed
    mutation check)."""
    discrimination_power: dict[int, float] = {}
    improvement_power: dict[int, float] = {}
    discrimination_n_reaching_target: int | None = None

    for n in candidates:
        discrimination_power[n] = simulate_power(p_intact, p_degraded, n, n_sim=n_sim, seed=seed)
        improvement_power[n] = simulate_power(p_cpp, p_baseline, n, n_sim=n_sim, seed=seed + 1)
        if discrimination_n_reaching_target is None and discrimination_power[n] >= TARGET_POWER:
            discrimination_n_reaching_target = n

    if discrimination_n_reaching_target is None:
        return SizingResult(NOT_RUN_NO_DISCRIMINATION, None, discrimination_power, improvement_power)

    for n in candidates:
        if n < discrimination_n_reaching_target:
            continue
        if discrimination_power[n] >= TARGET_POWER and improvement_power[n] >= TARGET_POWER:
            return SizingResult(SIZED, n, discrimination_power, improvement_power)

    return SizingResult(ESCALATE_IMPROVEMENT_SHORTFALL, None, discrimination_power, improvement_power)
