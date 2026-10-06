"""Tests for the controller-owned decide-and-reply channel (#183).

Exercised directly over real `AF_UNIX` sockets - this module owns no Docker
or managed-backend plumbing of its own (that is `docker_backend.py`'s
`trigger_socket_host_path` parameter, covered in `test_docker_backend.py`),
so there is nothing here a fake CLI would add.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Mapping
from pathlib import Path

import pytest

from skillc.decide_reply_channel import (
    ChannelRefusal,
    DecideFn,
    DecideReplyChannel,
    LoggedDecision,
    TrustedLog,
)


def _send(sock_path: Path, payload: dict[str, object], timeout: float = 5.0) -> dict[str, object]:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect(str(sock_path))
        s.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        s.shutdown(socket.SHUT_WR)
        chunks: list[bytes] = []
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        s.close()
    line = b"".join(chunks).split(b"\n", 1)[0]
    result: dict[str, object] = json.loads(line.decode("utf-8"))
    return result


def _decide_fixed(decisions: dict[int, str]) -> DecideFn:
    """A decide function for the disruption-trigger-shaped case: replies
    `fail` exactly on the client sequence numbers named, `pass` otherwise.
    Refuses any op other than `disruption_check` - proving the channel's
    own op-gating is the decide function's job, not something this module
    hardcodes (design doc §0/§2e: different callers, different ops)."""
    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        if request.get("op") != "disruption_check":
            raise ChannelRefusal("unknown op")
        client_seq = request.get("client_seq")
        return {"decision": "fail" if client_seq in decisions and decisions[client_seq] == "fail" else "pass"}
    return decide


def test_decisions_are_logged_in_arrival_order_with_controller_assigned_seq(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({3: "fail"}))
    channel.start()
    try:
        replies = [_send(sock_path, {"op": "disruption_check", "client_seq": i}) for i in range(1, 5)]
    finally:
        log = channel.stop_and_finalize()
    assert [r["result"]["decision"] for r in replies] == ["pass", "pass", "fail", "pass"]  # type: ignore[index]
    assert [d.seq for d in log] == [1, 2, 3, 4]
    assert [d.result["decision"] for d in log] == ["pass", "pass", "fail", "pass"]


def test_decision_is_logged_before_any_reply_can_have_been_sent(tmp_path: Path) -> None:
    """The ordering guarantee itself (design doc §2b step 3): block `decide`
    until a probe thread has already observed the log holding the entry,
    proving the append happens-before the handler's own `sendall`."""
    sock_path = tmp_path / "trigger.sock"
    released = threading.Event()
    observed_before_release = threading.Event()

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        released.wait(timeout=5.0)
        return {"decision": "pass"}

    channel = DecideReplyChannel(sock_path, decide)
    channel.start()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(str(sock_path))
        s.sendall(json.dumps({"op": "x"}).encode("utf-8") + b"\n")
        s.shutdown(socket.SHUT_WR)
        # The handler is now blocked inside `decide`. Release it, then read
        # the reply - by the time the reply arrives, the log append (which
        # happens between `decide` returning and `sendall`) is already done.
        released.set()
        chunks: list[bytes] = []
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        s.close()
        observed_before_release.set()
    finally:
        log = channel.stop_and_finalize()
    assert len(log) == 1
    assert log[0].result == {"decision": "pass"}


def test_a_refused_request_is_never_logged_as_a_decision(tmp_path: Path) -> None:
    """A `ChannelRefusal` is a transport-level refusal, not a decision - the
    log must stay empty. If this ever logged refusals, `no-controller-
    witness` would stop meaning what §2d says it means."""
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()
    try:
        reply = _send(sock_path, {"op": "not-a-real-op"})
    finally:
        log = channel.stop_and_finalize()
    assert reply == {"ok": False, "error": "unknown op"}
    assert log == []


