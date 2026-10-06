"""Tests for skillc/reliability.py (issue #273).

Each estimator is checked against a hand-computable value, not against a
second implementation of the same formula - the point of a golden dataset is
that it can be checked by arithmetic, not by trusting the code that produced
it. The acceptance line's five control shapes (heterogeneous-task,
duplicate/retry, missing-data, zero-population, n<k) each have a dedicated
test naming which shape it is.
"""

from __future__ import annotations

import random

import pytest

from skillc import reliability as rel

# --------------------------------------------------------------- all_k / pass_at_k

def test_all_k_hand_computed() -> None:
    # C(3,2)/C(5,2) = 3/10
    assert rel.all_k(3, 5, 2) == pytest.approx(0.3)
    # C(4,4)/C(4,4) = 1
    assert rel.all_k(4, 4, 4) == pytest.approx(1.0)
    # C(0,2)/C(5,2) = 0
    assert rel.all_k(0, 5, 2) == pytest.approx(0.0)


def test_pass_at_k_hand_computed() -> None:
    # 1 - C(2,2)/C(5,2) = 1 - 1/10 = 0.9
    assert rel.pass_at_k(3, 5, 2) == pytest.approx(0.9)
    # 1 - C(5,2)/C(5,2) = 0, zero successes can never pass-at-k
    assert rel.pass_at_k(0, 5, 2) == pytest.approx(0.0)


def test_all_k_and_pass_at_k_are_different_functions_not_aliases() -> None:
    # A case where they must disagree: 1 success of 2, k=1.
    # all_k = C(1,1)/C(2,1) = 1/2. pass_at_k = 1 - C(1,1)/C(2,1) = 1/2.
    # Pick a case where they clearly diverge instead:
    # c=1, n=3, k=2: all_k = C(1,2)/C(3,2) = 0/3 = 0
    #                 pass_at_k = 1 - C(2,2)/C(3,2) = 1 - 1/3 = 2/3
    assert rel.all_k(1, 3, 2) == pytest.approx(0.0)
    assert rel.pass_at_k(1, 3, 2) == pytest.approx(2.0 / 3.0)


# --------------------------------------------------------------- n<k control

def test_n_less_than_k_is_insufficient_never_zero() -> None:
    assert rel.all_k(2, 3, 5) == rel.INSUFFICIENT
    assert rel.pass_at_k(2, 3, 5) == rel.INSUFFICIENT
    # Never confusable with a real zero result:
    assert rel.all_k(2, 3, 5) != 0
    assert rel.all_k(2, 3, 5) != 0.0


def test_all_k_refuses_malformed_input() -> None:
    with pytest.raises(rel.ReliabilityRefused):
        rel.all_k(-1, 5, 2)
    with pytest.raises(rel.ReliabilityRefused):
        rel.all_k(6, 5, 2)  # c > n
    with pytest.raises(rel.ReliabilityRefused):
        rel.all_k(1, 5, 0)  # k must be >= 1
    with pytest.raises(rel.ReliabilityRefused):
        rel.all_k(True, 5, 2)  # bool is not an int here, even though it is one in Python


# --------------------------------------------------------------- population_all_k / heterogeneous-task

def test_population_all_k_heterogeneous_tasks() -> None:
    # Three tasks with different n, k=2: t1 all_k=0.3 (3/5 C(3,2)/C(5,2)),
    # t2 all_k=1.0 (2/2), t3 all_k=0.0 (1/4, n>=k but C(1,2)=0).
    result = rel.population_all_k({"t1": (3, 5), "t2": (2, 2), "t3": (1, 4)}, k=2)
    assert result.per_task == {"t1": pytest.approx(0.3), "t2": pytest.approx(1.0), "t3": pytest.approx(0.0)}
    assert result.excluded == ()
    assert result.mean == pytest.approx((0.3 + 1.0 + 0.0) / 3.0)


def test_population_all_k_excludes_insufficient_tasks_by_name() -> None:
    # t4 has n=1 < k=2: excluded, never scored as 0.
    result = rel.population_all_k({"t1": (3, 5), "t4": (1, 1)}, k=2)
    assert result.excluded == ("t4",)
    assert "t4" not in result.per_task
    assert result.mean == pytest.approx(0.3)  # only t1 counted


