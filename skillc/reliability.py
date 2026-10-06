"""Repeat-reliability and declared-interval statistics (issue #273).

protocol.md section 10.5 ("Repeats, intervals and accounting") and 10.6
("Convenience proxies") - delivered by #264 as the frozen, predeclared default
method - define exactly what this module computes and nothing more. It picks
no method #264 did not already name, and names no rule #264 left open: where
#264 states none (a per-arm PASS/FAIL reduction over repeated attempts,
"discriminating" itself), this module refuses to invent one rather than
silently defaulting (skillc #273's own scope note; cpp-eval review).

Stdlib only (AGENTS.md): no external statistics runtime. The one function
with no stdlib closed form - the Beta distribution's quantile, which
Clopper-Pearson needs - is implemented from the regularized incomplete beta
function (`math.lgamma` plus a continued fraction, Numerical Recipes 6.4)
inverted by bisection. Correct to within `_BETA_PPF_TOL` of the true
quantile, verified against textbook Clopper-Pearson tables in
`tests/test_reliability.py`, never against a second implementation of the
same approximation.

THE UNIT OF REPEATED EVIDENCE IS THE TASK, NEVER THE ATTEMPT (protocol.md
10.5: "Repeats of one task are not independent evidence about other tasks").
Every population-level function here resamples or averages over TASKS, with
per-task reliability computed first and never attempts pooled across tasks
directly - `pooled_all_k` refuses exactly the shape protocol.md names as
wrong ("A pooled success rate across heterogeneous tasks is never raised to
the k-th power").
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist

#: The declared default confidence level (protocol.md 10.5: "95% two-sided").
DEFAULT_CONFIDENCE = 0.95

#: all-k / pass-at-k / population-all-k return this, never 0, when n < k -
#: protocol.md 10.5: "With n < k the cell reports `insufficient`, never 0."
INSUFFICIENT = "insufficient"

#: The task-cluster bootstrap's own minimum population (protocol.md 10.5:
#: "only with at least 5 tasks. With fewer, only per-task results are
#: reported, because 2 or 3 tasks cannot support a population interval").
MIN_BOOTSTRAP_TASKS = 5

#: The bootstrap's declared resample count (protocol.md 10.5: "10000
#: resamples").
DEFAULT_BOOTSTRAP_RESAMPLES = 10000


class ReliabilityRefused(ValueError):
    """A statistic was asked for over input protocol.md's own method refuses -
    insufficient population, an undeclared method, or a shape this module was
    never asked to invent (#273's scope fence)."""


def _refuse(message: str) -> ReliabilityRefused:
    return ReliabilityRefused(f"reliability: {message}")


def _check_confidence(confidence: float) -> None:
    """Every interval function's `confidence` must be a finite probability
    strictly between 0 and 1 (cross-model review, #273): an unchecked
    `confidence=2` silently returned `(0.0, 1.0)` from `clopper_pearson` -
    a degenerate, maximally-wide interval that LOOKS like a real answer
    rather than a refused impossible request."""
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) \
            or not math.isfinite(confidence) or not (0.0 < confidence < 1.0):
        raise _refuse(f"confidence must be a finite number strictly between 0 and 1, not {confidence!r}")


