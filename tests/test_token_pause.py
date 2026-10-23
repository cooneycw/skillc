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


def _draft() -> dict[str, Any]:
    """`test_fixture_live._draft()`, loaded by path (one module name for mypy)."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent / "test_fixture_live.py"
    spec = importlib.util.spec_from_file_location("fixture_live_tests_for_token_pause", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._draft()  # type: ignore[no-any-return]


def _record(total: Any, disposition: str = "captured") -> dict[str, Any]:
    usage = {"total_tokens": total} if total is not None else None
    return {"disposition": disposition, "observation": {"run_metadata": {"token_usage": usage}}}


def test_red_an_attempt_above_the_bound_pauses_the_schedule() -> None:
    trigger = fl.token_pause_trigger(_record(1_600_000), BOUND)
    assert trigger is not None and "1600000 tokens" in trigger and "orchestrator's GO" in trigger


def test_an_attempt_at_or_under_the_bound_continues() -> None:
    assert fl.token_pause_trigger(_record(1_400_000), BOUND) is None
    assert fl.token_pause_trigger(_record(BOUND), BOUND) is None


@pytest.mark.parametrize("total", [None, "1400000", True, -1])
def test_red_an_unknown_total_pauses(total: Any) -> None:
    """Counter-model review (L1): a negative total cannot show consumption
    stayed under the bound - it pauses, as an unknown one does."""
    assert "unknown" in str(fl.token_pause_trigger(_record(total), BOUND))


def test_no_declared_bound_or_no_dispatch_never_pauses() -> None:
    assert fl.token_pause_trigger(_record(9_000_000), None) is None
    assert fl.token_pause_trigger(_record(None, disposition="not-run"), BOUND) is None


@pytest.mark.parametrize("value", [0, -1, True, 1.5e6, "1500000"])
def test_red_a_malformed_declared_bound_is_refused(value: Any) -> None:
    data = _draft()
    fl.parse_declaration(data)  # the draft parses as is
    data["shared"]["token_pause_per_attempt"] = value
    with pytest.raises(fl.LiveRefused, match="token_pause_per_attempt"):
        fl.parse_declaration(data)


def test_a_declared_bound_is_inside_the_digest() -> None:
    data = _draft()
    before = fl.parse_declaration(data).digest
    data["shared"]["token_pause_per_attempt"] = BOUND
    assert fl.parse_declaration(data).digest != before


# --- what decides "live" (orchestrator condition, #530) ------------------------------

def _clean(record: dict[str, Any]) -> dict[str, Any]:
    """A record no containment trigger stops, so only the pause can."""
    return record


@pytest.fixture
def no_containment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fl, "containment_trigger", lambda record, **_kw: None)


@pytest.mark.parametrize("total", [None, 1_600_000])
def test_red_a_live_attempt_with_unknown_or_excess_tokens_pauses(no_containment: None, total: Any) -> None:
    trigger = fl.schedule_trigger(_record(total), allowlist_digest="x", nested_policy=None,
                                  token_pause=BOUND, rehearse=None)
    assert trigger is not None and trigger.startswith("token pause")


def test_red_absent_tokens_on_a_live_run_are_the_pause_never_a_rehearsal(no_containment: None) -> None:
    """A record exactly like a scripted actor's (no token usage at all) on a
    LIVE run: the classifier has only the controller's run mode to go on, so it
    cannot read the missing tokens as a rehearsal - it pauses."""
    actor_like = {"disposition": "captured", "observation": {"run_metadata": {}}}
    assert fl.schedule_trigger(actor_like, allowlist_digest="x", nested_policy=None, token_pause=BOUND,
                               rehearse=None) is not None
    assert fl.schedule_trigger(actor_like, allowlist_digest="x", nested_policy=None, token_pause=BOUND,
                               rehearse="actor") is None  # only the declared run mode skips it


def test_the_live_classifier_reads_no_attempt_field() -> None:
    """The mode is a parameter, never derived inside: the function's inputs are
    the record, the declaration's bound and the controller's `rehearse`."""
    import inspect
    params = list(inspect.signature(fl.schedule_trigger).parameters)
    assert params == ["record", "allowlist_digest", "nested_policy", "token_pause", "rehearse"]
    source = inspect.getsource(fl.schedule_trigger)
    assert "rehearse is None" in source and 'record.get("rehearse' not in source
