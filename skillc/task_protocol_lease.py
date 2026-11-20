"""Endpoint leases and the startup barrier for the task-protocol stream
(#620 PR-B, B4).

See `docs/specs/evaluation-facility/task-protocol-stream.md`, section 2, and
decision 4, accepted 2026-11-17. This module is pure. It holds the launch
inventory, issues one fresh endpoint lease per planned sandbox, binds each lease
to its runtime instance and its independently captured startup session, runs
the one startup barrier, and answers the receiver's question "whose endpoint is
this?". It produces B2's `binding`, `barrier` and `revocation` records but does
not write them; the caller appends them durably before anything depends on them.

THE TRUST ROOT IS THE CONTROLLER'S OWN INVENTORY. A principal is a launch slot
the controller planned before launch. Its identity comes from the endpoint's
lease, never from a request. The startup session comes from the trusted startup
channel (for a Codex exec, `controller_turns.session_id_from_header` on the
independently drained header). It is never an agent's claimed replacement.

ONE BARRIER, THEN NOTHING CHANGES. Before the first offer, `barrier()`
finalizes every planned slot as `bound`, `unstarted` or `unavailable` and
freezes them. Nonstarts stay in the population. The clock origin was fixed at
`Inventory` time and never restarts. After the barrier, no bind, rebind or
status change is accepted. Only revocation remains, and revocation is
one-way.

REVOCATION BY CLOSE, NEVER BY REPLACE. A lease's endpoint id and runtime instance
are used once. An endpoint is never reassigned, and a runtime instance (a
container) that has held a lease can never bind another. A revoked lease stops
answering `principal_for` for good. The controller never re-binds a socket at
the same path for a live sandbox (the 2026-11-20 mount-shape ruling), so a
receiver restart is lost ingress (UNKNOWN), never a new endpoint for the same
slot.

PRIVATE STAYS PRIVATE. Endpoint ids, runtime instance ids and session ids
reach the journal only as digests: `bindings_digest` over the whole frozen
mapping, and the caller's own `evidence_digest` per binding.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Any

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_PRIVATE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_TOKEN = re.compile(r"[a-z][a-z0-9-]{0,63}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_INT = (1 << 63) - 1

STATES = ("bound", "unstarted", "unavailable")


class LeaseError(ValueError):
    """A refused lease, binding or barrier operation. Never task failure."""


def _name(value: object) -> str:
    if type(value) is not str or not _NAME.fullmatch(value):
        raise LeaseError("bounded name required")
    return value


def _private(value: object) -> str:
    if type(value) is not str or not _PRIVATE.fullmatch(value):
        raise LeaseError("bounded private identifier required")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise LeaseError("sha256 reference required")
    return value


def _sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Slot:
    """One planned launch slot. `principal` is the lease and journal name;
    the rest is the declared public task binding PR-A's plan carries."""

    principal: str
    role: str
    task: str
    generation: int
    revision: int
    nonce: str

    def __post_init__(self) -> None:
        for value in (self.principal, self.role, self.task, self.nonce):
            _name(value)
        if type(self.generation) is not int or not 0 <= self.generation <= _MAX_INT:
            raise LeaseError("nonbool generation required")
        if type(self.revision) is not int or not 1 <= self.revision <= _MAX_INT:
            raise LeaseError("positive nonbool revision required")


@dataclass(frozen=True)
class Inventory:
    """The prelaunch population, frozen before launch. Its digest is B2's
    `population_digest`; `clock_origin_ns` is the attempt's one origin."""

    attempt_id: str
    declaration_digest: str
    slots: tuple[Slot, ...]
    clock_origin_ns: int

    def __post_init__(self) -> None:
        _name(self.attempt_id)
        _digest(self.declaration_digest)
        if type(self.slots) is not tuple or not self.slots or any(
                type(s) is not Slot for s in self.slots):
            raise LeaseError("nonempty planned slot population required")
        for key in ("principal", "role"):
            values = [getattr(s, key) for s in self.slots]
            if len(set(values)) != len(values):
                raise LeaseError("unique planned principals and roles required")
        if type(self.clock_origin_ns) is not int or not 0 <= self.clock_origin_ns <= _MAX_INT:
            raise LeaseError("integer clock origin required")

    def fields(self) -> dict[str, Any]:
        return {"attempt_id": self.attempt_id, "declaration_digest": self.declaration_digest,
                "clock_origin_ns": self.clock_origin_ns,
                "slots": [asdict(s) for s in self.slots]}

    @property
    def digest(self) -> str:
        return _sha(self.fields())

    @property
    def principals(self) -> tuple[str, ...]:
        return tuple(s.principal for s in self.slots)


