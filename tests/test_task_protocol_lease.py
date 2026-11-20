"""The #620 PR-B leases and startup barrier (skillc/task_protocol_lease.py, B4).

controls/task-protocol-lease/cases.json holds hand-written operation scripts
with each operation's expected outcome; they were not produced by running the
module. Each blind variant below must disagree with them."""

from __future__ import annotations

import importlib
import itertools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from skillc import task_protocol_lease as tpl
from skillc.task_protocol_lease import Inventory, LeaseError, Leases, Slot

DOC = json.loads((Path(__file__).resolve().parent.parent / "controls" / "task-protocol-lease"
                  / "cases.json").read_text())
CASES: list[dict[str, Any]] = DOC["cases"]


def _inventory() -> Inventory:
    raw = DOC["inventory"]
    return Inventory(raw["attempt_id"], raw["declaration_digest"],
                     tuple(Slot(**s) for s in raw["slots"]), raw["clock_origin_ns"])


def _tokens() -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"ep-{next(counter)}"


def _do(leases: Leases, op: dict[str, Any]) -> Any:
    """Run one scripted operation; return what its `expect` is compared to."""
    name = op["op"]
    try:
        if name == "issue":
            leases.issue(op["principal"])
        elif name == "bind":
            leases.bind(op["principal"], runtime_instance=op["runtime_instance"],
                        session_id=op["session_id"], evidence_digest=op["evidence_digest"])
        elif name == "unstarted":
            leases.mark_unstarted(op["principal"])
        elif name == "unavailable":
            leases.mark_unavailable(op["principal"], op["reason"])
        elif name == "barrier":
            record = leases.barrier()
            return {"expect": "ok", "states": [s["state"] for s in record["slots"]]}
        elif name == "lookup":
            return leases.principal_for(op["endpoint"], op["runtime_instance"])
        elif name == "resume":
            return leases.resume(op["principal"], op["session_id"])
        elif name == "revoke":
            leases.revoke(op["principal"], op["reason"])
        elif name == "sessions":
            return leases.bound_sessions()
        else:
            raise AssertionError(name)
    except LeaseError:
        return "refused" if name != "barrier" else {"expect": "refused", "states": None}
    return "ok"


def _want(op: dict[str, Any]) -> Any:
    if op["op"] == "barrier":
        return {"expect": op["expect"], "states": op["states"]}
    return op["expect"]


def _run(case: dict[str, Any], leases_type: type[Leases] = Leases) -> list[str]:
    leases = leases_type(_inventory(), used_instances=case.get("used_instances", ()),
                         used_endpoints=case.get("used_endpoints", ()), token=_tokens())
    wrong = []
    for index, op in enumerate(case["ops"]):
        got, want = _do(leases, op), _want(op)
        if got != want:
            wrong.append(f"{case['name']}[{index}] {op['op']}: {got!r} != {want!r}")
    return wrong


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_each_committed_script_behaves_as_declared(case: dict[str, Any]) -> None:
    assert _run(case) == []


def test_the_cases_reach_every_slot_state_and_both_outcomes() -> None:
    states = {s for c in CASES for op in c["ops"] if op["op"] == "barrier" and op["states"]
              for s in op["states"]}
    assert states == set(tpl.STATES)
    outcomes = {op["expect"] for c in CASES for op in c["ops"]
                if op["op"] in ("issue", "bind", "unstarted", "unavailable", "revoke")}
    assert outcomes == {"ok", "refused"}


# Blind variants: each must disagree with at least the named case.


class _Rebinds(Leases):
    def bind(self, principal: str, *, runtime_instance: str, session_id: str | None,
             evidence_digest: str) -> dict[str, Any]:
        self._entries[principal].state = None
        return super().bind(principal, runtime_instance=runtime_instance, session_id=session_id,
                            evidence_digest=evidence_digest)


class _IgnoresRevocation(Leases):
    def principal_for(self, endpoint_id: str, runtime_instance: str) -> str | None:
        for entry in self._entries.values():
            entry.revoked = False
        return super().principal_for(endpoint_id, runtime_instance)


class _IgnoresRuntime(Leases):
    def principal_for(self, endpoint_id: str, runtime_instance: str) -> str | None:
        for entry in self._entries.values():
            if entry.lease is not None and entry.lease.endpoint_id == endpoint_id:
                return super().principal_for(endpoint_id, entry.runtime_instance or "")
        return None


class _GuessesNonstarts(Leases):
    def barrier(self) -> dict[str, Any]:
        for entry in self._entries.values():
            entry.state = entry.state or "unstarted"
        return super().barrier()


class _ForgetsEarlierAttempts(Leases):
    def __init__(self, inventory: Inventory, **kwargs: Any) -> None:
        kwargs["used_instances"] = ()
        super().__init__(inventory, **kwargs)


class _NeverFreezes(Leases):
    def _open(self, principal: str) -> Any:
        if principal not in self._entries:
            raise LeaseError("unplanned principal")
        return self._entries[principal]


class _KeepsFirstHolder(Leases):
    """The finding on #804: a collision that marks only the newcomer."""

    def bind(self, principal: str, *, runtime_instance: str, session_id: str | None,
             evidence_digest: str) -> dict[str, Any]:
        before = {p: (e.state, e.reason) for p, e in self._entries.items() if p != principal}
        try:
            return super().bind(principal, runtime_instance=runtime_instance,
                                session_id=session_id, evidence_digest=evidence_digest)
        finally:
            for other, (state, reason) in before.items():
                self._entries[other].state, self._entries[other].reason = state, reason


