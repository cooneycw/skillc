"""Verified adapter from the task-protocol journal into PR-A (#620 PR-B, B6).

See `docs/specs/evaluation-facility/task-protocol-stream.md`, section 3. It
reads a sealed controller journal (B2) only through `task_protocol_journal.
verify`, against the caller-held Reference and Context. It accounts for every
record and produces two things per planned role:

- a PROJECTION in the existing PR-A protocol row shape (`wave_id`, `role`,
  `attempt_id`, `session_id`, `task`, `generation`, `revision`, `nonce`, `op`,
  `elapsed`). It holds the role's first acknowledged and first
  completion-claimed decisions, and nothing else. The identity fields come from
  the frozen PLAN binding, never from the journal. The existing `live_wave`
  kernel then applies its existing rules to those rows, unchanged.
- a DIAGNOSTIC: offers, refusals, retries, rejections, sender-attributed
  violations, late and fenced counts, and coverage. Under accepted decision 5
  and the #626 ruling, it is a separate declared diagnostic that never changes
  the primary verdict. Any primary-endpoint effect is #639's to decide.

A role gets NO projection, so `live_wave` reports its protocol as unavailable
(UNKNOWN), when any of these holds:

- the journal is unverifiable;
- the bindings or the clock join do not hold;
- its seal coverage is unknown, or it had a capacity event;
- it was not bound at the startup barrier;
- one of its rows would change its deadline decision under float conversion.

INTEGER TIME DECIDES. A row is on time when `elapsed_ns <= deadline_ns`. The
PR-A seam takes float seconds. When `elapsed_ns / 1e9 <= plan.deadline` would
disagree with the integer decision, the role is refused (`float-cutoff-flip`)
instead of being rounded into an answer.

CLOCK JOIN, AND ITS LIMIT. The journal is bound to the attempt's one origin
through the inventory (`population_digest` covers `clock_origin_ns`). The wake
capture records no origin of its own, so the join is a caller-held binding
(`ClockJoin`), checked for consistency like any other held expectation. It
does not prove that both captures were started from that origin. B8 does that,
and makes the wake capture record its origin in its own sealed context.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import live_wave, wave_wake_capture
from . import task_protocol_journal as tj
from .task_protocol_lease import Inventory, Slot
from .task_protocol_state import VIOLATIONS

#: Every journal record kind, and where the adapter puts it. A kind missing
#: here refuses the whole journal rather than being skipped silently.
ACCOUNTED = {
    "binding": "custody", "barrier": "custody", "revocation": "custody", "fence": "custody",
    "decision": "decision", "retry": "diagnostic", "rejection": "diagnostic",
    "capacity": "coverage",
}
PROJECTED = {"acknowledged": "ack", "completion-claimed": "complete"}


class AdapterRefused(ValueError):
    """The journal cannot be joined to the frozen plan. Never task failure."""


@dataclass(frozen=True)
class ClockJoin:
    """Caller-held: the inventory, the wake capture context and the one
    origin these captures share. Consistency, not provenance."""

    inventory_digest: str
    wake_context_digest: str | None
    origin_ns: int


def parse_inventory(value: object) -> Inventory:
    if type(value) is not dict or set(value) != {"attempt_id", "declaration_digest",
                                                  "clock_origin_ns", "slots"}:
        raise AdapterRefused("closed inventory required")
    slots = value["slots"]
    if type(slots) is not list:
        raise AdapterRefused("inventory slots required")
    inventory: Inventory | None
    try:
        inventory = Inventory(value["attempt_id"], value["declaration_digest"],
                              tuple(Slot(**s) for s in slots), value["clock_origin_ns"])
    except (TypeError, ValueError):
        inventory = None
    # Raised OUTSIDE the handler, so neither __cause__ nor __context__ carries
    # the underlying error, which can name participant-chosen keys (B7).
    if inventory is None:
        raise AdapterRefused("inventory outside its contract")
    return inventory


def parse_clock_join(value: object) -> ClockJoin:
    if type(value) is not dict or set(value) != {"inventory_digest", "wake_context_digest",
                                                  "origin_ns"}:
        raise AdapterRefused("closed clock join required")
    if (type(value["inventory_digest"]) is not str or type(value["origin_ns"]) is not int
            or value["wake_context_digest"] is not None
            and type(value["wake_context_digest"]) is not str):
        raise AdapterRefused("clock join fields required")
    return ClockJoin(value["inventory_digest"], value["wake_context_digest"], value["origin_ns"])


def _empty_diagnostic() -> dict[str, Any]:
    return {"offers": 0, "acks": 0, "completion_claims": 0, "refusals": {}, "retries": 0,
            "rejections": {}, "violations": {}, "late": 0, "fenced": 0, "coverage": "unknown"}


def _unknown(plan: live_wave.WavePlan, reason: str) -> dict[str, Any]:
    return {"status": "UNKNOWN", "reasons": [reason],
            "projections": {r.role: None for r in plan.roles},
            "diagnostic": {"roles": {r.role: _empty_diagnostic() for r in plan.roles},
                           "unauthenticated_ingress": None, "capacity_events": None,
                           "seal_outcome": None, "primary_effect": "none (decision 5)"}}


def _check_bindings(context: tj.Context, inventory: Inventory, plan: live_wave.WavePlan,
                    join: ClockJoin | None, wake: wave_wake_capture.Context | None) -> str | None:
    if context.population_digest != inventory.digest:
        return "journal-not-bound-to-inventory"
    if context.attempt_id != plan.wave_id or inventory.attempt_id != plan.wave_id:
        return "journal-attempt-differs"
    if context.declaration_digest != inventory.declaration_digest:
        return "declaration-differs"
    if context.principals != inventory.principals:
        return "principal-population-differs"
    if [s.role for s in inventory.slots] != [r.role for r in plan.roles]:
        return "role-population-differs"
    for slot, binding in zip(inventory.slots, plan.roles, strict=True):
        if (slot.task, slot.generation, slot.revision, slot.nonce) != (
                binding.task, binding.generation, binding.revision, binding.nonce):
            return "slot-binding-differs"
    if join is None:
        return "clock-join-unavailable"
    if join.inventory_digest != inventory.digest or join.origin_ns != inventory.clock_origin_ns:
        return "clock-join-unavailable"
    if wake is not None:
        if (join.wake_context_digest != wake.digest
                or wake.attempt_id != context.attempt_id
                or wake.approved_declaration_digest != context.declaration_digest
                or wake.deadline_digest != context.deadline_digest):
            return "clock-join-unavailable"
    elif join.wake_context_digest is not None:
        return "clock-join-unavailable"
    return None


def adapt(root: Path, reference: tj.Reference, context: tj.Context, inventory: Inventory,
          plan: live_wave.WavePlan, deadline_ns: int, join: ClockJoin | None,
          wake: wave_wake_capture.Context | None = None) -> dict[str, Any]:
    """Project and diagnose a sealed journal for one planned wave."""
    if type(deadline_ns) is not int or deadline_ns < 0 or deadline_ns != round(plan.deadline * 1e9):
        return _unknown(plan, "deadline-differs")
    problem = _check_bindings(context, inventory, plan, join, wake)
    if problem is not None:
        return _unknown(plan, problem)
    verified = tj.verify(root, reference, context)
    if verified.get("status") != "CAPTURED":
        return _unknown(plan, "journal-unverifiable")
    records: list[dict[str, Any]] = verified["records"]
    if any(r.get("kind") not in ACCOUNTED for r in records):
        return _unknown(plan, "unaccounted-record-kind")

    role_of = {s.principal: s.role for s in inventory.slots}
    binding_of = {r.role: r for r in plan.roles}
    roles = {r.role: _empty_diagnostic() for r in plan.roles}
    coverage: dict[str, str] = verified["coverage"]
    bound: set[str] = set()
    capacity: set[str] = set()
    unauthenticated = capacity_events = 0
    rows: dict[str, list[dict[str, Any]]] = {r.role: [] for r in plan.roles}
    seen: dict[str, set[str]] = {r.role: set() for r in plan.roles}
    refused: dict[str, str] = {}

    for record in records:
        kind, principal = record["kind"], record.get("principal")
        if kind == "barrier":
            bound = {s["principal"] for s in record["slots"] if s["state"] == "bound"}
            continue
        if kind == "capacity":
            capacity_events += 1
            if principal is None:
                capacity.update(role_of)
            else:
                capacity.add(principal)
            continue
        if kind in ("binding", "revocation", "fence"):
            continue
        if principal is None:
            unauthenticated += kind == "rejection" and record["reason"] == "unauthenticated-peer"
            continue
        diagnostic = roles[role_of[principal]]
        if kind == "retry":
            diagnostic["retries"] += 1
            continue
        if kind == "rejection":
            reason = record["reason"]
            diagnostic["rejections"][reason] = diagnostic["rejections"].get(reason, 0) + 1
            diagnostic["fenced"] += reason == "fenced"
            continue
        decision, reason = record["decision"], record["reason"]
        role = role_of[principal]
        if decision == "offered":
            diagnostic["offers"] += 1
        elif decision == "refusal-retained":
            diagnostic["refusals"][reason] = diagnostic["refusals"].get(reason, 0) + 1
        elif decision == "rejected":
            diagnostic["rejections"][reason] = diagnostic["rejections"].get(reason, 0) + 1
            diagnostic["late"] += reason == "late"
            if reason in VIOLATIONS:
                diagnostic["violations"][reason] = diagnostic["violations"].get(reason, 0) + 1
        elif decision in PROJECTED:
            op = PROJECTED[decision]
            diagnostic["acks" if op == "ack" else "completion_claims"] += 1
            elapsed_ns = record["elapsed_ns"]
            on_time = elapsed_ns <= deadline_ns
            if (elapsed_ns / 1e9 <= plan.deadline) != on_time:
                refused[role] = "float-cutoff-flip"
            if op in seen[role]:
                continue
            seen[role].add(op)
            binding = binding_of[role]
            rows[role].append({"wave_id": plan.wave_id, "role": role,
                               "attempt_id": binding.attempt_id, "session_id": binding.session_id,
                               "task": binding.task, "generation": binding.generation,
                               "revision": binding.revision, "nonce": binding.nonce,
                               "op": op, "elapsed": elapsed_ns / 1e9})

    projections: dict[str, bytes | None] = {}
    for slot in inventory.slots:
        role, principal = slot.role, slot.principal
        complete = (coverage.get(principal) == "complete" and principal not in capacity
                    and principal in bound and role not in refused)
        roles[role]["coverage"] = "complete" if complete else "unknown"
        if role in refused:
            roles[role]["refused"] = refused[role]
        projections[role] = (b"".join(json.dumps(row, sort_keys=True, separators=(",", ":"))
                                      .encode() + b"\n" for row in rows[role])
                             if complete and rows[role] else None)
    return {"status": "CAPTURED", "reasons": sorted(set(refused.values())),
            "projections": projections,
            "diagnostic": {"roles": roles, "unauthenticated_ingress": unauthenticated,
                           "capacity_events": capacity_events, "seal_outcome": verified["outcome"],
                           "primary_effect": "none (decision 5)"}}


def violation_counts(result: dict[str, Any]) -> Counter[str]:
    """All sender-attributed violations in a diagnostic, by reason."""
    total: Counter[str] = Counter()
    for role in result["diagnostic"]["roles"].values():
        total.update(role["violations"])
    return total
