"""The task-protocol decision state machine (#620 PR-B, B3).

See `docs/specs/evaluation-facility/task-protocol-stream.md`, sections 1 and 4,
and decisions 3 and 6, accepted 2026-11-17. This module is pure: it holds no
socket, journal, lease or clock. The receiver (B5) authenticates the sender
from its endpoint lease, parses the bytes with `task_protocol_schema`, and then
asks this machine what to decide.

TWO PHASES, SO STATE NEVER RUNS AHEAD OF CUSTODY. `propose` returns the
decision, its receipt and the exact journal record (B2's `kind` and fields)
without changing anything. The caller appends that record durably, and only
then calls `commit` with the journal sequence number it got back. A failed
append leaves the machine exactly where it was, and no receipt is sent. This
is the design's "complete fsynced record before any receipt or state advance".

WHAT THE MACHINE DECIDES. Each planned principal has exactly one declared offer
(decision 3).

- `offer` returns that offer. Asking again is harmless and returns it again.
- `ack` is valid on the principal's own current offer once it has been offered.
- `complete` is valid only after an ack.
- `refuse` is retained as a refusal. It is not terminal, and it never becomes a
  task failure here.

Every decided request number is remembered with its normalized digest
(decision 6):

- The same number with the same digest is an idempotent retry. It returns the
  ORIGINAL receipt and is journaled as a `retry` of the original record. It is
  never a second semantic completion.
- The same number with different content is a `protocol-conflict`.

Deadlines and the fence:

- A request decided after the common deadline is `late`. On time means
  `elapsed_ns <= deadline_ns`, and the comparison is in integer nanoseconds.
- After the fence, every request, a retry included, is `fenced`. It is journaled
  as a `rejection` row, because B2 accepts no decision after a fence.
- Nothing renews a deadline, an offer or a lease.

VIOLATIONS ARE NARROW AND ATTRIBUTED TO THE SENDER. `Proposal.violation` is True
only for the design's positive rules, and the principal it names is always the
authenticated sender, never the owner of an offer the request names. Those rules
are:

- changed content under a used request number;
- a second distinct completion;
- an ack after completion;
- a complete before ack;
- an old or wrong offer on a proven current lease.

Everything else is retained without being a violation: a duplicate ack before
completion, a refusal after completion, a late or fenced request, a malformed
request. Whether a violation becomes a wave FAIL is the verdict's question (B6),
not this machine's.

Stdlib only, per AGENTS.md.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from .task_protocol_schema import Receipt, Rejected, Request

_PRINCIPAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_MAX_INT = (1 << 63) - 1

#: Rejection reasons that are positive, attributable protocol violations.
VIOLATIONS = frozenset({"protocol-conflict", "after-complete", "complete-before-ack",
                        "wrong-offer", "stale-offer"})


class StateError(ValueError):
    """A caller error (an unplanned principal, an out-of-order commit), never
    a protocol decision and never a participant-visible message."""


@dataclass(frozen=True)
class Offer:
    principal: str
    offer_id: str

    def __post_init__(self) -> None:
        for value in (self.principal, self.offer_id):
            if type(value) is not str or not _PRINCIPAL.fullmatch(value):
                raise StateError("bounded principal and offer id required")


@dataclass(frozen=True)
class Plan:
    """The frozen, already-declared offers: exactly one per planned principal,
    the common deadline on the controller's elapsed clock, and the offer ids of
    earlier generations, which are `stale-offer` rather than `wrong-offer`."""

    offers: tuple[Offer, ...]
    deadline_ns: int
    retired_offer_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if type(self.offers) is not tuple or not self.offers:
            raise StateError("nonempty offer population required")
        principals = [o.principal for o in self.offers]
        ids = [o.offer_id for o in self.offers]
        if len(set(principals)) != len(principals) or len(set(ids)) != len(ids):
            raise StateError("one unique offer per principal required")
        if type(self.deadline_ns) is not int or not 0 <= self.deadline_ns <= _MAX_INT:
            raise StateError("integer deadline required")
        if type(self.retired_offer_ids) is not frozenset or set(ids) & self.retired_offer_ids:
            raise StateError("retired offers must be distinct from current ones")
        for retired in self.retired_offer_ids:
            Offer("x", retired)

    def offer_for(self, principal: str) -> Offer:
        for offer in self.offers:
            if offer.principal == principal:
                return offer
        raise StateError("unplanned principal")


@dataclass(frozen=True)
class Proposal:
    """What to journal and what to reply, before anything changes.

    `kind` and `fields` are B2's `Journal.append(kind, **fields)` arguments,
    except that a `retry` row's `original_seq` is already filled in. `effect`
    names the state flag `commit` sets: `offered`, `acked`, `completed`,
    `refused`, or None."""

    principal: str
    kind: str
    fields: dict[str, Any]
    receipt: Receipt
    violation: bool
    effect: str | None
    request: int | None


@dataclass
class _Prior:
    digest: str
    seq: int
    receipt: Receipt


@dataclass
class _Principal:
    offered: bool = False
    acked: bool = False
    completed: bool = False
    refused: bool = False
    requests: dict[int, _Prior] = field(default_factory=dict)


class Machine:
    """One planned attempt's protocol state. Not thread-safe by itself: the
    receiver calls it under the same lock that serializes the journal."""

    def __init__(self, plan: Plan) -> None:
        if type(plan) is not Plan:
            raise StateError("frozen plan required")
        self.plan = plan
        self._state = {o.principal: _Principal() for o in plan.offers}
        self._pending: Proposal | None = None

    def snapshot(self, principal: str) -> dict[str, bool]:
        state = self._lookup(principal)
        return {"offered": state.offered, "acked": state.acked, "completed": state.completed,
                "refused": state.refused}

    def _lookup(self, principal: str) -> _Principal:
        if principal not in self._state:
            raise StateError("unplanned principal")
        return self._state[principal]

    def propose(self, principal: str, parsed: Request | Rejected, elapsed_ns: int, *,
                fenced: bool = False) -> Proposal:
        """Decide without changing state. `principal` is the authenticated
        sender from the endpoint lease; nothing in `parsed` can name one."""
        state = self._lookup(principal)
        if type(elapsed_ns) is not int or elapsed_ns < 0:
            raise StateError("integer elapsed time required")
        if self._pending is not None:
            raise StateError("previous proposal neither committed nor discarded")
        proposal = self._decide(principal, state, parsed, elapsed_ns, fenced)
        self._pending = proposal
        return proposal

    def discard(self) -> None:
        """The append failed or was refused: forget the proposal, change nothing."""
        self._pending = None

    def commit(self, proposal: Proposal, seq: int) -> None:
        """Advance state once `proposal`'s record is durable at `seq`."""
        if proposal is not self._pending:
            raise StateError("commit must follow its own proposal")
        if type(seq) is not int or seq < 1:
            raise StateError("journal sequence required")
        state = self._state[proposal.principal]
        if proposal.effect is not None:
            setattr(state, proposal.effect, True)
        if proposal.kind == "decision" and proposal.request is not None:
            # The FIRST decision for a number is the one retries return; a
            # later conflicting request never replaces it.
            state.requests.setdefault(proposal.request,
                                      _Prior(proposal.fields["request_digest"], seq,
                                             proposal.receipt))
        self._pending = None

    # -- decisions -----------------------------------------------------------

    def _rejection_row(self, principal: str, reason: str, length: int, digest: str,
                       request: int | None, offer_id: str | None = None) -> Proposal:
        return Proposal(principal, "rejection",
                        {"principal": principal, "reason": reason, "length": length,
                         "content_digest": digest},
                        Receipt(request, "rejected", offer_id, reason), False, None, request)

    def _decide(self, principal: str, state: _Principal, parsed: Request | Rejected,
                elapsed_ns: int, fenced: bool) -> Proposal:
        if isinstance(parsed, Rejected):
            return self._rejection_row(principal, parsed.reason, parsed.length,
                                       "sha256:" + parsed.digest, None)
        if not isinstance(parsed, Request):
            raise StateError("parsed request required")
        digest = "sha256:" + parsed.digest
        size = len(parsed.canonical())
        if fenced:
            return self._rejection_row(principal, "fenced", size, digest, parsed.request,
                                       parsed.offer_id)
        prior = state.requests.get(parsed.request)
        if prior is not None:
            if prior.digest == digest:
                return Proposal(principal, "retry",
                                {"principal": principal, "request": parsed.request,
                                 "request_digest": digest, "original_seq": prior.seq},
                                copy.copy(prior.receipt), False, None, parsed.request)
            return self._decision(principal, parsed, digest, "rejected", "protocol-conflict")
        if elapsed_ns > self.plan.deadline_ns:
            return self._decision(principal, parsed, digest, "rejected", "late")
        own = self.plan.offer_for(principal)
        if parsed.op == "offer":
            return self._decision(principal, parsed, digest, "offered", None,
                                  offer_id=own.offer_id, effect="offered")
        if parsed.offer_id != own.offer_id:
            reason = ("stale-offer" if parsed.offer_id in self.plan.retired_offer_ids
                      else "wrong-offer")
            return self._decision(principal, parsed, digest, "rejected", reason)
        if parsed.op == "ack":
            if not state.offered:
                return self._decision(principal, parsed, digest, "rejected", "ack-before-offer")
            if state.completed:
                return self._decision(principal, parsed, digest, "rejected", "after-complete")
            if state.acked:
                return self._decision(principal, parsed, digest, "rejected", "protocol-conflict",
                                      violation=False)
            return self._decision(principal, parsed, digest, "acknowledged", None, effect="acked")
        if parsed.op == "complete":
            if state.completed:
                return self._decision(principal, parsed, digest, "rejected", "after-complete")
            if not state.acked:
                return self._decision(principal, parsed, digest, "rejected",
                                      "complete-before-ack")
            return self._decision(principal, parsed, digest, "completion-claimed", None,
                                  effect="completed")
        if not state.offered:
            return self._decision(principal, parsed, digest, "rejected", "no-current-offer")
        if state.completed:
            return self._decision(principal, parsed, digest, "rejected", "after-complete",
                                  violation=False)
        return self._decision(principal, parsed, digest, "refusal-retained", None,
                              effect="refused")

    def _decision(self, principal: str, parsed: Request, digest: str, decision: str,
                  reason: str | None, *, offer_id: str | None = None, effect: str | None = None,
                  violation: bool | None = None) -> Proposal:
        echoed = offer_id if offer_id is not None else parsed.offer_id
        receipt = Receipt(parsed.request, decision, echoed, reason)
        fields = {"principal": principal, "request": parsed.request, "op": parsed.op,
                  "offer_id": parsed.offer_id if parsed.op != "offer" else echoed,
                  "request_digest": digest, "decision": decision,
                  "reason": reason if reason is not None else parsed.reason}
        if violation is None:
            violation = reason in VIOLATIONS
        return Proposal(principal, "decision", fields, receipt, violation, effect,
                        parsed.request)
