"""Pre-spend cost estimation and the spend gate (#26, ADR 0005 rule 5).

`test_authorize_refuses_without_an_approved_budget` and
`test_authorize_refuses_an_insufficient_budget` are this module's committed
negative controls for its one gate (`authorize`): each names the concrete
input that makes the gate report the OTHER verdict from the green case
right beside it.
"""

from __future__ import annotations

import pytest

from skillc import cost_estimate as ce

PRICE = ce.ModelPrice(
    name="gpt-5.1-codex",
    input_usd_per_million=1.25,
    output_usd_per_million=10.00,
    source="pricepertoken.com, 2026-09-26 (third-party aggregator, not independently confirmed against OpenAI's own page)",
)


def test_estimate_computes_input_and_output_cost_separately():
    cost = ce.estimate(
        trials=3, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=1_000_000, estimated_output_tokens_per_attempt=1_000_000,
        price=PRICE,
    )
    assert cost.total_attempts == 3
    # 3 attempts * (1.25 input + 10.00 output) = 33.75
    assert cost.estimated_usd == pytest.approx(33.75)


def test_estimate_multiplies_trials_by_attempts_per_trial():
    cost = ce.estimate(
        trials=3, attempts_per_trial=2,
        estimated_input_tokens_per_attempt=100_000, estimated_output_tokens_per_attempt=50_000,
        price=PRICE,
    )
    assert cost.total_attempts == 6


@pytest.mark.parametrize("kwargs, why", [
    ({"trials": 0, "attempts_per_trial": 1, "estimated_input_tokens_per_attempt": 1, "estimated_output_tokens_per_attempt": 1}, "trials"),
    ({"trials": 1, "attempts_per_trial": 0, "estimated_input_tokens_per_attempt": 1, "estimated_output_tokens_per_attempt": 1}, "attempts_per_trial"),
    ({"trials": 1, "attempts_per_trial": 1, "estimated_input_tokens_per_attempt": 0, "estimated_output_tokens_per_attempt": 1}, "token counts"),
    ({"trials": 1, "attempts_per_trial": 1, "estimated_input_tokens_per_attempt": 1, "estimated_output_tokens_per_attempt": 0}, "token counts"),
])
def test_estimate_refuses_a_non_positive_input(kwargs, why):
    """Red case: an estimate of $0 must mean 'priced at zero attempts' would
    be the silent-empty-population defect this codebase refuses elsewhere -
    so a zero anywhere in the population is refused outright, never quietly
    projected."""
    with pytest.raises(ValueError, match=why):
        ce.estimate(price=PRICE, **kwargs)


def test_assumptions_are_carried_through_unmodified():
    assumptions = {"tokens_per_attempt": "estimated from CPP subject's average skill+prompt size, not measured"}
    cost = ce.estimate(
        trials=1, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=1000, estimated_output_tokens_per_attempt=1000,
        price=PRICE, assumptions=assumptions,
    )
    assert cost.assumptions == assumptions


# --------------------------------------------------------------------------
# Judge-call cost (#69 follow-up): tiers 2/3 make paid calls, counted only
# when explicitly enabled.
# --------------------------------------------------------------------------

JUDGE_PRICE = ce.ModelPrice(
    name="fake-judge-model", input_usd_per_million=2.50, output_usd_per_million=10.00, source="test",
)


def test_estimate_without_judges_matches_the_pre_69_follow_up_behavior():
    """judge_tiers_enabled=0 (the default) must add nothing - the exact
    number #26/#12's manifests already committed must not silently change
    the day this function grew judge-cost support."""
    cost = ce.estimate(
        trials=3, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=50_000, estimated_output_tokens_per_attempt=5_000,
        price=PRICE,
    )
    assert cost.judge_tiers_enabled == 0
    assert cost.judge_calls_total == 0
    assert cost.judge_price is None
    assert cost.estimated_usd == pytest.approx(3 * (50_000 / 1_000_000 * 1.25 + 5_000 / 1_000_000 * 10.00))