def test_population_all_k_zero_population_is_none_not_zero() -> None:
    # Every task excluded -> no mean to report, not 0.0.
    result = rel.population_all_k({"t1": (1, 1)}, k=2)
    assert result.mean is None
    assert result.excluded == ("t1",)

    empty = rel.population_all_k({}, k=2)
    assert empty.mean is None
    assert empty.excluded == ()


def test_population_all_k_declared_weights() -> None:
    result = rel.population_all_k(
        {"t1": (3, 5), "t2": (2, 2)}, k=2, weights={"t1": 1.0, "t2": 3.0},
    )
    # weighted mean = (1*0.3 + 3*1.0) / 4 = 3.3/4 = 0.825
    assert result.mean == pytest.approx(0.825)


def test_population_all_k_refuses_a_weight_map_naming_the_wrong_tasks() -> None:
    with pytest.raises(rel.ReliabilityRefused):
        rel.population_all_k({"t1": (3, 5), "t2": (1, 1)}, k=2, weights={"t1": 1.0, "t2": 1.0})


def test_population_all_k_refuses_a_non_positive_weight() -> None:
    with pytest.raises(rel.ReliabilityRefused):
        rel.population_all_k({"t1": (3, 5)}, k=2, weights={"t1": 0.0})


def test_population_all_k_refuses_a_nan_weight() -> None:
    """Cross-model review, #273: `w <= 0` is False for NaN (every comparison
    with NaN is), so a NaN weight used to slide past the positivity guard and
    silently produce a NaN mean - a population that reads as 'measured' while
    reporting a value that is not a number."""
    with pytest.raises(rel.ReliabilityRefused):
        rel.population_all_k({"t1": (3, 5)}, k=2, weights={"t1": float("nan")})
    with pytest.raises(rel.ReliabilityRefused):
        rel.population_all_k({"t1": (3, 5)}, k=2, weights={"t1": float("inf")})


def test_pooled_all_k_always_refuses() -> None:
    with pytest.raises(rel.ReliabilityRefused):
        rel.pooled_all_k()
    with pytest.raises(rel.ReliabilityRefused):
        rel.pooled_all_k(1, 2, 3)


# --------------------------------------------------------------- Clopper-Pearson

@pytest.mark.parametrize(
    "c, n, lower, upper",
    [
        (0, 10, 0.0, 0.3085),
        (5, 10, 0.1871, 0.8129),
        (10, 10, 0.6915, 1.0),
    ],
)
def test_clopper_pearson_matches_textbook_values(c: int, n: int, lower: float, upper: float) -> None:
    got_lower, got_upper = rel.clopper_pearson(c, n)
    assert got_lower == pytest.approx(lower, abs=1e-4)
    assert got_upper == pytest.approx(upper, abs=1e-4)


def test_clopper_pearson_is_symmetric_around_half() -> None:
    lower, upper = rel.clopper_pearson(5, 10)
    assert lower == pytest.approx(1 - upper, abs=1e-9)


def test_clopper_pearson_refuses_zero_trials() -> None:
    with pytest.raises(rel.ReliabilityRefused):
        rel.clopper_pearson(0, 0)


@pytest.mark.parametrize("bad_confidence", [2.0, 0.0, 1.0, -0.5, float("nan"), float("inf")])
def test_confidence_is_validated_everywhere_it_is_accepted(bad_confidence: float) -> None:
    """Cross-model review, #273: `clopper_pearson(5, 10, confidence=2)` used
    to silently return `(0.0, 1.0)` - a degenerate, maximally-wide interval
    that reads as a real answer rather than a refused impossible request.
    `wilson_score` feeds `newcombe_hybrid_interval`, so checking it there
    covers both; `task_cluster_bootstrap` computes alpha independently and
    needs its own check."""
    with pytest.raises(rel.ReliabilityRefused):
        rel.clopper_pearson(5, 10, confidence=bad_confidence)
    with pytest.raises(rel.ReliabilityRefused):
        rel.wilson_score(5, 10, confidence=bad_confidence)
    with pytest.raises(rel.ReliabilityRefused):
        rel.task_cluster_bootstrap([0.1, 0.2, 0.3, 0.4, 0.5], seed=1, confidence=bad_confidence)


def test_bootstrap_refuses_a_non_positive_resample_count() -> None:
    with pytest.raises(rel.ReliabilityRefused):
        rel.task_cluster_bootstrap([0.1, 0.2, 0.3, 0.4, 0.5], seed=1, resamples=0)