@pytest.mark.parametrize("variant,must_miss", [
    (_Rebinds, "conflicting-second-bind"),
    (_IgnoresRevocation, "revocation-is-one-way"),
    (_IgnoresRuntime, "healthy-with-a-nonstart"),
    (_GuessesNonstarts, "barrier-refused-while-unresolved"),
    (_ForgetsEarlierAttempts, "runtime-instance-from-earlier-attempt"),
    (_NeverFreezes, "frozen-after-barrier"),
    (_KeepsFirstHolder, "runtime-instance-collision-within-attempt"),
    (_KeepsFirstHolder, "session-collision-within-attempt"),
], ids=lambda v: getattr(v, "__name__", str(v)))
def test_a_blind_lease_table_disagrees(variant: type[Leases], must_miss: str) -> None:
    case = next(c for c in CASES if c["name"] == must_miss)
    assert _run(case, variant)


# Records for B2's journal, with a drift guard.

#: B2's closed field sets, mirrored until `skillc.task_protocol_journal` is on
#: main. Once it is importable, the test below compares against the ACTUAL sets
#: and fails on any difference; it never skips.
B2_MIRROR = {
    "binding": {"principal", "evidence_digest"},
    "barrier": {"bindings_digest", "slots"},
    "revocation": {"principal", "reason"},
}
B2_SLOT_STATES = ("bound", "unstarted", "unavailable")


def _b2() -> tuple[dict[str, set[str]], tuple[str, ...]]:
    try:
        journal = importlib.import_module("skillc.task_protocol_journal")
    except ImportError:
        return B2_MIRROR, B2_SLOT_STATES
    actual = {kind: set(journal.KINDS[kind]) for kind in B2_MIRROR}
    assert actual == B2_MIRROR, "the B2 mirror here has drifted from task_protocol_journal"
    assert tuple(journal.SLOT_STATES) == B2_SLOT_STATES
    return actual, tuple(journal.SLOT_STATES)


def test_records_match_b2_field_sets_mirror_until_b2_merges_then_actual() -> None:
    fields, slot_states = _b2()
    assert set(tpl.STATES) == set(slot_states)
    leases = Leases(_inventory(), token=_tokens())
    leases.issue("p-a")
    binding = leases.bind("p-a", runtime_instance="inst-a", session_id="sess-a",
                          evidence_digest="sha256:" + "e" * 64)
    leases.mark_unstarted("p-b")
    leases.mark_unavailable("p-c", "launch-failed")
    barrier = leases.barrier()
    revocation = leases.revoke("p-a", "closed")
    assert set(binding) == fields["binding"]
    assert set(barrier) == fields["barrier"]
    assert set(revocation) == fields["revocation"]
    assert [s["principal"] for s in barrier["slots"]] == list(_inventory().principals)
    assert all(set(s) == {"principal", "state"} for s in barrier["slots"])


def test_the_bindings_digest_covers_private_identities_without_revealing_them() -> None:
    def run(instance: str) -> dict[str, Any]:
        leases = Leases(_inventory(), token=_tokens())
        leases.issue("p-a")
        leases.bind("p-a", runtime_instance=instance, session_id="sess-secret-a",
                    evidence_digest="sha256:" + "e" * 64)
        leases.mark_unstarted("p-b")
        leases.mark_unstarted("p-c")
        return leases.barrier()

    first, second = run("inst-a"), run("inst-b")
    assert first["bindings_digest"] != second["bindings_digest"]
    assert first["slots"] == second["slots"]
    text = json.dumps(first)
    assert "sess-secret-a" not in text and "inst-a" not in text and "ep-1" not in text


def test_the_inventory_digest_binds_the_prelaunch_population() -> None:
    raw = DOC["inventory"]
    base = _inventory()
    changes: list[dict[str, Any]] = [{"clock_origin_ns": 1001}, {"attempt_id": "attempt-2"}]
    for change in changes:
        fields: dict[str, Any] = {"attempt_id": raw["attempt_id"],
                                  "declaration_digest": raw["declaration_digest"],
                                  "slots": base.slots, "clock_origin_ns": raw["clock_origin_ns"],
                                  **change}
        assert Inventory(**fields).digest != base.digest
    nonstart_dropped = Inventory(raw["attempt_id"], raw["declaration_digest"], base.slots[:2],
                                 raw["clock_origin_ns"])
    assert nonstart_dropped.digest != base.digest


@pytest.mark.parametrize("build", [
    lambda: Slot("p a", "r", "t", 0, 1, "n"),
    lambda: Slot("p", "r", "t", True, 1, "n"),
    lambda: Slot("p", "r", "t", 0, 0, "n"),
    lambda: Inventory("a", "sha256:" + "a" * 64, (), 0),
    lambda: Inventory("a", "a" * 64, (Slot("p", "r", "t", 0, 1, "n"),), 0),
    lambda: Inventory("a", "sha256:" + "a" * 64,
                      (Slot("p", "r", "t", 0, 1, "n"), Slot("p", "r2", "t", 0, 1, "n")), 0),
    lambda: Inventory("a", "sha256:" + "a" * 64,
                      (Slot("p", "r", "t", 0, 1, "n"), Slot("q", "r", "t", 0, 1, "n")), 0),
    lambda: Inventory("a", "sha256:" + "a" * 64, (Slot("p", "r", "t", 0, 1, "n"),), -1),
])
def test_an_inventory_outside_the_contract_is_refused(build: Callable[[], object]) -> None:
    with pytest.raises(LeaseError):
        build()


def test_sessions_are_final_only_after_the_barrier() -> None:
    leases = Leases(_inventory(), token=_tokens())
    with pytest.raises(LeaseError):
        leases.bound_sessions()
    assert leases.passed is False