def test_estimate_with_one_judge_tier_adds_one_call_per_attempt():
    cost = ce.estimate(
        trials=3, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=50_000, estimated_output_tokens_per_attempt=5_000,
        price=PRICE,
        judge_tiers_enabled=1, judge_price=JUDGE_PRICE,
        estimated_judge_input_tokens_per_call=100_000, estimated_judge_output_tokens_per_call=2_000,
    )
    assert cost.judge_calls_total == 3  # 3 attempts * 1 tier
    agent_cost = 3 * (50_000 / 1_000_000 * 1.25 + 5_000 / 1_000_000 * 10.00)
    judge_cost = 3 * (100_000 / 1_000_000 * 2.50 + 2_000 / 1_000_000 * 10.00)
    assert cost.estimated_usd == pytest.approx(agent_cost + judge_cost)


def test_estimate_with_two_judge_tiers_doubles_the_judge_calls():
    cost = ce.estimate(
        trials=3, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=50_000, estimated_output_tokens_per_attempt=5_000,
        price=PRICE,
        judge_tiers_enabled=2, judge_price=JUDGE_PRICE,
        estimated_judge_input_tokens_per_call=100_000, estimated_judge_output_tokens_per_call=2_000,
    )
    assert cost.judge_calls_total == 6  # 3 attempts * 2 tiers, ADR 0005: "two paid judge calls per trial"


def test_estimate_refuses_an_invalid_judge_tier_count():
    with pytest.raises(ValueError, match="0, 1 or 2"):
        ce.estimate(
            trials=1, attempts_per_trial=1,
            estimated_input_tokens_per_attempt=1000, estimated_output_tokens_per_attempt=1000,
            price=PRICE, judge_tiers_enabled=3,
        )


def test_estimate_refuses_judges_enabled_with_no_judge_price():
    """A cost enabled but not priced is refused - the silent gap ADR 0005
    exists to close."""
    with pytest.raises(ValueError, match="judge_price"):
        ce.estimate(
            trials=1, attempts_per_trial=1,
            estimated_input_tokens_per_attempt=1000, estimated_output_tokens_per_attempt=1000,
            price=PRICE, judge_tiers_enabled=1,
        )


def test_estimate_refuses_judges_enabled_with_no_judge_token_assumption():
    with pytest.raises(ValueError, match="judge call estimated to cost nothing"):
        ce.estimate(
            trials=1, attempts_per_trial=1,
            estimated_input_tokens_per_attempt=1000, estimated_output_tokens_per_attempt=1000,
            price=PRICE, judge_tiers_enabled=1, judge_price=JUDGE_PRICE,
        )


def test_a_plan_under_the_ceiling_without_judges_is_over_it_with_them():
    """The orchestrator's own control: a plan comfortably under $5 without
    judges must be refused once both judge tiers are enabled and the judge
    cost pushes it over - and refused ONLY in that configuration, not by
    some unconditional new ceiling check."""
    without_judges = ce.estimate(
        trials=6, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=50_000, estimated_output_tokens_per_attempt=5_000,
        price=PRICE,
    )
    assert without_judges.estimated_usd <= ce.CEILING_USD
    ce.authorize(without_judges, approved_budget_usd=without_judges.estimated_usd)  # must not raise

    expensive_judge_price = ce.ModelPrice(
        name="expensive-judge", input_usd_per_million=500.0, output_usd_per_million=500.0, source="test",
    )
    with_judges = ce.estimate(
        trials=6, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=50_000, estimated_output_tokens_per_attempt=5_000,
        price=PRICE,
        judge_tiers_enabled=2, judge_price=expensive_judge_price,
        estimated_judge_input_tokens_per_call=50_000, estimated_judge_output_tokens_per_call=5_000,
    )
    assert with_judges.estimated_usd > ce.CEILING_USD
    with pytest.raises(ce.SpendNotAuthorized, match="ceiling"):
        ce.authorize(with_judges, approved_budget_usd=1_000_000.0)


# --------------------------------------------------------------------------
# authorize(): the spend gate. Committed negative controls for ADR 0005 rule 5.
# --------------------------------------------------------------------------


def _cheap_estimate() -> ce.RunCostEstimate:
    return ce.estimate(
        trials=1, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=1000, estimated_output_tokens_per_attempt=1000,
        price=PRICE,
    )


def test_authorize_refuses_without_an_approved_budget():
    """Red case: ADR 0005's default - no budget approved - must refuse, not
    silently run for free or skip quietly."""
    with pytest.raises(ce.SpendNotAuthorized, match="no budget has been approved"):
        ce.authorize(_cheap_estimate(), approved_budget_usd=None)


