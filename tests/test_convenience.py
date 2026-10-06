"""Tests for skillc/convenience.py (issue #273, protocol.md 10.6).

Phase wall times are checked against hand-computed deltas. The three
not-captured proxies and tokens are checked against their stated sentinel,
not against a computed value - there is no computed value, and a test that
expected one would be asserting a capability this module does not have.
"""

from __future__ import annotations

import pytest

from skillc import convenience as conv

LE = conv.LifecycleEvent


def _events(*pairs: tuple[str, str]) -> list[conv.LifecycleEvent]:
    return [LE(event=event, at=at) for event, at in pairs]


# --------------------------------------------------------------- phase_wall_times

def test_phase_wall_times_hand_computed() -> None:
    events = _events(
        ("planned", "2026-09-26T12:00:00Z"),
        ("dispatched", "2026-09-26T12:00:01Z"),
        ("started", "2026-09-26T12:00:03Z"),
        ("stopped", "2026-09-26T12:00:08Z"),
    )
    intervals = conv.phase_wall_times(events)
    assert intervals == (
        conv.PhaseInterval("planned", "dispatched", 1.0),
        conv.PhaseInterval("dispatched", "started", 2.0),
        conv.PhaseInterval("started", "stopped", 5.0),
    )


def test_phase_wall_times_handles_fractional_seconds() -> None:
    events = _events(
        ("planned", "2026-09-26T12:00:00.250000Z"),
        ("dispatched", "2026-09-26T12:00:01.750000Z"),
    )
    (interval,) = conv.phase_wall_times(events)
    assert interval.seconds == pytest.approx(1.5)


def test_phase_wall_times_zero_duration_is_not_an_error() -> None:
    """Two events landing in the same instant is a tie, not disorder."""
    events = _events(
        ("planned", "2026-09-26T12:00:00Z"),
        ("dispatched", "2026-09-26T12:00:00Z"),
    )
    (interval,) = conv.phase_wall_times(events)
    assert interval.seconds == pytest.approx(0.0)


def test_phase_wall_times_refuses_empty() -> None:
    """missing-data control: an attempt with no recorded lifecycle reports
    no phases, never a fabricated zero-length one."""
    with pytest.raises(conv.ConvenienceRefused):
        conv.phase_wall_times([])


def test_phase_wall_times_refuses_events_not_starting_at_planned() -> None:
    events = _events(("dispatched", "2026-09-26T12:00:00Z"))
    with pytest.raises(conv.ConvenienceRefused):
        conv.phase_wall_times(events)


def test_phase_wall_times_refuses_an_event_outside_the_vocabulary() -> None:
    events = _events(
        ("planned", "2026-09-26T12:00:00Z"),
        ("teleported", "2026-09-26T12:00:01Z"),
    )
    with pytest.raises(conv.ConvenienceRefused):
        conv.phase_wall_times(events)


def test_phase_wall_times_refuses_out_of_order_events() -> None:
    """A later event timestamped earlier than its predecessor must refuse
    rather than report a negative duration (cross-model review pattern from
    #273's reliability work, applied here by the same discipline)."""
    events = _events(
        ("planned", "2026-09-26T12:00:05Z"),
        ("dispatched", "2026-09-26T12:00:01Z"),
    )
    with pytest.raises(conv.ConvenienceRefused):
        conv.phase_wall_times(events)


def test_phase_wall_times_refuses_a_non_string_timestamp() -> None:
    events = [conv.LifecycleEvent(event="planned", at="2026-09-26T12:00:00Z"), conv.LifecycleEvent(event="dispatched", at=None)]  # type: ignore[arg-type]
    with pytest.raises(conv.ConvenienceRefused):
        conv.phase_wall_times(events)


def test_phase_wall_times_refuses_an_unparseable_timestamp() -> None:
    events = _events(
        ("planned", "not-a-timestamp"),
        ("dispatched", "2026-09-26T12:00:01Z"),
    )
    with pytest.raises(conv.ConvenienceRefused):
        conv.phase_wall_times(events)


def test_phase_wall_times_missing_middle_events_produces_no_fabricated_gap() -> None:
    """An attempt that jumps straight from planned to captured (every
    in-between event absent from its record) reports exactly one interval
    spanning that gap - not an UNKNOWN, not a fabricated per-phase split."""
    events = _events(
        ("planned", "2026-09-26T12:00:00Z"),
        ("captured", "2026-09-26T12:00:09Z"),
    )
    intervals = conv.phase_wall_times(events)
    assert intervals == (conv.PhaseInterval("planned", "captured", 9.0),)


# --------------------------------------------------------------- convenience_summary

def test_convenience_summary_reports_real_phases_beside_honest_sentinels() -> None:
    events = _events(
        ("planned", "2026-09-26T12:00:00Z"),
        ("dispatched", "2026-09-26T12:00:01Z"),
    )
    summary = conv.convenience_summary(events)
    assert summary.phase_wall_times == (conv.PhaseInterval("planned", "dispatched", 1.0),)
    assert summary.instruction_length == conv.NOT_CAPTURED
    assert summary.clarification_correction_turns == conv.NOT_CAPTURED
    assert summary.approvals == conv.NOT_CAPTURED
    assert summary.tokens == conv.UNKNOWN


def test_convenience_summary_propagates_the_same_refusal() -> None:
    with pytest.raises(conv.ConvenienceRefused):
        conv.convenience_summary([])


def test_not_captured_and_unknown_are_distinct_sentinels() -> None:
    """The two absences are not interchangeable: NOT_CAPTURED means no field
    exists at all, UNKNOWN is the schema's own declared-future-observation
    vocabulary (records.md's cost/token note). Collapsing them would lose
    that distinction for whoever reads a report later."""
    assert conv.NOT_CAPTURED != conv.UNKNOWN
    assert conv.NOT_CAPTURED == conv.NOT_CAPTURED.lower()
    assert conv.UNKNOWN == conv.UNKNOWN.upper()
