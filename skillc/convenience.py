"""Convenience proxies (issue #273, protocol.md 10.6).

protocol.md 10.6 ("Convenience proxies") names four things reported beside
success, never folded into a score: instruction length, clarification and
correction turns, approvals split necessary/redundant, and wall time per
phase with tokens where observable.

Three of the four are NOT CAPTURED anywhere in the v2 record schema today.
No producer persists the prompt text or its length - protocol.md 10.1's own
"recorded in full" requirement is unmet, `agent-observation` keeps only the
boolean `prompt_delivered` (filed as a nit on skillc #20, found while
building this). No record field counts an interactive clarification or
correction turn, and none names an in-run approval event at all. This module
reports those as `NOT_CAPTURED` rather than guessing a number, declaring
`not_applicable` with no interactivity signal to justify it, or reconstructing
a length from `goal.md` plus the arm's declared instruction at report time -
that would be reconstruction from source files that can move on after the
run, never capture of what the subject actually saw.

Wall time per phase is real. `attempt-lifecycle.events` is an ordered,
non-empty list of `{event, at}` pairs starting at `planned`
(`skillc.records.LIFECYCLE_EVENTS`). Per-phase wall time is the delta between
each consecutive pair, labeled with the controller's own event names - never
a canonical phase name this module invents, so an event the controller never
wrote produces no interval rather than a fabricated one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from skillc.records import LIFECYCLE_EVENTS

#: protocol.md 10.6 proxies with no backing record field (skillc #20).
#: Lowercase, matching `reliability.INSUFFICIENT` - a sentinel this module's
#: own reporting layer returns, not a value copied from the record schema.
NOT_CAPTURED = "not_captured"

#: protocol.md 10.6: "tokens where observable, otherwise UNKNOWN." Uppercase,
#: matching the schema's own UNKNOWN vocabulary (records.py's lifecycle and
#: observation statuses) rather than this module's NOT_CAPTURED sentinel -
#: tokens are a declared future observation (records.md: "Cost/token
#: observation ... join this list when a producer can report them"), a
#: different kind of absence than a proxy with no field at all.
UNKNOWN = "UNKNOWN"


class ConvenienceRefused(ValueError):
    """A convenience proxy was asked for over input this module refuses -
    empty, malformed or out-of-order lifecycle events - rather than fabricate
    a negative or partial duration."""


def _refuse(message: str) -> ConvenienceRefused:
    return ConvenienceRefused(f"convenience: {message}")


@dataclass(frozen=True)
class LifecycleEvent:
    event: str
    at: str


@dataclass(frozen=True)
class PhaseInterval:
    from_event: str
    to_event: str
    seconds: float


@dataclass(frozen=True)
class ConvenienceSummary:
    """protocol.md 10.6, one struct per attempt. The three string fields are
    always their stated sentinel today - this is not a partial result, it is
    the honest answer for what the v2 schema can report."""

    phase_wall_times: tuple[PhaseInterval, ...]
    instruction_length: str
    clarification_correction_turns: str
    approvals: str
    tokens: str


def _parse_at(value: object, event: str) -> datetime:
    if not isinstance(value, str):
        raise _refuse(f"event {event!r} has a non-string timestamp {value!r}")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise _refuse(f"event {event!r} has an unparseable timestamp {value!r}: {exc}") from None


def phase_wall_times(events: Sequence[LifecycleEvent]) -> tuple[PhaseInterval, ...]:
    """Per-phase wall time from attempt-lifecycle's own event list.

    Refuses: an empty list; an event list that does not start at `planned`
    (records.py's own rule for the stored record - re-checked here because
    this module consumes raw stored data, a trust boundary of its own, not
    a value this module produced itself); any event name outside
    `LIFECYCLE_EVENTS`; and any pair whose timestamps are not non-decreasing
    (out-of-order events) - never a negative duration.
    """
    if not events:
        raise _refuse("no events: an attempt with no recorded lifecycle has no phases to report")
    if events[0].event != "planned":
        raise _refuse(f"events do not start at planned, start at {events[0].event!r}")
    for ev in events:
        if ev.event not in LIFECYCLE_EVENTS:
            raise _refuse(f"event {ev.event!r} is outside the lifecycle vocabulary")

    intervals: list[PhaseInterval] = []
    previous_at = _parse_at(events[0].at, events[0].event)
    for left, right in pairwise(events):
        right_at = _parse_at(right.at, right.event)
        if right_at < previous_at:
            raise _refuse(
                f"{right.event!r} at {right.at!r} is earlier than {left.event!r} at "
                f"{left.at!r} - events are not in chronological order"
            )
        intervals.append(
            PhaseInterval(from_event=left.event, to_event=right.event, seconds=(right_at - previous_at).total_seconds())
        )
        previous_at = right_at
    return tuple(intervals)


def convenience_summary(events: Sequence[LifecycleEvent]) -> ConvenienceSummary:
    """The full protocol.md 10.6 report for one attempt: real phase wall
    times beside the three honestly-unavailable proxies, never a guess."""
    return ConvenienceSummary(
        phase_wall_times=phase_wall_times(events),
        instruction_length=NOT_CAPTURED,
        clarification_correction_turns=NOT_CAPTURED,
        approvals=NOT_CAPTURED,
        tokens=UNKNOWN,
    )
