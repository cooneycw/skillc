"""The #620 PR-B decision state machine (skillc/task_protocol_state.py, B3).

controls/task-protocol-state/cases.json holds hand-written step sequences with
each step's expected decision; they were not produced by running the machine.
Each blind machine variant below must disagree with them."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from skillc import task_protocol_schema as schema
from skillc import task_protocol_state as tps
from skillc.task_protocol_state import Machine, Offer, Plan, Proposal, StateError

DOC = json.loads((Path(__file__).resolve().parent.parent / "controls" / "task-protocol-state"
                  / "cases.json").read_text())
CASES: list[dict[str, Any]] = DOC["cases"]

#: B2's closed field sets for the three kinds this machine proposes (kept
#: literal here so a drift between the two slices fails a test).
JOURNAL_FIELDS = {
    "decision": {"principal", "request", "op", "offer_id", "request_digest", "decision", "reason"},
    "retry": {"principal", "request", "request_digest", "original_seq"},
    "rejection": {"principal", "reason", "length", "content_digest"},
}


def _plan() -> Plan:
    raw = DOC["plan"]
    return Plan(tuple(Offer(p, o) for p, o in raw["offers"]), raw["deadline_ns"],
                frozenset(raw["retired_offer_ids"]))


def _raw(step: dict[str, Any]) -> bytes:
    if "raw" in step:
        return step["raw"].encode()
    return json.dumps(step["request"]).encode()


Proposer = Callable[[Machine, str, Any, int, bool], Proposal]


def _propose(machine: Machine, principal: str, parsed: Any, elapsed: int, fenced: bool) -> Proposal:
    return machine.propose(principal, parsed, elapsed, fenced=fenced)


def _run(case: dict[str, Any], propose: Proposer = _propose,
         machine_type: type[Machine] = Machine) -> list[str]:
    machine = machine_type(_plan())
    wrong = []
    for index, step in enumerate(case["steps"]):
        expect = step["expect"]
        proposal = propose(machine, step["principal"], schema.parse_request(_raw(step)),
                           step["elapsed_ns"], step["fenced"])
        got = {"kind": proposal.kind, "decision": proposal.receipt.decision,
               "reason": proposal.receipt.reason, "violation": proposal.violation}
        want = {k: expect[k] for k in ("kind", "decision", "reason", "violation")}
        if "offer_id" in expect:
            got["offer_id"], want["offer_id"] = proposal.receipt.offer_id, expect["offer_id"]
        if "retry_of" in expect:
            got["original_seq"] = proposal.fields.get("original_seq")
            want["original_seq"] = expect["retry_of"] + 1
        if "principal_field" in expect:
            got["principal"], want["principal"] = proposal.fields["principal"], expect[
                "principal_field"]
        if "row_reason" in expect:
            got["row_reason"], want["row_reason"] = proposal.fields["reason"], expect["row_reason"]
        if got != want:
            wrong.append(f"{case['name']}[{index}]: {got} != {want}")
        machine.commit(proposal, index + 1)
    return wrong


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_each_committed_sequence_decides_as_declared(case: dict[str, Any]) -> None:
    assert _run(case) == []


def test_every_proposal_is_a_valid_receipt_and_journal_record() -> None:
    for case in CASES:
        machine = Machine(_plan())
        for index, step in enumerate(case["steps"]):
            proposal = machine.propose(step["principal"], schema.parse_request(_raw(step)),
                                       step["elapsed_ns"], fenced=step["fenced"])
            assert schema.parse_receipt(proposal.receipt.encode()) == proposal.receipt
            assert set(proposal.fields) == JOURNAL_FIELDS[proposal.kind], case["name"]
            assert proposal.fields["principal"] == step["principal"]
            machine.commit(proposal, index + 1)


def test_the_cases_reach_every_decision_and_every_violation() -> None:
    decisions = {s["expect"]["decision"] for c in CASES for s in c["steps"]}
    assert decisions == set(schema.DECISIONS)
    violations = {s["expect"]["reason"] for c in CASES for s in c["steps"]
                  if s["expect"]["violation"]}
    assert violations == set(tps.VIOLATIONS)
    kinds = {s["expect"]["kind"] for c in CASES for s in c["steps"]}
    assert kinds == set(JOURNAL_FIELDS)


# Blind variants: each must disagree with at least the named case.


class _NoRetryMemory(Machine):
    def commit(self, proposal: Proposal, seq: int) -> None:
        super().commit(proposal, seq)
        self._state[proposal.principal].requests.clear()


class _ConflictOverwrites(Machine):
    def commit(self, proposal: Proposal, seq: int) -> None:
        state = self._state[proposal.principal]
        super().commit(proposal, seq)
        if proposal.kind == "decision" and proposal.request is not None:
            state.requests[proposal.request] = tps._Prior(proposal.fields["request_digest"], seq,
                                                          proposal.receipt)


def _strict_deadline(machine: Machine, principal: str, parsed: Any, elapsed: int,
                     fenced: bool) -> Proposal:
    return machine.propose(principal, parsed, elapsed + 1, fenced=fenced)


def _ignore_fence(machine: Machine, principal: str, parsed: Any, elapsed: int,
                  fenced: bool) -> Proposal:
    return machine.propose(principal, parsed, elapsed, fenced=False)


def _blame_the_owner(machine: Machine, principal: str, parsed: Any, elapsed: int,
                     fenced: bool) -> Proposal:
    proposal = machine.propose(principal, parsed, elapsed, fenced=fenced)
    if proposal.receipt.reason == "wrong-offer" and isinstance(parsed, schema.Request):
        owner = next((o.principal for o in machine.plan.offers if o.offer_id == parsed.offer_id),
                     principal)
        proposal.fields["principal"] = owner
    return proposal


def _never_a_violation(machine: Machine, principal: str, parsed: Any, elapsed: int,
                       fenced: bool) -> Proposal:
    proposal = machine.propose(principal, parsed, elapsed, fenced=fenced)
    blind = dataclasses.replace(proposal, violation=False)
    machine._pending = blind
    return blind


def _missing(name: str, **kwargs: Any) -> bool:
    case = next(c for c in CASES if c["name"] == name)
    return bool(_run(case, **kwargs))


@pytest.mark.parametrize("kwargs,must_miss", [
    ({"machine_type": _NoRetryMemory}, "retry-identical-completion"),
    ({"machine_type": _ConflictOverwrites}, "changed-content-same-number-then-original-retry"),
    ({"propose": _strict_deadline}, "deadline-boundary"),
    ({"propose": _ignore_fence}, "fenced-requests-and-retries"),
    ({"propose": _blame_the_owner}, "wrong-offer-attributed-to-sender"),
    ({"propose": _never_a_violation}, "distinct-second-completion"),
    ({"propose": _never_a_violation}, "complete-before-ack"),
], ids=["no-retry-memory", "conflict-overwrites-original", "strict-deadline", "ignore-fence",
        "blame-the-owner", "never-a-violation-completion", "never-a-violation-order"])
def test_a_blind_machine_disagrees(kwargs: dict[str, Any], must_miss: str) -> None:
    assert _missing(must_miss, **kwargs)


def test_an_accept_all_machine_disagrees() -> None:
    def accept(machine: Machine, principal: str, parsed: Any, elapsed: int,
               fenced: bool) -> Proposal:
        proposal = machine.propose(principal, parsed, elapsed, fenced=fenced)
        number = parsed.request if isinstance(parsed, schema.Request) else 1
        blind = Proposal(principal, "decision", proposal.fields,
                         schema.Receipt(number, "acknowledged", "o-a"), False, None, None)
        machine._pending = blind
        return blind

    assert sum(bool(_run(case, propose=accept)) for case in CASES) == len(CASES)


# The two-phase contract.


def _offer(number: int = 1) -> schema.Request:
    parsed = schema.parse_request(json.dumps({"version": 1, "op": "offer",
                                              "request": number}).encode())
    assert isinstance(parsed, schema.Request)
    return parsed


def test_a_proposal_changes_nothing_until_it_is_committed() -> None:
    machine = Machine(_plan())
    proposal = machine.propose("role-a", _offer(), 1)
    assert machine.snapshot("role-a")["offered"] is False
    with pytest.raises(StateError):
        machine.propose("role-a", _offer(2), 1)
    machine.discard()
    assert machine.snapshot("role-a")["offered"] is False
    with pytest.raises(StateError):
        machine.commit(proposal, 1)
    again = machine.propose("role-a", _offer(), 1)
    machine.commit(again, 1)
    assert machine.snapshot("role-a")["offered"] is True


def test_a_discarded_decision_is_not_remembered_for_retries() -> None:
    machine = Machine(_plan())
    machine.propose("role-a", _offer(), 1)
    machine.discard()
    proposal = machine.propose("role-a", _offer(), 2)
    assert proposal.kind == "decision" and proposal.receipt.decision == "offered"


@pytest.mark.parametrize("call", [
    lambda m: m.propose("role-z", _offer(), 1),
    lambda m: m.propose("role-a", _offer(), -1),
    lambda m: m.propose("role-a", _offer(), True),
    lambda m: m.propose("role-a", {"op": "offer"}, 1),
    lambda m: m.snapshot("role-z"),
])
def test_caller_errors_are_state_errors(call: Callable[[Machine], object]) -> None:
    with pytest.raises(StateError):
        call(Machine(_plan()))


@pytest.mark.parametrize("build", [
    lambda: Plan((), 10),
    lambda: Plan((Offer("a", "o-1"), Offer("a", "o-2")), 10),
    lambda: Plan((Offer("a", "o-1"), Offer("b", "o-1")), 10),
    lambda: Plan((Offer("a", "o-1"),), -1),
    lambda: Plan((Offer("a", "o-1"),), 10, frozenset({"o-1"})),
    lambda: Plan((Offer("a", "o-1"),), 10, frozenset({"-bad"})),
    lambda: Offer("a b", "o-1"),
])
def test_a_plan_outside_the_contract_is_refused(build: Callable[[], object]) -> None:
    with pytest.raises(StateError):
        build()
