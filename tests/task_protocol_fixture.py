"""Build REAL sealed task-protocol journals for adapter and assembly tests.

Everything here goes through the merged modules (B2 journal, B3 machine, B4
leases), with no hand-written journal bytes, so a projection test reads what
the controller would actually have written. The clock is injected in integer
nanoseconds.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skillc import live_wave
from skillc import task_protocol_journal as tj
from skillc import task_protocol_schema as schema
from skillc.task_protocol_lease import Inventory, Leases, Slot
from skillc.task_protocol_state import Machine, Offer, Plan

E = "sha256:" + "e" * 64


@dataclass
class Built:
    root: Path
    reference: tj.Reference
    context: tj.Context
    inventory: Inventory
    deadline_ns: int


def inventory_for(plan: live_wave.WavePlan, declaration: str, origin_ns: int = 0) -> Inventory:
    return Inventory(plan.wave_id, declaration,
                     tuple(Slot(principal_of(r.role), r.role, r.task, r.generation, r.revision,
                                r.nonce) for r in plan.roles), origin_ns)


def principal_of(role: str) -> str:
    return "slot-" + role


def offer_of(role: str) -> str:
    return "offer-" + role


def request(op: str, number: int, role: str,
            reason: str | None = None) -> schema.Request | schema.Rejected:
    fields: dict[str, Any] = {"version": 1, "op": op, "request": number}
    if op != "offer":
        fields["offer_id"] = offer_of(role)
    if reason is not None:
        fields["reason"] = reason
    return schema.parse_request(json.dumps(fields).encode())


#: (role, op, request number, elapsed_ns[, refusal reason])
Step = tuple[Any, ...]


def build(root: Path, plan: live_wave.WavePlan, declaration: str, deadline_digest: str,
          steps: Iterable[Step], *, deadline_ns: int | None = None,
          unbound: Iterable[str] = (), capacity_for: Iterable[str] = (),
          limits: dict[str, int] | None = None, origin_ns: int = 0,
          extra: Callable[[tj.Journal, Leases], None] | None = None) -> Built:
    """One sealed journal. `steps` are applied in order with their elapsed
    times; `unbound` roles are marked unstarted at the barrier."""
    deadline = round(plan.deadline * 1e9) if deadline_ns is None else deadline_ns
    inventory = inventory_for(plan, declaration, origin_ns)
    context = tj.Context(plan.wave_id, declaration, inventory.digest, deadline_digest,
                         "skillc-test", inventory.principals,
                         limits=limits or dict(tj.DEFAULT_LIMITS))
    tokens = itertools.count(1)
    leases = Leases(inventory, token=lambda: f"endpoint-{next(tokens)}")
    skip = set(unbound)
    plan_steps = list(steps)
    # Records written before the first step all sit at the origin.
    pre = 1 + sum(1 for r in plan.roles if r.role not in skip) + 1
    schedule = [origin_ns] * pre + [origin_ns + s[3] for s in plan_steps]
    schedule += [schedule[-1]] * 64
    clock_values: Iterator[int] = iter(schedule)
    journal = tj.Journal(root, context, origin_ns, clock_ns=lambda: next(clock_values))
    for binding in plan.roles:
        principal = principal_of(binding.role)
        leases.issue(principal)
        if binding.role in skip:
            leases.mark_unstarted(principal)
        else:
            record = leases.bind(principal, runtime_instance="instance-" + binding.role,
                                 session_id="session-" + binding.role, evidence_digest=E)
            journal.append("binding", **record)
    journal.append("barrier", **leases.barrier())
    machine = Machine(Plan(tuple(Offer(principal_of(r.role), offer_of(r.role)) for r in plan.roles),
                           deadline))
    for step in plan_steps:
        role, op, number = step[0], step[1], step[2]
        reason = step[4] if len(step) > 4 else None
        parsed = request(op, number, role, reason)
        principal = principal_of(role)

        def decide(elapsed: int, fenced: bool, principal: str = principal,
                   parsed: Any = parsed) -> tuple[str, dict[str, Any], Any]:
            proposal = machine.propose(principal, parsed, elapsed, fenced=fenced)
            return proposal.kind, proposal.fields, proposal

        seq, _, proposal = journal.transact(decide)
        machine.commit(proposal, seq)
    for role in capacity_for:
        journal.append("capacity", principal=principal_of(role), scope="principal")
    if extra is not None:
        extra(journal, leases)
    journal.append("fence", reason="closure")
    coverage = {p: "complete" for p in inventory.principals}
    reference = journal.seal(coverage)
    return Built(root, reference, context, inventory, deadline)


def plan_of(roles: Iterable[str], *, deadline: float = 10.0, wave_id: str = "wave-0001",
            sessions: bool = True) -> live_wave.WavePlan:
    names = list(roles)
    return live_wave.WavePlan(wave_id, tuple(
        live_wave.RoleBinding(role, f"{wave_id}-{role}",
                              f"00000000-0000-0000-0000-{i + 1:012x}" if sessions else None,
                              role, 0, 1, "task-nonce-" + role, ("output.json",))
        for i, role in enumerate(names)), names[0], deadline)
