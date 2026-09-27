"""Pre-spend cost estimation and the spend gate (#26, mirrors #12/ADR 0005's
cost-stop ruling one level down: a bounded selection-probe pilot, not the
first full matched pilot #12 owns).

ADR 0005 rule 5: "Filing an issue, or merging planning documents... never
authorizes a paid model call... Without an approved budget, the run manifest
is prepared and execution is reported incomplete, never silently skipped or
approximated." This module is that boundary, made structural rather than a
convention nobody happens to violate yet: `estimate()` computes a number from
stated assumptions, and `authorize()` is the ONLY function in this package
that may say a live run may proceed - it refuses on anything short of an
explicit, sufficient, human-approved budget UNDER the operator's own ceiling.

`estimate()`'s inputs are themselves assumptions, not measurements: no
attempt has run, so there is nothing to measure yet. Every assumed value is
named in `RunCostEstimate.assumptions` so a reader (or `master`) can see
exactly what would have to be wrong for the number to be wrong, rather than
trusting a bare dollar figure.

**The $5 ceiling (operator ruling, relayed 2026-09-26 via master, msg 1401/
1402): "don't worry about the cost estimate... i expect it's under $5."**
`authorize()` refuses ANY estimate over `CEILING_USD`, even one an operator
would otherwise approve a larger budget for - the ceiling and the approved
budget are two independent refusals, and either alone is enough to stop a
run. What this module does NOT do: track spend DURING a live run and stop it
mid-flight when it crosses the ceiling. That needs the attempt loop itself
(`skillc/trial.py`'s controller, once #10's Docker backend implementation
lands - #77's follow-up PR), which does not exist yet; every `execute()` body
on the real backend still raises `NotImplementedError`. This module's ceiling
is the pre-run refusal ADR 0005 and the operator both ask for; a running-spend
stop is owed to that later work, named here rather than silently assumed
covered.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: The operator's own ceiling for the whole paid run (msg 1401/1402), not
#: merely a budget someone could approve past. `authorize()` refuses above
#: this regardless of `approved_budget_usd`.
CEILING_USD = 5.00


class SpendNotAuthorized(Exception):
    """No live run may start: refused, not silently skipped or approximated
    (ADR 0005 rule 5)."""


def _finite_nonnegative(value: float, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        raise ValueError(f"{what} must be a finite number, not {value!r}")
    if value < 0:
        raise ValueError(f"{what} must not be negative, got {value!r}")


@dataclass(frozen=True)
class ModelPrice:
    """Public per-token pricing for one model, with its source recorded -
    this number is looked up, not remembered, and a reader must be able to
    check it against the same source later."""

    name: str
    input_usd_per_million: float
    output_usd_per_million: float
    source: str

    def __post_init__(self) -> None:
        _finite_nonnegative(self.input_usd_per_million, "input_usd_per_million")
        _finite_nonnegative(self.output_usd_per_million, "output_usd_per_million")


@dataclass(frozen=True)
class RunCostEstimate:
    """The result of `estimate()`: a number, and everything it assumed to
    get there. Never trusted as a measurement - `approved_budget_usd` in
    `authorize()` is compared against `estimated_usd`, which is a projection,
    not an observed cost."""

    trials: int
    attempts_per_trial: int
    total_attempts: int
    price: ModelPrice
    estimated_input_tokens_per_attempt: int
    estimated_output_tokens_per_attempt: int
    estimated_usd: float
    assumptions: dict[str, str] = field(default_factory=dict)
    #: 0 (deterministic tier only, the default - #69's own tiers 2/3 cost
    #: nothing extra unless explicitly enabled), 1 or 2 judge tiers enabled.
    #: Each enabled tier makes its own paid call per attempt (#69 ADR 0005:
    #: "two paid judge calls per trial when both are enabled").
    judge_tiers_enabled: int = 0
    judge_calls_total: int = 0
    judge_price: ModelPrice | None = None


def estimate(
    trials: int,
    attempts_per_trial: int,
    estimated_input_tokens_per_attempt: int,
    estimated_output_tokens_per_attempt: int,
    price: ModelPrice,
    assumptions: dict[str, str] | None = None,
    judge_tiers_enabled: int = 0,
    judge_price: ModelPrice | None = None,
    estimated_judge_input_tokens_per_call: int = 0,
    estimated_judge_output_tokens_per_call: int = 0,
) -> RunCostEstimate:
    """A pure projection: `trials * attempts_per_trial` paid AGENT
    invocations, each estimated at the given input/output token counts,
    priced at `price` - plus, when `judge_tiers_enabled` is 1 or 2 (#69's
    same-model and independent tiers), one paid JUDGE call per enabled tier
    PER ATTEMPT, each estimated separately at `judge_price` and its own
    token assumptions. `judge_tiers_enabled=0` (the default) reproduces this
    function's pre-#69-follow-up behavior exactly: no judge cost is added
    unless a caller explicitly enables it, matching ADR 0005's "tiers 2 and 3
    make paid model calls... a run manifest's cost estimate must count both"
    only when they are actually requested, never speculatively.

    Refuses non-positive trial/attempt counts or AGENT token estimates - a
    "free" estimate from a zero is the same silent-empty-population defect
    this codebase refuses elsewhere (`skillc/leak.py`, `skillc/records.py`'s
    empty-capture rule): an estimate of $0 must mean "priced at zero
    attempts", never "nothing to estimate". `judge_tiers_enabled` outside
    `{0, 1, 2}`, or judges enabled without a `judge_price` and positive judge
    token assumptions, are refused the same way - a cost enabled but not
    priced is exactly the silent gap ADR 0005 exists to close."""
    if trials < 1:
        raise ValueError(f"trials must be a positive integer, not {trials!r}")
    if attempts_per_trial < 1:
        raise ValueError(f"attempts_per_trial must be a positive integer, not {attempts_per_trial!r}")
    if estimated_input_tokens_per_attempt < 1 or estimated_output_tokens_per_attempt < 1:
        raise ValueError("estimated token counts must be positive - an attempt that spends nothing was not modeled")
    if judge_tiers_enabled not in (0, 1, 2):
        raise ValueError(f"judge_tiers_enabled must be 0, 1 or 2 (#69 has exactly two judge tiers), not {judge_tiers_enabled!r}")

    total_attempts = trials * attempts_per_trial
    input_cost = total_attempts * estimated_input_tokens_per_attempt / 1_000_000 * price.input_usd_per_million
    output_cost = total_attempts * estimated_output_tokens_per_attempt / 1_000_000 * price.output_usd_per_million

    judge_calls_total = 0
    judge_cost = 0.0
    if judge_tiers_enabled > 0:
        if judge_price is None:
            raise ValueError("judge_tiers_enabled > 0 requires judge_price - a cost enabled but not priced is refused")
        if estimated_judge_input_tokens_per_call < 1 or estimated_judge_output_tokens_per_call < 1:
            raise ValueError(
                "judge_tiers_enabled > 0 requires positive estimated_judge_input_tokens_per_call and "
                "estimated_judge_output_tokens_per_call - a judge call estimated to cost nothing was not modeled"
            )
        judge_calls_total = total_attempts * judge_tiers_enabled
        judge_input_cost = judge_calls_total * estimated_judge_input_tokens_per_call / 1_000_000 * judge_price.input_usd_per_million
        judge_output_cost = judge_calls_total * estimated_judge_output_tokens_per_call / 1_000_000 * judge_price.output_usd_per_million
        judge_cost = judge_input_cost + judge_output_cost

    return RunCostEstimate(
        trials=trials,
        attempts_per_trial=attempts_per_trial,
        total_attempts=total_attempts,
        price=price,
        estimated_input_tokens_per_attempt=estimated_input_tokens_per_attempt,
        estimated_output_tokens_per_attempt=estimated_output_tokens_per_attempt,
        # Never rounded: authorize() compares this exactly against a budget
        # and the $5 ceiling, and rounding a tiny positive cost down to
        # 0.0000 would let it authorize against a budget of $0 (Codex
        # code-review finding on #26). Round only for DISPLAY, never here.
        estimated_usd=input_cost + output_cost + judge_cost,
        assumptions=dict(assumptions or {}),
        judge_tiers_enabled=judge_tiers_enabled,
        judge_calls_total=judge_calls_total,
        judge_price=judge_price if judge_tiers_enabled > 0 else None,
    )


def authorize(cost: RunCostEstimate, approved_budget_usd: float | None) -> None:
    """The only function in this module that may say a live run may
    proceed. Raises `SpendNotAuthorized` when:

    - the estimate itself exceeds `CEILING_USD` - the operator's own ceiling,
      refused regardless of any approved budget (msg 1401/1402);
    - `approved_budget_usd` is `None` (no budget was ever approved - the
      ADR 0005 default), non-finite, or negative - a NaN budget must not
      silently pass the `<` comparison below (Codex code-review finding);
    - `approved_budget_usd` is less than `cost.estimated_usd`.

    Never rounds, waives, or silently caps the run to fit an insufficient
    budget: the estimate and the approval are two independent numbers, and a
    caller narrowing the run to match an insufficient budget would be
    approximating the very spend this gate exists to keep explicit."""
    if cost.estimated_usd > CEILING_USD:
        raise SpendNotAuthorized(
            f"estimated cost ${cost.estimated_usd:.4f} exceeds the ${CEILING_USD:.2f} operator ceiling "
            f"for the whole run - refused regardless of any approved budget"
        )
    if approved_budget_usd is None:
        raise SpendNotAuthorized(
            f"no budget has been approved; estimated cost is ${cost.estimated_usd:.4f} for "
            f"{cost.total_attempts} attempt(s) - the run manifest is prepared, execution stays incomplete"
        )
    if isinstance(approved_budget_usd, bool) or math.isnan(approved_budget_usd) or math.isinf(approved_budget_usd) or approved_budget_usd < 0:
        raise SpendNotAuthorized(f"approved_budget_usd must be a finite, non-negative number, not {approved_budget_usd!r}")
    if approved_budget_usd < cost.estimated_usd:
        raise SpendNotAuthorized(
            f"approved budget ${approved_budget_usd:.4f} is less than the ${cost.estimated_usd:.4f} "
            f"estimate for {cost.total_attempts} attempt(s)"
        )