def _check_c_n_k(c: int, n: int, k: int) -> None:
    for name, value in (("c", c), ("n", n), ("k", k)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise _refuse(f"{name} must be an integer, not {value!r}")
    if n < 0:
        raise _refuse(f"n must be non-negative, not {n!r}")
    if not (0 <= c <= n):
        raise _refuse(f"c must satisfy 0 <= c <= n; got c={c!r}, n={n!r}")
    if k < 1:
        raise _refuse(f"k must be a positive integer, not {k!r}")


def all_k(c: int, n: int, k: int) -> float | str:
    """The declared per-task all-k estimator (protocol.md 10.5): the
    probability that ALL of k attempts drawn without replacement from this
    task's n evaluable attempts succeed, given c of them did -
    `C(c, k) / C(n, k)`.

    Returns `INSUFFICIENT`, never `0`, when `n < k`: a task that was not
    attempted enough times to even ask the question is a different fact from
    one that was asked and failed every time.

    Distinct from `pass_at_k` (which REWARDS occasional success, protocol.md's
    own words) by construction: this function and that one share no code, so
    a bug in one cannot silently make it compute the other.
    """
    _check_c_n_k(c, n, k)
    if n < k:
        return INSUFFICIENT
    return math.comb(c, k) / math.comb(n, k)


def pass_at_k(c: int, n: int, k: int) -> float | str:
    """`1 - C(n-c, k) / C(n, k)` (protocol.md 10.5): the probability that AT
    LEAST ONE of k attempts drawn without replacement succeeds. Rewards
    occasional success, which is exactly why protocol.md requires `all_k` and
    this to be computed and labelled separately, never substituted for each
    other. Same `INSUFFICIENT` rule as `all_k` when `n < k`.
    """
    _check_c_n_k(c, n, k)
    if n < k:
        return INSUFFICIENT
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


@dataclass(frozen=True)
class PopulationAllK:
    """The declared-weight mean of per-task all-k over tasks with `n >= k`
    (protocol.md 10.5). `excluded` names every task left out for insufficient
    `n`, never silently dropped. Equal weighting is the default; a study may
    declare other weights, but never silently - `weights` must then name
    every included task explicitly."""

    mean: float | None
    per_task: Mapping[str, float]
    excluded: tuple[str, ...]


def population_all_k(
    per_task_cn: Mapping[str, tuple[int, int]], k: int, weights: Mapping[str, float] | None = None,
) -> PopulationAllK:
    """`per_task_cn` maps a task id to its own `(c, n)`. Computes `all_k` per
    task, then the declared-weight mean over tasks with `n >= k` - equal
    weights by default (protocol.md 10.5: "equal weights by default").

    A task with `n < k` is EXCLUDED from the mean and named in `excluded`,
    never scored as 0 and never silently missing. An empty `per_task_cn`, or
    one where every task is excluded, yields `mean=None` - an empty
    population is a fact to report, not a `0.0` that reads as "measured and
    found lacking" (AGENTS.md).

    `weights`, when given, must name EXACTLY the set of tasks whose `n >= k`
    (not the full `per_task_cn` population, which may include excluded
    tasks it cannot weight) and must be positive; this function does not
    renormalize a partial or malformed weight map - that would silently
    change what was declared.
    """
    per_task: dict[str, float] = {}
    excluded: list[str] = []
    for task_id, (c, n) in per_task_cn.items():
        value = all_k(c, n, k)
        if value == INSUFFICIENT:
            excluded.append(task_id)
        else:
            per_task[task_id] = value  # type: ignore[assignment]

    if not per_task:
        return PopulationAllK(mean=None, per_task=per_task, excluded=tuple(sorted(excluded)))

    if weights is None:
        mean = sum(per_task.values()) / len(per_task)
    else:
        if set(weights) != set(per_task):
            raise _refuse(
                f"weights names {sorted(weights)}, but the tasks with n >= k are "
                f"{sorted(per_task)} - a declared weight map must name exactly that set"
            )
        if any(not math.isfinite(w) or w <= 0 for w in weights.values()):
            # `nan <= 0` is False (every comparison with NaN is), so a plain
            # `w <= 0` guard lets a NaN weight straight through and silently
            # produces a NaN mean (cross-model review, #273) - `math.isfinite`
            # catches both NaN and +-inf, which `<= 0` alone cannot.
            raise _refuse("every declared weight must be a finite, positive number")
        total_weight = sum(weights.values())
        mean = sum(weights[t] * per_task[t] for t in per_task) / total_weight

    return PopulationAllK(mean=mean, per_task=per_task, excluded=tuple(sorted(excluded)))


def pooled_all_k(*_args: object, **_kwargs: object) -> None:
    """Refuses unconditionally. protocol.md 10.5: "A pooled success rate
    across heterogeneous tasks is never raised to the k-th power." There is
    no correct implementation of this function - it exists only so that
    reaching for "the pooled version" finds a named refusal instead of
    silence or a plausible-looking wrong answer."""
    raise _refuse(
        "a pooled success rate across heterogeneous tasks is never raised to the k-th "
        "power (protocol.md 10.5) - use population_all_k, which averages PER-TASK all_k"
    )


# ---------------------------------------------------------------------------
# Intervals (protocol.md 10.5: "95% two-sided")
# ---------------------------------------------------------------------------

_BETA_PPF_TOL = 1e-12
_BETA_PPF_MAX_ITER = 200


def _betacf(x: float, a: float, b: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical
    Recipes 3rd ed., section 6.4). Pure stdlib (`math` only)."""
    max_iter, eps, fpmin = 200, 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    else:
        # The loop ran every iteration WITHOUT the convergence break firing
        # (cross-model review, #273): silently returning `h` here hands
        # `_beta_ppf`'s bisection an UNVERIFIED value that merely looks
        # precise - no caller could tell a converged answer from a stale one
        # by inspection. Large, nearly-balanced `(a, b)` near the branch
        # threshold can need more than `max_iter` terms; refusing here, named
        # by the actual `(x, a, b)` that failed, is what keeps every value
        # this module returns either correct or absent, never merely
        # plausible-looking. `clopper_pearson`'s own two calls never reach
        # `n` large enough to trigger this at `max_iter=200` within the
        # explicitly verified range (`tests/test_reliability.py`'s oracle
        # grid plus spot rows through `n=1000`) - this is the floor under
        # that range, not a bound this module claims never to need.
        raise _refuse(
            f"the continued fraction for the incomplete beta function did not converge "
            f"within {max_iter} iterations at x={x!r}, a={a!r}, b={b!r} - refusing rather "
            f"than returning an unverified value"
        )
    return h


def _betainc(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function `I_x(a, b)`, for `x` in `[0, 1]`.

    `a == 0` or `b == 0` is a degenerate Beta - undefined as a density, but
    `I_x` still has a well-defined value at these boundary parameters via its
    binomial-survival reading (`I_x(k, n-k+1) = P(Bin(n,x) >= k)`): `a == 0`
    is "at least 0 successes", which is trivially true for EVERY `x`
    including `x == 0` (`Bin(n, 0)` is always exactly 0 successes, and `0 >=
    0`), so `1.0` unconditionally; `b == 0` is "more successes than trials",
    which is never true for any `x` including `x == 1` (`Bin(n, 1)` is always
    exactly `n` successes, never `n+1`), so `0.0` unconditionally. The first
    version of this fix still branched on `x` at these boundaries and got the
    `x == 0` / `x == 1` endpoints backwards (cross-model review, #273):
    `_betainc(0.0, 0, 11)` returned `0.0` where the binomial reading - and the
    independent oracle - both say `1.0`. Neither of `clopper_pearson`'s own
    two calls ever reaches `a == 0` or `b == 0` - `_beta_ppf` is only called
    with `a = c >= 1` or `b = n - c >= 1` - but `tests/test_reliability.py`'s
    independent oracle exercises the FULL `k` range (`k = 0..n`) directly
    against this function, and found both gaps before they could matter
    (#273, cpp-eval review's own ask for an exact-oracle grid)."""
    if a == 0:
        return 1.0
    if b == 0:
        return 0.0
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(x, a, b) / a
    return 1.0 - front * _betacf(1.0 - x, b, a) / b


def _beta_ppf(p: float, a: float, b: float) -> float:
    """Quantile (inverse CDF) of `Beta(a, b)` at probability `p`, by
    bisection over `_betainc` - the one piece of this module with no closed
    form, so this is the one function with a numerical tolerance rather than
    an exact result."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(_BETA_PPF_MAX_ITER):
        mid = (lo + hi) / 2.0
        if _betainc(mid, a, b) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < _BETA_PPF_TOL:
            break
    return (lo + hi) / 2.0


def clopper_pearson(c: int, n: int, confidence: float = DEFAULT_CONFIDENCE) -> tuple[float, float]:
    """Exact two-sided Clopper-Pearson interval for `c` successes of `n`
    trials (protocol.md 10.5: "a single cell's rate: Clopper-Pearson exact").
    `n == 0` is refused - an empty cell has no rate to bound.

    VERIFIED RANGE (orchestrator review, #273): checked against an
    independent exact oracle (`fractions.Fraction`, no numerics) for every
    `n` from 1 to 60 and every `c` in that range at `tests/test_reliability.
    py`'s grid test, and spot-checked at `n = 100, 250, 500, 1000` (`c` at
    `0, 1, n//2, n-1, n`). Beyond that range this function has not been
    checked against the oracle, though `_betacf` refuses outright rather than
    return a value when its own continued fraction fails to converge within
    200 iterations (verified concretely at `a = b = 1e7`, far past any `n`
    this function would plausibly see) - so a result from `n` outside the
    verified range is either correct or absent, never merely unchecked and
    silently returned.
    """
    if n <= 0:
        raise _refuse(f"clopper_pearson needs n >= 1, not n={n!r}")
    if not (0 <= c <= n):
        raise _refuse(f"c must satisfy 0 <= c <= n; got c={c!r}, n={n!r}")
    _check_confidence(confidence)
    alpha = 1.0 - confidence
    lower = 0.0 if c == 0 else _beta_ppf(alpha / 2.0, c, n - c + 1)
    upper = 1.0 if c == n else _beta_ppf(1.0 - alpha / 2.0, c + 1, n - c)
    return lower, upper


def wilson_score(c: int, n: int, confidence: float = DEFAULT_CONFIDENCE) -> tuple[float, float]:
    """Wilson score interval for `c` successes of `n` trials - the per-arm
    building block `newcombe_hybrid_interval` combines; not itself one of
    protocol.md 10.5's named intervals, but each named interval it composes
    into is."""
    if n <= 0:
        raise _refuse(f"wilson_score needs n >= 1, not n={n!r}")
    if not (0 <= c <= n):
        raise _refuse(f"c must satisfy 0 <= c <= n; got c={c!r}, n={n!r}")
    _check_confidence(confidence)
    z = NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)
    phat = c / n
    denom = 1.0 + z * z / n
    center = phat + z * z / (2.0 * n)
    margin = z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))
    return (center - margin) / denom, (center + margin) / denom


def newcombe_hybrid_interval(
    c1: int, n1: int, c2: int, n2: int, confidence: float = DEFAULT_CONFIDENCE,
) -> tuple[float, float]:
    """Newcombe's hybrid score interval for the difference between two
    INDEPENDENT arms' proportions (protocol.md 10.5: "a within-task
    difference between independent arms"), combining each arm's own
    `wilson_score` interval. This is for two independent samples (e.g.
    baseline vs. treatment on the same task), never for paired attempts -
    `mcnemar_exact` is the paired test, and a hypothesis test, not an
    interval (protocol.md's own distinction)."""
    p1, p2 = c1 / n1, c2 / n2
    l1, u1 = wilson_score(c1, n1, confidence)
    l2, u2 = wilson_score(c2, n2, confidence)
    diff = p1 - p2
    lower = diff - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = diff + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return lower, upper


def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar test p-value from the two DISCORDANT pair
    counts (`b`: arm 1 succeeds, arm 2 fails; `c`: the reverse) over attempts
    PAIRED by the study's own design (protocol.md 10.5: "Attempts are paired
    only where the design pairs them ... Repeat index alone is not a
    pairing"). A HYPOTHESIS TEST, never relabeled an interval - protocol.md's
    own distinction, and this function returns a bare p-value, nothing
    interval-shaped, so it cannot be mistaken for one.

    `b + c == 0` (no discordant pairs at all) returns `1.0`: nothing
    distinguishes the arms in the only pairs that could, which is maximal,
    not minimal, evidence against a difference.

    THE RATIO IS DIVIDED BEFORE IT IS SCALED (cross-model review, #273): for
    `n` above roughly 1050, `math.comb(n, i)` summed over the tail is an
    integer too large for `float()` to represent, and `0.5 ** n` has already
    underflowed to `0.0` - multiplying the huge int by that float raises
    `OverflowError` on a perfectly valid, non-degenerate input
    (`mcnemar_exact(550, 550)` is exactly such a case). Python's integer
    TRUE DIVISION of two arbitrarily large ints does not have this problem
    (it never needs either operand to fit in a `float` on its own), so the
    division happens first, while both operands are still exact integers,
    and only the already-small `float` result is scaled afterward.
    """
    if isinstance(b, bool) or isinstance(c, bool) or not isinstance(b, int) or not isinstance(c, int) or b < 0 or c < 0:
        raise _refuse(f"b and c must be non-negative integers; got b={b!r}, c={c!r}")
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    numerator = sum(math.comb(n, i) for i in range(k + 1))
    ratio = numerator / (2 ** n)  # int/int true division: exact until this line, safe at any n
    return min(1.0, 2.0 * ratio)


@dataclass(frozen=True)
class BootstrapInterval:
    """A task-cluster percentile bootstrap result. `seed` is always recorded
    (CPP review on #273: "seeded, with the seed recorded in the output"), so
    the interval is reproducible from the record alone, not just from a
    process that happened to use one."""

    seed: int
    resamples: int
    confidence: float
    lower: float
    upper: float


def task_cluster_bootstrap(
    task_values: Sequence[float],
    seed: int,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
) -> BootstrapInterval:
    """Percentile bootstrap over task-level values (e.g. each task's own
    `all_k`), resampling TASKS with replacement - never attempts, because
    repeats of one task are not independent evidence about other tasks
    (protocol.md 10.5). Refuses below `MIN_BOOTSTRAP_TASKS` tasks
    (protocol.md 10.5: "2 or 3 tasks cannot support a population interval") -
    report per-task results instead of calling this function at all.

    DETERMINISTIC IN (seed, MULTISET), not in input order: `task_values` is
    sorted before any resampling index is drawn, so two callers who pass the
    same values in a different order and the same seed get the IDENTICAL
    interval (CPP review on #273: "the same seed and the same multiset give
    the same interval" - tested by `tests/test_reliability.py`'s
    shuffle-invariance control, which exercises the bootstrap specifically,
    not only the point estimators that are trivially order-invariant).
    """
    _check_confidence(confidence)
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise _refuse(f"resamples must be a positive integer, not {resamples!r}")
    n = len(task_values)
    if n < MIN_BOOTSTRAP_TASKS:
        raise _refuse(
            f"task-cluster bootstrap needs at least {MIN_BOOTSTRAP_TASKS} tasks, got {n} "
            f"(protocol.md 10.5) - report per-task results instead"
        )
    canonical = sorted(task_values)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        means.append(sum(canonical[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    alpha = 1.0 - confidence
    lo_index = int(alpha / 2.0 * resamples)
    hi_index = min(resamples - 1, int((1.0 - alpha / 2.0) * resamples))
    return BootstrapInterval(
        seed=seed, resamples=resamples, confidence=confidence,
        lower=means[lo_index], upper=means[hi_index],
    )


# ---------------------------------------------------------------------------
# All-attempt accounting and retries (protocol.md 10.5)
# ---------------------------------------------------------------------------

#: The final-status vocabulary a slot resolves to - exactly `records.
#: PROTOCOL_STATUSES` (PASS/FAIL/UNAVAILABLE/INCONCLUSIVE/NOT_RUN), restated
#: here rather than imported so this module's own test suite can floor it
#: without importing `skillc.records`'s much larger surface for one tuple.
SLOT_STATUSES = ("PASS", "FAIL", "UNAVAILABLE", "INCONCLUSIVE", "NOT_RUN")
#: Final statuses that make a slot evaluable (protocol.md: "evaluable (PASS
#: or FAIL)"). The other three are coverage, counted separately.
EVALUABLE_STATUSES = ("PASS", "FAIL")


@dataclass(frozen=True)
class AttemptRecord:
    """One PLANNED attempt's own observed outcome, already resolved from its
    own `attempt-lifecycle`/`verified-result` (`records.derive_status`) by the
    caller - this module reads only the resolved facts, never a raw bundle.

    `retry_of`, when set, names another `AttemptRecord.attempt_id` in the SAME
    call's `attempts` sequence: protocol.md's "a slot that ended UNAVAILABLE
    before the agent's first observed turn may be retried ... the retry is a
    new attempt ID linked to the original, which stays in coverage." This
    module does not itself enforce WHEN a retry was legitimate (that a
    trial's own `retry_of` chain obeys the eligibility rule is a planning-time
    concern, `skillc/trial.py`'s); it accounts whatever chain it is given.
    """

    attempt_id: str
    status: str  # one of SLOT_STATUSES
    started: bool
    retry_of: str | None = None


@dataclass(frozen=True)
class CellAccounting:
    """One cell's (one task, one arm) all-attempt account (protocol.md 10.5:
    "Every report shows scheduled, started, evaluable ... and coverage
    counts ... per cell, with infrastructure availability separate").

    `evaluable_ids` names each evaluable SLOT's representative attempt, in
    slot order - "reliability uses the first n evaluable attempts per cell in
    slot order, so a retry can fill a slot but cannot select a better
    outcome." Passing `k` attempt ids from here into `all_k`/`pass_at_k` as
    `n` is exactly that selection, made inspectable rather than implicit.
    """

    scheduled: int
    started: int
    evaluable: int
    c: int
    coverage: Mapping[str, int]
    evaluable_ids: tuple[str, ...]


def account_cell(attempts: Sequence[AttemptRecord]) -> CellAccounting:
    """Resolve `attempts` (which may include retries) into one account per
    SLOT, then total the slots.

    A slot is a chain linked by `retry_of`; its identity is the chain's ROOT
    attempt id, and its SLOT ORDER is the order that root first appears in
    `attempts` - the only ordering this function has, and the one protocol.md
    means by "slot order" (a planned population has no other declared order
    to use). A slot's FINAL status is the first PASS/FAIL found anywhere in
    its chain (an evaluated slot does not keep retrying - `started` is never
    un-set by a later observation), or, if none, the status of the chain's
    own LAST (most-recently-added) attempt - the final non-result after
    retries are exhausted. `started` is true for a slot if ANY attempt in its
    chain started, even one later superseded by a retry: protocol.md's
    eligibility rule ("only a slot that ended UNAVAILABLE BEFORE the agent's
    first observed turn may be retried") means a slot that ever started
    should not legally have a further retry at all - this function reports
    what it is given rather than re-deriving eligibility, so a chain that
    violates the rule still reports `started=True` honestly rather than
    being silently corrected.

    Duplicate `attempt_id`s and an attempt naming its own id as `retry_of`
    are both refused: `records.py`'s own `unique-ids`/`trial-ledger` rules
    are where a real bundle catches these before this function ever sees
    them, but a caller assembling `AttemptRecord`s by hand must not get a
    silently wrong account from a malformed chain.
    """
    seen_ids: set[str] = set()
    for attempt in attempts:
        if attempt.attempt_id in seen_ids:
            raise _refuse(f"duplicate attempt_id {attempt.attempt_id!r} in one cell's accounting")
        seen_ids.add(attempt.attempt_id)
        if attempt.retry_of == attempt.attempt_id:
            raise _refuse(f"attempt {attempt.attempt_id!r} names itself as retry_of")
        if attempt.status not in SLOT_STATUSES:
            raise _refuse(f"attempt {attempt.attempt_id!r} has status {attempt.status!r}, not one of {SLOT_STATUSES}")
    for attempt in attempts:
        # A DANGLING retry_of (cross-model review, #273) silently made the
        # retry read as its OWN root - [AttemptRecord("retry", "PASS", True,
        # retry_of="missing")] accounted a complete, started, evaluated slot
        # while the "original" attempt it claims to retry is simply absent
        # from this call's own population. That is the one thing a retry can
        # never legitimately be missing - the chain names a parent in THIS
        # SAME cell's attempts (module docstring, above) - so an absent one
        # is refused here rather than silently treated as "no parent, this
        # must be a root after all".
        if attempt.retry_of is not None and attempt.retry_of not in seen_ids:
            raise _refuse(
                f"attempt {attempt.attempt_id!r} names retry_of {attempt.retry_of!r}, "
                f"which is not an attempt in this cell's own accounting"
            )

    by_id = {a.attempt_id: a for a in attempts}
    chains: dict[str, list[AttemptRecord]] = {}
    roots_in_order: list[str] = []

    def _root(attempt: AttemptRecord) -> str:
        seen: set[str] = set()
        current = attempt
        while current.retry_of is not None and current.retry_of in by_id:
            if current.attempt_id in seen:
                raise _refuse(f"retry_of chain containing {attempt.attempt_id!r} cycles")
            seen.add(current.attempt_id)
            current = by_id[current.retry_of]
        return current.attempt_id

    for attempt in attempts:
        root = _root(attempt)
        if root not in chains:
            chains[root] = []
            roots_in_order.append(root)
        chains[root].append(attempt)

    scheduled = len(roots_in_order)
    started = 0
    evaluable_ids: list[str] = []
    c = 0
    coverage: dict[str, int] = {status: 0 for status in SLOT_STATUSES if status not in EVALUABLE_STATUSES}

    for root in roots_in_order:
        chain = chains[root]
        if any(a.started for a in chain):
            started += 1
        evaluated = next((a for a in chain if a.status in EVALUABLE_STATUSES), None)
        if evaluated is not None:
            evaluable_ids.append(evaluated.attempt_id)
            if evaluated.status == "PASS":
                c += 1
        else:
            final = chain[-1]
            coverage[final.status] += 1

    return CellAccounting(
        scheduled=scheduled, started=started, evaluable=len(evaluable_ids), c=c,
        coverage=coverage, evaluable_ids=tuple(evaluable_ids),
    )
