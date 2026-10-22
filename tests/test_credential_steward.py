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


@pytest.mark.parametrize(("first", "second"), [
    (1, 1),   # replayed
    (1, 3),   # a gap: event 2 was sent and never arrived
    (2, 3),   # the record never saw event 1
])
def test_red_a_replayed_skipped_or_late_starting_seq_is_refused(first: int, second: int) -> None:
    s = cs.CredentialStewardSession("a-1")
    event = {"op": "credential_steward", "opens": 4, "closes": 4}
    if first != 1:
        with pytest.raises(ChannelRefusal, match="missing or replayed"):
            s.decide({**event, "event": "armed", "seq": first})
    else:
        s.decide({**event, "event": "armed", "seq": first})
        with pytest.raises(ChannelRefusal, match="missing or replayed"):
            s.decide({**event, "event": "withdrawn", "seq": second})
    assert s.finalize(1)["status"] == "unknown"


def test_red_a_late_event_is_refused() -> None:
    s = _session("armed")
    s.finalize(1)
    with pytest.raises(ChannelRefusal, match="finalized"):
        s.decide({"op": "credential_steward", "event": "stopped", "seq": 2, "opens": 0, "closes": 0})


def test_the_absent_record_blocks() -> None:
    assert cs.credit_block(None) == "not credited: the credential steward record is absent"


# --- the driver, against a fake backend that plays the steward --------------

class _FakeSteward:
    """Answers the driver's root calls the way the in-container steward
    would, by sending its events into the session."""

    def __init__(self, session: cs.CredentialStewardSession, *, start_ok: bool = True, arms: bool = True,
                 signal_ok: bool = True, restore_ok: bool = True) -> None:
        self.session, self.start_ok, self.arms, self.signal_ok, self.restore_ok = session, start_ok, arms, signal_ok, restore_ok
        self.calls: list[str] = []
        self.seq = 0

    def _emit(self, event: str) -> None:
        self.seq += 1
        self.session.decide({"op": "credential_steward", "event": event, "seq": self.seq, "opens": 4, "closes": 4})

    def start_root_daemon_in_attempt(self, handle: object, argv: Any, timeout: float | None = None) -> bool:
        self.calls.append("start")
        if self.start_ok and self.arms:
            self._emit("armed")
            self._emit("withdrawn")
        return self.start_ok

    def root_output_in_attempt(self, handle: object, argv: Any, timeout: float | None = None,
                               max_bytes: int = 1 << 20) -> bytes | None:
        script = argv[2] if argv[0] == "sh" else " ".join(argv)
        if "kill -USR1" in script:
            # The steward restores the file itself, then re-arms - or reports
            # `error` and never arms when the restore fails.
            self.calls.append("restore+rearm")
            if self.signal_ok and self.arms:
                self._emit("armed" if self.restore_ok else "error")
                if self.restore_ok:
                    self._emit("withdrawn")
            return b"" if self.signal_ok else None
        if "kill -TERM" in script:
            self.calls.append("stop")
            self._emit("stopped")
            return b""
        if argv[0] == "cat":
            self.calls.append("vault")
            return b'{"tokens": {}}'
        raise AssertionError(argv)


def _driver(**kw: Any) -> tuple[cs.CredentialSteward, _FakeSteward, list[bytes]]:
    session = cs.CredentialStewardSession("a-1")
    placed: list[bytes] = []
    driver = cs.CredentialSteward(session, "/home/candidate/.codex", wait_s=0.2, sleep=lambda s: None)
    return driver, _FakeSteward(session, **kw), placed


def test_a_turn_and_a_resume_end_held_and_rearm_comes_before_restore() -> None:
    driver, fake, placed = _driver()
    driver.start(fake, object(), placed.append)
    driver.restore_for_turn(fake, object())
    driver.stop(fake, object())
    assert placed == [cs.STEWARD_SOURCE.read_bytes()]
    # No controller-side root copy at all (#518 review): the steward restores.
    assert fake.calls == ["start", "restore+rearm", "vault", "stop"]
    assert driver.record()["status"] == "held"


@pytest.mark.parametrize(("kw", "match"), [
    ({"start_ok": False}, "could not be started"),
    ({"arms": False}, "never reported armed"),
])
def test_red_a_steward_that_does_not_start_or_arm_refuses_the_attempt(kw: dict[str, Any], match: str) -> None:
    driver, fake, placed = _driver(**kw)
    with pytest.raises(cs.StewardFailed, match=match):
        driver.start(fake, object(), placed.append)


@pytest.mark.parametrize(("kw", "match"), [
    ({"signal_ok": False}, "could not be signalled"),
    ({"restore_ok": False}, "never restored and re-armed"),
])
def test_red_a_resume_the_steward_cannot_cover_is_refused(kw: dict[str, Any], match: str) -> None:
    driver, fake, placed = _driver(**kw)
    driver.start(fake, object(), placed.append)
    with pytest.raises(cs.StewardFailed, match=match):
        driver.restore_for_turn(fake, object())


def test_red_a_resume_with_no_rearm_ack_is_refused_before_any_restore() -> None:
    driver, fake, placed = _driver()
    driver.start(fake, object(), placed.append)
    fake.arms = False
    with pytest.raises(cs.StewardFailed, match="never restored and re-armed"):
        driver.restore_for_turn(fake, object())


def test_stop_reads_the_vault_first_and_runs_once() -> None:
    """#518 review: `finish()` runs after the container is stopped, so the
    stop in `before_stop` must be the one that counts, and a second call
    must not reach the (gone) container."""
    driver, fake, placed = _driver()
    driver.start(fake, object(), placed.append)
    driver.stop(fake, object())
    driver.stop(fake, object())
    assert fake.calls == ["start", "vault", "stop"]
    assert driver.vault_bytes(fake, object()) == b'{"tokens": {}}' and fake.calls[-1] == "stop"
    assert driver.record()["status"] == "held"


def test_a_missing_stop_reads_unknown() -> None:
    driver, fake, placed = _driver()
    driver.start(fake, object(), placed.append)
    assert driver.record()["status"] == "unknown"  # never stopped


def test_the_steward_watches_the_backends_own_codex_home() -> None:
    from skillc import docker_backend as d
    assert cs.HOME_CODEX == f"{d.CONTAINER_HOME}/.codex"
    assert cs.STEWARD_SOURCE.is_file()
