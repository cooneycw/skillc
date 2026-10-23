"""#530: the owner's D3 token bound (#529 comment 6365908723): an attempt above
the declared `shared.token_pause_per_attempt` is flagged and the next attempt
waits for the orchestrator's GO. The pause is a gate that lets work through,
so each side has a committed case: over the bound pauses, under it continues,
an UNKNOWN total pauses (it cannot be shown to be under), and a declaration
that does not declare it never pauses.
"""

from __future__ import annotations

from typing import Any

import pytest

from skillc import fixture_live as fl

BOUND = 1_500_000


def _record(total: Any, disposition: str = "captured") -> dict[str, Any]:
    usage = {"total_tokens": total} if total is not None else None
    return {"disposition": disposition, "observation": {"run_metadata": {"token_usage": usage}}}


def test_red_an_attempt_above_the_bound_pauses_the_schedule() -> None:
    trigger = fl.token_pause_trigger(_record(1_600_000), BOUND)
    assert trigger is not None and "1600000 tokens" in trigger and "orchestrator's GO" in trigger


def test_an_attempt_at_or_under_the_bound_continues() -> None:
    assert fl.token_pause_trigger(_record(1_400_000), BOUND) is None
    assert fl.token_pause_trigger(_record(BOUND), BOUND) is None


@pytest.mark.parametrize("total", [None, "1400000", True])
def test_red_an_unknown_total_pauses(total: Any) -> None:
    assert "unknown" in str(fl.token_pause_trigger(_record(total), BOUND))


def test_no_declared_bound_or_no_dispatch_never_pauses() -> None:
    assert fl.token_pause_trigger(_record(9_000_000), None) is None
    assert fl.token_pause_trigger(_record(None, disposition="not-run"), BOUND) is None


@pytest.mark.parametrize("value", [0, -1, True, 1.5e6, "1500000"])
def test_red_a_malformed_declared_bound_is_refused(value: Any) -> None:
    from tests.test_fixture_live import _draft
    data = _draft()
    fl.parse_declaration(data)  # the draft parses as is
    data["shared"]["token_pause_per_attempt"] = value
    with pytest.raises(fl.LiveRefused, match="token_pause_per_attempt"):
        fl.parse_declaration(data)


def test_a_declared_bound_is_inside_the_digest() -> None:
    from tests.test_fixture_live import _draft
    data = _draft()
    before = fl.parse_declaration(data).digest
    data["shared"]["token_pause_per_attempt"] = BOUND
    assert fl.parse_declaration(data).digest != before