def test_authorize_refuses_an_insufficient_budget():
    """Red case: an approved budget that is smaller than the estimate must
    refuse outright - never silently narrow the run to fit."""
    cost = _cheap_estimate()
    with pytest.raises(ce.SpendNotAuthorized, match="less than"):
        ce.authorize(cost, approved_budget_usd=cost.estimated_usd - 0.01)


def test_authorize_accepts_a_sufficient_budget():
    cost = _cheap_estimate()
    ce.authorize(cost, approved_budget_usd=cost.estimated_usd)  # must not raise


def test_authorize_accepts_a_generous_budget():
    cost = _cheap_estimate()
    ce.authorize(cost, approved_budget_usd=cost.estimated_usd + 1000)  # must not raise


# --------------------------------------------------------------------------
# The $5 operator ceiling (msg 1401/1402) - refused regardless of any
# approved budget, however large.
# --------------------------------------------------------------------------


def test_authorize_refuses_an_estimate_over_the_ceiling_even_with_a_huge_budget():
    over_ceiling = ce.estimate(
        trials=1_000_000, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=1000, estimated_output_tokens_per_attempt=1000,
        price=PRICE,
    )
    assert over_ceiling.estimated_usd > ce.CEILING_USD
    with pytest.raises(ce.SpendNotAuthorized, match="ceiling"):
        ce.authorize(over_ceiling, approved_budget_usd=1_000_000.0)


def test_authorize_accepts_an_estimate_right_at_the_ceiling():
    at_ceiling = ce.RunCostEstimate(
        trials=1, attempts_per_trial=1, total_attempts=1, price=PRICE,
        estimated_input_tokens_per_attempt=1, estimated_output_tokens_per_attempt=1,
        estimated_usd=ce.CEILING_USD,
    )
    ce.authorize(at_ceiling, approved_budget_usd=ce.CEILING_USD)  # must not raise


# --------------------------------------------------------------------------
# Non-finite / negative values must not bypass the gate (Codex code-review
# finding on #26): a `<` comparison against NaN is always False.
# --------------------------------------------------------------------------


def test_model_price_refuses_a_nan_rate():
    with pytest.raises(ValueError, match="finite"):
        ce.ModelPrice(name="x", input_usd_per_million=float("nan"), output_usd_per_million=1.0, source="test")


def test_model_price_refuses_a_negative_rate():
    with pytest.raises(ValueError, match="not be negative"):
        ce.ModelPrice(name="x", input_usd_per_million=-1.0, output_usd_per_million=1.0, source="test")


def test_model_price_refuses_an_infinite_rate():
    with pytest.raises(ValueError, match="finite"):
        ce.ModelPrice(name="x", input_usd_per_million=1.0, output_usd_per_million=float("inf"), source="test")


def test_authorize_refuses_a_nan_budget():
    """Red case: `float(\"nan\") < cost.estimated_usd` is always False, so a
    NaN budget must be refused explicitly rather than falling through the
    ordinary comparison."""
    with pytest.raises(ce.SpendNotAuthorized, match="finite"):
        ce.authorize(_cheap_estimate(), approved_budget_usd=float("nan"))


def test_authorize_refuses_a_negative_budget():
    with pytest.raises(ce.SpendNotAuthorized):
        ce.authorize(_cheap_estimate(), approved_budget_usd=-1.0)


def test_authorize_refuses_an_infinite_budget():
    """An infinite budget would authorize literally anything - refused
    explicitly rather than treated as 'sufficient'."""
    with pytest.raises(ce.SpendNotAuthorized, match="finite"):
        ce.authorize(_cheap_estimate(), approved_budget_usd=float("inf"))


# --------------------------------------------------------------------------
# estimated_usd is never rounded before authorization (Codex code-review
# finding on #26): rounding a tiny positive cost down to 0.0000 would let it
# authorize against a budget of $0.
# --------------------------------------------------------------------------


def test_a_tiny_positive_estimate_still_refuses_a_zero_budget():
    tiny = ce.estimate(
        trials=1, attempts_per_trial=1,
        estimated_input_tokens_per_attempt=1, estimated_output_tokens_per_attempt=1,
        price=PRICE,
    )
    assert tiny.estimated_usd > 0
    with pytest.raises(ce.SpendNotAuthorized):
        ce.authorize(tiny, approved_budget_usd=0.0)
