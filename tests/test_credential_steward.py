"""#518 A: the controller's credential-steward record, which fails closed."""

from __future__ import annotations

from typing import Any

import pytest

from skillc import credential_steward as cs
from skillc.decide_reply_channel import ChannelRefusal


def _session(*names: str) -> cs.CredentialStewardSession:
    s = cs.CredentialStewardSession("a-1")
    for seq, name in enumerate(names, start=1):
        s.decide({"op": "credential_steward", "event": name, "seq": seq, "opens": 4, "closes": 4})
    return s


def test_one_launch_withdrawn_quietly_and_stopped_is_held() -> None:
    record = _session("armed", "withdrawn", "stopped").finalize(expected_arms=1)
    assert record["status"] == "held" and cs.credit_block(record) is None and cs.stop_reason(record) is None


def test_a_resume_needs_its_own_arm_and_withdrawal() -> None:
    assert _session("armed", "withdrawn", "armed", "withdrawn", "stopped").finalize(2)["status"] == "held"
    assert _session("armed", "withdrawn", "stopped").finalize(2)["status"] == "unknown"  # the resume never armed


@pytest.mark.parametrize(("names", "status", "why"), [
    (("armed", "withdrawn", "refreshed-captured", "stopped"), "refreshed", "re-appeared"),
    (("armed", "withdrawn-at-deadline", "stopped"), "unknown", "at-deadline 1"),
    (("armed", "stopped"), "unknown", "arms 1/1"),                       # never withdrawn
    (("armed", "withdrawn"), "unknown", "stopped False"),                # the steward died before the end
    (("armed", "withdrawn", "error", "stopped"), "unknown", "unknown"),
    ((), "unknown", "arms 0/1"),                                         # never started
])
def test_red_every_record_that_is_not_held_blocks_credit_and_stops(names: tuple[str, ...], status: str,
                                                                    why: str) -> None:
    record = _session(*names).finalize(expected_arms=1)
    assert record["status"] == status
    block = cs.credit_block(record)
    assert block is not None and why in block and cs.stop_reason(record) is not None


@pytest.mark.parametrize("request_", [
    {"op": "credential_steward", "event": "withdrawn", "seq": 1, "opens": 4},                   # a missing key
    {"op": "credential_steward", "event": "gone", "seq": 1, "opens": 4, "closes": 4},          # unknown event
    {"op": "credential_steward", "event": "armed", "seq": True, "opens": 4, "closes": 4},      # bool is not int
    {"op": "credential_steward", "event": "armed", "seq": 1, "opens": -1, "closes": 4},
    {"op": "codex_guard", "event": "armed", "seq": 1, "opens": 4, "closes": 4},
])
def test_red_a_malformed_event_makes_the_channel_unavailable(request_: dict[str, Any]) -> None:
    s = cs.CredentialStewardSession("a-1")
    with pytest.raises(ChannelRefusal):
        s.decide(request_)
    assert s.channel_unavailable and s.finalize(0)["status"] == "unknown"


def test_red_a_replayed_seq_and_a_late_event_are_refused() -> None:
    s = _session("armed")
    with pytest.raises(ChannelRefusal, match="seq did not increase"):
        s.decide({"op": "credential_steward", "event": "withdrawn", "seq": 1, "opens": 4, "closes": 4})
    s.finalize(1)
    with pytest.raises(ChannelRefusal, match="finalized"):
        s.decide({"op": "credential_steward", "event": "stopped", "seq": 9, "opens": 0, "closes": 0})


def test_the_absent_record_blocks() -> None:
    assert cs.credit_block(None) == "not credited: the credential steward record is absent"