# ----------------------- independent exact oracle for the incomplete beta function
#
# `rel._betainc` has no stdlib closed form and is computed from a continued
# fraction (Numerical Recipes 6.4) - numerics the textbook spot-checks above
# cannot rule out a subtle error in. This oracle computes the SAME
# mathematical quantity by a completely different, EXACT route: for integer
# a=k, b=n-k+1, I_x(a, b) equals P(Binomial(n, x) >= k), which is just a sum
# of binomial terms - computable exactly with `math.comb` and
# `fractions.Fraction`, no numerics at all. The two must agree; if they
# don't, the continued-fraction implementation is wrong, not the oracle.

from fractions import Fraction


def _binomial_pmf_table_exact(n: int, x: Fraction) -> list[Fraction]:
    """`[P(Bin(n, x) = j) for j in range(n + 1)]`, exact. Built by the
    standard recurrence `pmf[j] = pmf[j-1] * (n-j+1)/j * x/(1-x)` rather than
    `n` independent calls to `math.comb` and `Fraction.__pow__`, so computing
    the whole table once per `(n, x)` is cheap enough for a `n<=60` grid."""
    one_minus_x = 1 - x
    if one_minus_x == 0:
        return [Fraction(0)] * n + [Fraction(1)]
    pmf = [one_minus_x ** n]
    ratio = x / one_minus_x
    for j in range(1, n + 1):
        pmf.append(pmf[-1] * Fraction(n - j + 1, j) * ratio)
    return pmf


def _binomial_sf_exact(n: int, k: int, x: Fraction) -> Fraction:
    """`P(Bin(n, x) >= k)`, exact - this IS `I_x(k, n-k+1)` for integer `k`."""
    if k <= 0:
        return Fraction(1)
    if k > n:
        return Fraction(0)
    return sum(_binomial_pmf_table_exact(n, x)[k:], start=Fraction(0))


def _binomial_cdf_exact(n: int, k: int, x: Fraction) -> Fraction:
    """`P(Bin(n, x) <= k)`, exact."""
    if k < 0:
        return Fraction(0)
    if k >= n:
        return Fraction(1)
    return sum(_binomial_pmf_table_exact(n, x)[: k + 1], start=Fraction(0))


#: ~20 points, including near-0 and near-1 where the continued fraction's two
#: symmetry branches (`x < (a+1)/(a+b+2)` in `rel._betainc`) are each
#: exercised, and both sides of `x=0.5`.
_GRID_X = [Fraction(i, 1000) for i in (1, 2, 5, 10, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950, 980, 990, 995, 998, 999)]


def test_betainc_matches_exact_binomial_tail_oracle_on_a_grid() -> None:
    """`n` in 1..60, every `k` in 0..n, ~20 `x` points: `rel._betainc(x, k,
    n-k+1)` must equal the exact binomial survival function to within 1e-10,
    everywhere on the grid - not spot-checked, the WHOLE grid asserted in one
    run, because a near-miss region bad enough to matter could sit between
    textbook spot-check points."""
    mismatches = []
    for n in range(1, 61):
        for x in _GRID_X:
            x_float = float(x)
            for k in range(n + 1):
                a, b = k, n - k + 1
                got = rel._betainc(x_float, a, b)
                want = float(_binomial_sf_exact(n, k, x))
                if abs(got - want) > 1e-10:
                    mismatches.append((n, k, x_float, got, want))
    assert not mismatches, f"{len(mismatches)} grid mismatches, first 5: {mismatches[:5]}"


def test_betainc_endpoint_boundary_at_a_zero_and_b_zero() -> None:
    """Cross-model review, #273: the grid above deliberately excludes `x=0`
    and `x=1` (`_GRID_X` runs 0.001..0.999), so it could not see that the
    FIRST fix for `a==0`/`b==0` still branched on `x` and got these two exact
    endpoints backwards - `_betainc(0.0, 0, 11)` returned `0.0` where the
    binomial reading (`P(Bin(n, 0) >= 0)`, always true) says `1.0`, and
    `_betainc(1.0, 5, 0)` returned `1.0` where `P(Bin(n, 1) >= n+1)` (never
    true) says `0.0`. Checked directly, at the exact endpoints the grid never
    reaches."""
    assert rel._betainc(0.0, 0, 11) == 1.0
    assert rel._betainc(1.0, 0, 11) == 1.0
    assert rel._betainc(0.5, 0, 11) == 1.0
    assert rel._betainc(1.0, 5, 0) == 0.0
    assert rel._betainc(0.0, 5, 0) == 0.0
    assert rel._betainc(0.5, 5, 0) == 0.0