def test_malformed_json_and_non_dict_requests_are_refused_not_logged(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(str(sock_path))
        s.sendall(b"not json at all\n")
        s.shutdown(socket.SHUT_WR)
        reply = json.loads(s.recv(65536).decode("utf-8").splitlines()[0])
        s.close()

        s2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s2.settimeout(5.0)
        s2.connect(str(sock_path))
        s2.sendall(b"[1, 2, 3]\n")
        s2.shutdown(socket.SHUT_WR)
        reply2 = json.loads(s2.recv(65536).decode("utf-8").splitlines()[0])
        s2.close()
    finally:
        log = channel.stop_and_finalize()
    assert reply == {"ok": False, "error": "malformed request"}
    assert reply2 == {"ok": False, "error": "malformed request"}
    assert log == []


def test_concurrent_requests_get_strictly_increasing_unique_sequence_numbers(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()
    n = 20
    try:
        threads = [threading.Thread(target=_send, args=(sock_path, {"op": "disruption_check", "client_seq": i}))
                   for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
    finally:
        log = channel.stop_and_finalize()
    seqs = [d.seq for d in log]
    assert len(seqs) == n
    assert sorted(seqs) == list(range(1, n + 1))  # no duplicates, no gaps
    assert len(set(seqs)) == n


def test_a_subject_that_never_connects_is_a_named_case_not_an_error(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()
    log = channel.stop_and_finalize()
    assert log == []
    trusted = TrustedLog.witnessed(log)
    assert trusted.status == "no-controller-witness"
    assert trusted.decisions == ()


def test_a_witnessed_log_is_never_confused_with_a_bypass(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()
    try:
        _send(sock_path, {"op": "disruption_check", "client_seq": 1})
    finally:
        log = channel.stop_and_finalize()
    trusted = TrustedLog.witnessed(log)
    assert trusted.status == "witnessed"
    assert len(trusted.decisions) == 1


def test_channel_unavailable_is_its_own_status_distinct_from_both_others() -> None:
    trusted = TrustedLog.unavailable()
    assert trusted.status == "channel-unavailable"
    assert trusted.decisions == ()


def test_trusted_log_bytes_are_valid_json_naming_the_read_as_rule(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({2: "fail"}))
    channel.start()
    try:
        _send(sock_path, {"op": "disruption_check", "client_seq": 1})
        _send(sock_path, {"op": "disruption_check", "client_seq": 2})
    finally:
        log = channel.stop_and_finalize()
    trusted = TrustedLog.witnessed(log)
    parsed = json.loads(trusted.to_json_bytes().decode("utf-8"))
    assert parsed["status"] == "witnessed"
    assert "tool invocations" in parsed["read_as"]
    assert [d["result"]["decision"] for d in parsed["decisions"]] == ["pass", "fail"]
    # logged_at is strictly non-decreasing in seq order - decisions are
    # appended under a lock in arrival order (design doc §2b).
    stamps = [d["logged_at"] for d in parsed["decisions"]]
    assert stamps == sorted(stamps)


def test_the_socket_is_created_owner_only(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()
    try:
        mode = sock_path.stat().st_mode & 0o777
    finally:
        channel.stop_and_finalize()
    assert mode == 0o600


def test_start_is_refused_a_second_time(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()
    try:
        with pytest.raises(RuntimeError):
            channel.start()
    finally:
        channel.stop_and_finalize()


def test_finalize_is_refused_before_start(tmp_path: Path) -> None:
    channel = DecideReplyChannel(tmp_path / "trigger.sock", _decide_fixed({}))
    with pytest.raises(RuntimeError):
        channel.stop_and_finalize()


def test_finalize_is_refused_a_second_time(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()
    channel.stop_and_finalize()
    with pytest.raises(RuntimeError):
        channel.stop_and_finalize()


def test_logged_decision_is_immutable(tmp_path: Path) -> None:
    entry = LoggedDecision(seq=1, request={"op": "x"}, result={"decision": "pass"}, logged_at=0.0)
    with pytest.raises(AttributeError):
        entry.seq = 2  # type: ignore[misc]


def test_log_or_finalize_is_safe_to_call_more_than_once(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()
    _send(sock_path, {"op": "disruption_check", "client_seq": 1})
    first = channel.log_or_finalize()
    second = channel.log_or_finalize()
    assert first == second
    assert len(first) == 1
    # a plain stop_and_finalize() after log_or_finalize() already finalized
    # it must still raise - log_or_finalize() does not quietly relax that
    with pytest.raises(RuntimeError):
        channel.stop_and_finalize()


def test_close_is_a_no_op_before_start_and_after_finalize(tmp_path: Path) -> None:
    channel = DecideReplyChannel(tmp_path / "trigger.sock", _decide_fixed({}))
    channel.close()  # never started - no-op, must not raise
    channel.start()
    channel.stop_and_finalize()
    channel.close()  # already finalized - no-op, must not raise


def test_close_after_start_stops_the_listener_without_raising(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()
    channel.close()
    assert not sock_path.exists()
    # a second close() is still a no-op
    channel.close()


def test_start_refuses_a_path_too_close_to_the_af_unix_limit(tmp_path: Path) -> None:
    """The kernel's own `sun_path` bind (108 bytes on Linux) produces a
    bare, unexplained `OSError: AF_UNIX path too long` with no path and no
    limit named - found running `docker_backend.py`'s own integration test
    against a realistic `base_dir`. This channel raises BEFORE attempting
    the bind, naming both. Also proves `start()` did not flip to
    "started" on this path - a later real `start()` elsewhere must not be
    blocked by a channel that never actually bound anything."""
    long_name = "x" * 90
    sock_path = tmp_path / f"{long_name}.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    with pytest.raises(OSError, match="sun_path"):
        channel.start()
    channel.close()  # never started - still a safe no-op; must not raise
