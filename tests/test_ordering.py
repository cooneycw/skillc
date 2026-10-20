"""#279 PR-2a: the controller-owned ordering counter, and its stamp on
controller-turn records (orchestrator ruling R3: only a multi-turn attempt is
ordered; every other record is byte-identical)."""

from __future__ import annotations

import threading
from pathlib import Path

from test_agent_trial import _planned
from test_controller_turns import _MemoryTurns, _turn_events

from skillc import lifecycle
from skillc import trial as t
from skillc.backend import Limits
from skillc.ordering import Order


def test_the_order_is_strictly_increasing_and_never_repeats_under_threads() -> None:
    order = Order()
    seen: list[int] = []
    lock = threading.Lock()

    def take() -> None:
        for _ in range(500):
            value = order.next()
            with lock:
                seen.append(value)

    threads = [threading.Thread(target=take) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(seen) == list(range(1, 4001)) and order.last == 4000


def test_turn_records_carry_the_order_only_when_given_one(tmp_path: Path) -> None:
    store = t.open_store(tmp_path / "ordered", forbidden=[])
    experiment, attempt_id = _planned(store)
    order = Order()
    order.next()  # an event before the turn (a service request, say) took 1
    lifecycle._run_turns(_MemoryTurns(), object(), experiment, attempt_id, ["turn-1"],  # type: ignore[arg-type]
                         Limits(timeout=60), None, lambda _b, _h, turn, _r: ["turn-2"] if turn == 1 else None,
                         order=order)
    events = _turn_events(experiment, attempt_id)
    assert [(e.get("dispatched"), e.get("delivered"), e["order"]) for e in events] == [(True, None, 2), (None, True, 3)]

    plain = t.open_store(tmp_path / "plain", forbidden=[])
    experiment, attempt_id = _planned(plain)
    lifecycle._run_turns(_MemoryTurns(), object(), experiment, attempt_id, ["turn-1"],  # type: ignore[arg-type]
                         Limits(timeout=60), None, lambda _b, _h, turn, _r: ["turn-2"] if turn == 1 else None)
    assert all("order" not in e for e in _turn_events(experiment, attempt_id))  # the byte-identical control


def test_a_whole_multi_turn_attempt_stamps_its_turns_and_a_single_turn_one_does_not(tmp_path: Path) -> None:
    """End to end through `run_one_attempt` on the fake docker (#279 PR 1's
    harness): the order exists only because turns were declared."""
    from test_controller_turns import APPROVAL, _attempt

    from skillc import controller_turns as ct

    def run(name: str, turns: ct.Turns) -> list[dict[str, object]]:
        root = tmp_path / name
        root.mkdir()
        (root / "base").mkdir()
        store = t.open_store(root / "store", forbidden=[])
        _record, _entries, experiment, attempt_id = _attempt(store, root / "base", root / "docker-state", root,
                                                             turns=turns)
        return _turn_events(experiment, attempt_id)

    ordered = run("ordered", ct.Turns((APPROVAL,)))
    orders = [int(str(e["order"])) for e in ordered]
    assert orders and orders == sorted(orders) and len(set(orders)) == len(orders)
    assert run("single", ct.NO_TURNS) == []  # no turn, no turn record, no order anywhere