@pytest.mark.parametrize("n", [100, 250, 500, 1000])
def test_betainc_matches_oracle_at_large_n_spot_rows(n: int) -> None:
    """The grid test above stops at `n=60`; convergence is a function of
    `(x, a, b)`, not just `x`, so nothing in that grid establishes that the
    continued fraction still converges to the right answer at the `n` a real
    multi-task study could plausibly schedule (orchestrator review, #273:
    "nothing shows the CORRECT branch converges at, say, n=200 or 1000").
    `c` at `0, 1, n//2, n-1, n`, each checked against `x` chosen to keep the
    comparison INFORMATIVE - the task's own rate (`c/n`) and the two
    Clopper-Pearson tail points (0.001, 0.999), not a single fixed `x` that
    would silently underflow both sides to the same float zero for an
    extreme `(n, c)` pair and pass for the wrong reason."""
    mismatches = []
    for c in sorted({0, 1, n // 2, n - 1, n}):
        a, b = c, n - c + 1
        rate = Fraction(c, n)
        for x in {rate, Fraction(1, 1000), Fraction(999, 1000), Fraction(1, 2)}:
            if not (0 < x < 1):
                continue
            got = rel._betainc(float(x), a, b)
            want = float(_binomial_sf_exact(n, c, x))
            if abs(got - want) > 1e-9:
                mismatches.append((n, c, float(x), got, want))
    assert not mismatches, f"{len(mismatches)} mismatches at n={n}: {mismatches[:5]}"


def test_betacf_refuses_rather_than_return_an_unconverged_value() -> None:
    """Cross-model review, #273: the continued fraction used to return `h`
    even when all 200 iterations ran without the convergence break firing -
    an unverified number indistinguishable, by inspection, from a correct
    one. `a = b = 1e7` is a committed, concrete input that genuinely exhausts
    200 iterations without converging (verified directly, not asserted on
    faith) - far past this module's verified range (the oracle grid through
    `n=60`, spot rows through `n=1000`), which is exactly the point: this is
    the floor under that range, the input that proves the refusal exists
    rather than merely describing it."""
    with pytest.raises(rel.ReliabilityRefused, match="did not converge"):
        rel._betainc(0.5, 1e7, 1e7)


def test_clopper_pearson_inversion_matches_exact_binomial_oracle() -> None:
    """The bounds `clopper_pearson` returns are not merely plausible-looking
    numbers: `L` and `U` must satisfy the DEFINING property of the exact
    interval, `P(Bin(n, L) >= c) = alpha/2` and `P(Bin(n, U) <= c) = alpha/2`,
    checked against the SAME exact oracle as the grid test above - not
    against `clopper_pearson`'s own internals, which would prove nothing.

    THE RANGE MATTERS (orchestrator review, #273): this test originally ran
    `n` up to 40 only, and BOTH committed mutations of `_betainc` (the
    flipped symmetry branch, the perturbed continued-fraction coefficient)
    left it GREEN - not because the check was circular or its tolerance too
    loose, but because the continued fraction still CONVERGES to the right
    answer under either mutation for small-to-moderate `(a, b)`; the wrong
    branch is a numerical-stability choice, not a correctness one, until `n`
    is large enough that convergence genuinely fails. Measured directly: at
    `n=60` the flipped-branch mutation sends `clopper_pearson(1, 60)`'s upper
    bound to `0.9999999999995453` (oracle: `P(Bin(60, U) <= 1) = 0.0`, not
    the `0.025` a correct bound gives) - a failure invisible at `n<=40`, in
    the exact region the grid test's own `n<=60` already covered. The range
    here now matches the grid test's for exactly that reason - a narrower
    inversion test does not test what the grid test's range actually proves.
    """
    alpha = 0.05
    for n in range(1, 61):
        for c in range(n + 1):
            lower, upper = rel.clopper_pearson(c, n)
            if c == 0:
                assert lower == 0.0
            else:
                got = float(_binomial_sf_exact(n, c, Fraction(lower).limit_denominator(10**12)))
                assert got == pytest.approx(alpha / 2.0, abs=1e-6), (c, n, "lower", lower, got)
            if c == n:
                assert upper == 1.0
            else:
                got = float(_binomial_cdf_exact(n, c, Fraction(upper).limit_denominator(10**12)))
                assert got == pytest.approx(alpha / 2.0, abs=1e-6), (c, n, "upper", upper, got)


# --------------------------------------------------------------- Wilson / Newcombe

def test_wilson_score_contains_the_point_estimate() -> None:
    lower, upper = rel.wilson_score(5, 10)
    assert lower < 0.5 < upper


def test_newcombe_hybrid_interval_zero_when_arms_are_identical() -> None:
    lower, upper = rel.newcombe_hybrid_interval(5, 10, 5, 10)
    assert lower < 0.0 < upper  # contains 0, the true difference


def test_newcombe_hybrid_interval_is_antisymmetric_under_swap() -> None:
    lower, upper = rel.newcombe_hybrid_interval(8, 10, 2, 10)
    swapped_lower, swapped_upper = rel.newcombe_hybrid_interval(2, 10, 8, 10)
    assert swapped_lower == pytest.approx(-upper, abs=1e-9)
    assert swapped_upper == pytest.approx(-lower, abs=1e-9)


# --------------------------------------------------------------- McNemar exact

def test_mcnemar_exact_hand_computed() -> None:
    # n=10, k=min(1,9)=1: cumulative = (C(10,0)+C(10,1)) * 0.5^10 = 11/1024
    # p = 2 * 11/1024 = 22/1024 = 0.021484375
    assert rel.mcnemar_exact(1, 9) == pytest.approx(22 / 1024)


def test_mcnemar_exact_is_symmetric_in_its_two_counts() -> None:
    assert rel.mcnemar_exact(1, 9) == pytest.approx(rel.mcnemar_exact(9, 1))


def test_mcnemar_exact_no_discordant_pairs_is_one() -> None:
    assert rel.mcnemar_exact(0, 0) == 1.0


def test_mcnemar_exact_balanced_discordance_is_one() -> None:
    assert rel.mcnemar_exact(5, 5) == pytest.approx(1.0)


def test_mcnemar_exact_refuses_negative_counts() -> None:
    with pytest.raises(rel.ReliabilityRefused):
        rel.mcnemar_exact(-1, 3)


def test_mcnemar_exact_does_not_overflow_on_large_balanced_counts() -> None:
    """Cross-model review, #273: `mcnemar_exact(550, 550)` used to raise
    `OverflowError` - `math.comb(1100, i)` summed over the tail is an integer
    too large for `float()`, and `0.5 ** 1100` had already underflowed to
    `0.0`, so multiplying them raised rather than returning the correct
    `1.0` for a perfectly balanced, perfectly valid input."""
    assert rel.mcnemar_exact(550, 550) == pytest.approx(1.0)
    # An unbalanced large case too - the smaller tail must still sum correctly.
    assert 0.0 < rel.mcnemar_exact(400, 700) < 1.0


# --------------------------------------------------------------- bootstrap

def test_bootstrap_refuses_below_minimum_tasks() -> None:
    with pytest.raises(rel.ReliabilityRefused):
        rel.task_cluster_bootstrap([0.1, 0.2, 0.3], seed=1)


def test_bootstrap_records_its_own_seed() -> None:
    result = rel.task_cluster_bootstrap([0.1, 0.2, 0.3, 0.4, 0.5], seed=7)
    assert result.seed == 7


def test_bootstrap_is_deterministic_given_the_same_seed() -> None:
    values = [0.9, 0.8, 0.95, 0.7, 0.85]
    first = rel.task_cluster_bootstrap(values, seed=42)
    second = rel.task_cluster_bootstrap(values, seed=42)
    assert first == second


def test_bootstrap_shuffle_invariance_same_seed_same_multiset() -> None:
    """The committed shuffle-order control CPP review asked for: the SAME
    seed and the SAME multiset of task values give the SAME interval, however
    the caller happened to order that multiset - the point estimators (mean,
    all_k) are trivially order-invariant by `sum`/`comb`, but a resampling
    procedure keyed on POSITION would not be, and this is what proves this
    one is keyed on sorted VALUE instead."""
    values = [0.9, 0.8, 0.95, 0.7, 0.85, 0.6]
    rng = random.Random(99)
    shuffled = values[:]
    rng.shuffle(shuffled)
    assert shuffled != values  # the shuffle must actually have moved something

    first = rel.task_cluster_bootstrap(values, seed=42)
    second = rel.task_cluster_bootstrap(shuffled, seed=42)
    assert first == second


def test_bootstrap_different_seeds_can_differ() -> None:
    values = [0.9, 0.8, 0.95, 0.7, 0.85]
    first = rel.task_cluster_bootstrap(values, seed=1)
    second = rel.task_cluster_bootstrap(values, seed=2)
    # Not asserting they MUST differ (a collision is possible but vanishingly
    # unlikely with 10000 resamples); asserting the seed each records matches
    # what was asked for, which is the actual reproducibility contract.
    assert first.seed == 1
    assert second.seed == 2


# --------------------------------------------------------------- account_cell

AR = rel.AttemptRecord


def test_account_cell_hand_computed() -> None:
    acct = rel.account_cell([
        AR("a1", "PASS", True),
        AR("a2", "FAIL", True),
        AR("a3", "UNAVAILABLE", False),
    ])
    assert acct.scheduled == 3
    assert acct.started == 2
    assert acct.evaluable == 2
    assert acct.c == 1
    assert acct.coverage == {"UNAVAILABLE": 1, "INCONCLUSIVE": 0, "NOT_RUN": 0}
    assert acct.evaluable_ids == ("a1", "a2")


def test_account_cell_zero_population() -> None:
    acct = rel.account_cell([])
    assert acct.scheduled == 0
    assert acct.started == 0
    assert acct.evaluable == 0
    assert acct.c == 0
    assert acct.evaluable_ids == ()


def test_account_cell_retry_fills_the_slot() -> None:
    """duplicate/retry control: a retry is a NEW attempt_id in the SAME slot
    - it must not double-count the slot as scheduled twice, and the retry's
    own PASS must be what the slot reports."""
    acct = rel.account_cell([
        AR("a4", "UNAVAILABLE", False),
        AR("a5", "PASS", True, retry_of="a4"),
    ])
    assert acct.scheduled == 1  # one slot, not two
    assert acct.started == 1  # the retry started
    assert acct.evaluable == 1
    assert acct.c == 1
    assert acct.evaluable_ids == ("a5",)  # the retry's own id, not the original's


def test_account_cell_retry_cannot_select_a_better_outcome() -> None:
    """A retry that is ALSO unavailable leaves the slot in coverage - a
    retry can fill a slot, never upgrade a result that was never achieved."""
    acct = rel.account_cell([
        AR("a6", "UNAVAILABLE", False),
        AR("a7", "UNAVAILABLE", False, retry_of="a6"),
    ])
    assert acct.scheduled == 1
    assert acct.evaluable == 0
    assert acct.coverage["UNAVAILABLE"] == 1


def test_account_cell_refuses_duplicate_attempt_id() -> None:
    with pytest.raises(rel.ReliabilityRefused):
        rel.account_cell([AR("x", "PASS", True), AR("x", "FAIL", True)])


def test_account_cell_refuses_self_retry() -> None:
    with pytest.raises(rel.ReliabilityRefused):
        rel.account_cell([AR("y", "PASS", True, retry_of="y")])


def test_account_cell_refuses_a_dangling_retry_of() -> None:
    """Cross-model review, #273: `retry_of` naming an attempt NOT present in
    this same call's population used to be silently treated as "no parent,
    so this must be a root" - a retry whose own original went missing
    reported as a complete, started, evaluated slot instead of a refused
    account."""
    with pytest.raises(rel.ReliabilityRefused):
        rel.account_cell([AR("retry", "PASS", True, retry_of="missing")])


def test_account_cell_missing_data_is_never_silently_imputed() -> None:
    """missing-data control: a status outside the closed vocabulary - the
    shape an unclassified or missing observation would take - is REFUSED, not
    silently scored as PASS, FAIL, or dropped from the count. protocol.md:
    "Missing data is never imputed as success or failure.\""""
    with pytest.raises(rel.ReliabilityRefused):
        rel.account_cell([AR("z", "UNKNOWN", False)])
    with pytest.raises(rel.ReliabilityRefused):
        rel.account_cell([AR("z", "", False)])  # type: ignore[arg-type]