@dataclass(frozen=True)
class Lease:
    principal: str
    endpoint_id: str


@dataclass
class _Entry:
    slot: Slot
    lease: Lease | None = None
    runtime_instance: str | None = None
    session_id: str | None = None
    evidence_digest: str | None = None
    state: str | None = None
    reason: str | None = None
    revoked: bool = False


class Leases:
    """Lease state for one planned attempt. Not thread-safe by itself; the
    receiver serializes calls with its journal lock.

    `used_instances` and `used_endpoints` are runtime instances and endpoint
    ids held by any earlier attempt's leases; neither may be leased again."""

    def __init__(self, inventory: Inventory, *, used_instances: Iterable[str] = (),
                 used_endpoints: Iterable[str] = (),
                 token: Callable[[], str] = lambda: secrets.token_hex(16)) -> None:
        if type(inventory) is not Inventory:
            raise LeaseError("frozen inventory required")
        self.inventory = inventory
        self._entries = {s.principal: _Entry(s) for s in inventory.slots}
        self._used_instances = {_private(i) for i in used_instances}
        #: Runtime instances presented in THIS attempt, by the slot that
        #: presented them (bound or not).
        self._presented: dict[str, str] = {}
        self._used_endpoints = {_private(e) for e in used_endpoints}
        self._token = token
        self._barrier: dict[str, Any] | None = None

    # -- before the barrier ----------------------------------------------------

    def _open(self, principal: str) -> _Entry:
        if self._barrier is not None:
            raise LeaseError("startup barrier already passed")
        if principal not in self._entries:
            raise LeaseError("unplanned principal")
        return self._entries[principal]

    def issue(self, principal: str) -> Lease:
        """One fresh endpoint lease for a slot, before its sandbox starts."""
        entry = self._open(principal)
        if entry.lease is not None or entry.state is not None:
            raise LeaseError("slot already leased or resolved")
        endpoint = _private(self._token())
        if endpoint in self._used_endpoints:
            raise LeaseError("endpoint id already used")
        self._used_endpoints.add(endpoint)
        entry.lease = Lease(principal, endpoint)
        return entry.lease

    def bind(self, principal: str, *, runtime_instance: str, session_id: str | None,
             evidence_digest: str) -> dict[str, Any]:
        """Bind a leased slot to its actual runtime instance and its
        independently captured startup session. Returns B2's `binding` record.

        Identities are one-to-one, so a collision cannot say which binding is
        wrong:

        - A runtime instance or session that ANOTHER slot of this attempt
          already presented makes BOTH slots `unavailable`.
        - A runtime instance an EARLIER attempt held marks only this slot.
        - A missing session (None) or a second bind for this slot marks this
          slot.

        Each gives no task credit, and none accepts an agent's replacement
        identity."""
        entry = self._open(principal)
        if entry.lease is None:
            raise LeaseError("slot has no lease")
        instance = _private(runtime_instance)
        evidence = _digest(evidence_digest)
        if entry.state is not None:
            entry.state, entry.reason = "unavailable", "conflicting-startup-binding"
            raise LeaseError("slot already resolved")
        other = self._presented.get(instance)
        if other is not None and other != principal:
            self._collide(entry, self._entries[other])
            raise LeaseError("runtime instance presented by two slots of this attempt")
        if instance in self._used_instances:
            entry.state, entry.reason = "unavailable", "runtime-instance-reused"
            raise LeaseError("runtime instance already held a lease")
        # This instance now held a lease, whatever happens next.
        self._used_instances.add(instance)
        self._presented[instance] = principal
        entry.runtime_instance = instance
        if session_id is None:
            entry.state, entry.reason = "unavailable", "missing-startup-session"
            raise LeaseError("no independently captured startup session")
        session = _private(session_id)
        holder = next((e for e in self._entries.values()
                       if e is not entry and e.session_id == session), None)
        entry.session_id = session
        if holder is not None:
            self._collide(entry, holder)
            raise LeaseError("startup session presented by two slots of this attempt")
        entry.evidence_digest, entry.state = evidence, "bound"
        return {"principal": principal, "evidence_digest": evidence}

    @staticmethod
    def _collide(entry: _Entry, holder: _Entry) -> None:
        for slot in (entry, holder):
            slot.state, slot.reason = "unavailable", "startup-identity-collision"

    def mark_unstarted(self, principal: str) -> None:
        """A planned slot that was positively never started. It stays in the
        population."""
        entry = self._open(principal)
        if entry.state is not None:
            raise LeaseError("slot already resolved")
        entry.state, entry.reason = "unstarted", "not-started"

    def mark_unavailable(self, principal: str, reason: str) -> None:
        """A slot whose start or binding cannot be established."""
        entry = self._open(principal)
        if type(reason) is not str or not _TOKEN.fullmatch(reason):
            raise LeaseError("closed reason token required")
        if entry.state != "bound":
            entry.state, entry.reason = "unavailable", reason
        else:
            raise LeaseError("a bound slot is revoked after the barrier, never unbound")

    # -- the barrier -------------------------------------------------------------

    def barrier(self) -> dict[str, Any]:
        """Finalize every planned slot and freeze. Returns B2's `barrier`
        record. A slot still unresolved refuses the barrier: nothing is
        guessed into `unstarted`."""
        if self._barrier is not None:
            raise LeaseError("startup barrier already passed")
        unresolved = [p for p, e in self._entries.items() if e.state is None]
        if unresolved:
            raise LeaseError("every planned slot must be resolved before the barrier")
        mapping = [{"principal": e.slot.principal, "state": e.state, "reason": e.reason,
                    "endpoint_id": e.lease.endpoint_id if e.lease else None,
                    "runtime_instance": e.runtime_instance, "session_id": e.session_id,
                    "evidence_digest": e.evidence_digest}
                   for e in (self._entries[p] for p in self.inventory.principals)]
        self._barrier = {"bindings_digest": _sha({"inventory": self.inventory.digest,
                                                  "slots": mapping}),
                         "slots": [{"principal": m["principal"], "state": m["state"]}
                                   for m in mapping]}
        return dict(self._barrier, slots=[dict(s) for s in self._barrier["slots"]])

    @property
    def passed(self) -> bool:
        return self._barrier is not None

    def bound_sessions(self) -> dict[str, str | None]:
        """Per role, the bound startup session or None, for PR-A's
        `freeze_plan` after the barrier. Unstarted and unavailable slots keep
        their place with no session."""
        if self._barrier is None:
            raise LeaseError("sessions are final only after the barrier")
        return {e.slot.role: (e.session_id if e.state == "bound" else None)
                for e in (self._entries[p] for p in self.inventory.principals)}

    # -- after the barrier ---------------------------------------------------------

    def principal_for(self, endpoint_id: str, runtime_instance: str) -> str | None:
        """The receiver's lookup: the principal whose ACTIVE, bound lease is
        this endpoint AND whose recorded runtime instance is the one the
        caller independently observed now. Anything else is None (UNKNOWN),
        never a best guess."""
        if self._barrier is None:
            return None
        for entry in self._entries.values():
            if (entry.lease is not None and entry.lease.endpoint_id == endpoint_id
                    and entry.state == "bound" and not entry.revoked
                    and entry.runtime_instance == runtime_instance):
                return entry.slot.principal
        return None

    def resume(self, principal: str, session_id: str) -> bool:
        """A resume of the SAME observed session keeps its lease and clock;
        any other session does not (and is not rebound)."""
        if self._barrier is None or principal not in self._entries:
            return False
        entry = self._entries[principal]
        return entry.state == "bound" and not entry.revoked and entry.session_id == session_id

    def revoke(self, principal: str, reason: str) -> dict[str, Any]:
        """One-way. Returns B2's `revocation` record; the caller appends it
        durably before relying on the revocation."""
        if principal not in self._entries:
            raise LeaseError("unplanned principal")
        if type(reason) is not str or not _TOKEN.fullmatch(reason):
            raise LeaseError("closed reason token required")
        entry = self._entries[principal]
        if entry.lease is None or entry.revoked:
            raise LeaseError("no active lease to revoke")
        entry.revoked = True
        return {"principal": principal, "reason": reason}
