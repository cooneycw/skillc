"""Tests for the controller-owned decide-and-reply channel (#183).

Exercised directly over real `AF_UNIX` sockets - this module owns no Docker
or managed-backend plumbing of its own (that is `docker_backend.py`'s
`trigger_socket_host_path` parameter, covered in `test_docker_backend.py`),
so there is nothing here a fake CLI would add.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import threading
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

from skillc import decide_reply_channel as d
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


def test_sequential_decisions_get_increasing_controller_assigned_seq_numbers(tmp_path: Path) -> None:
    """Each call here fully round-trips before the next starts, so
    arrival order and completion order coincide - this does not test
    concurrent requests at all (see `test_concurrent_requests_get_
    strictly_increasing_unique_sequence_numbers` for that, and the module
    docstring for why completion order, not arrival order, is the only
    claim made about concurrent ones)."""
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


def test_sequence_numbers_reflect_completion_order_not_arrival_order(tmp_path: Path) -> None:
    """Pins the actual, corrected claim (counter-model review finding,
    msg 4685 item 7): a request that ARRIVES first but whose `decide`
    call takes longer is numbered AFTER one that arrives second but
    returns first. `decide` runs outside the log's lock, so the only
    ordering this module can honestly promise is completion order."""
    sock_path = tmp_path / "trigger.sock"
    first_arrived = threading.Event()
    release_first = threading.Event()

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        if request.get("client_seq") == 1:
            first_arrived.set()
            release_first.wait(timeout=5.0)  # arrives first, completes LAST
        return {"decision": "pass"}

    channel = DecideReplyChannel(sock_path, decide)
    channel.start()
    try:
        first = threading.Thread(target=_send, args=(sock_path, {"op": "disruption_check", "client_seq": 1}))
        first.start()
        first_arrived.wait(timeout=5.0)
        second = threading.Thread(target=_send, args=(sock_path, {"op": "disruption_check", "client_seq": 2}))
        second.start()
        second.join(timeout=5.0)  # arrives second, completes FIRST
        release_first.set()
        first.join(timeout=5.0)
    finally:
        log = channel.stop_and_finalize()
    by_client_seq = {entry.request["client_seq"]: entry.seq for entry in log}
    assert by_client_seq[2] < by_client_seq[1]  # second to arrive, first to complete


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
    # appended under a lock in COMPLETION order, which these two
    # sequential (not concurrent) calls make the same as arrival order.
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


# ---------------------------------------------------------- socket access control


def test_a_stale_orphan_socket_is_cleared_and_reused(tmp_path: Path) -> None:
    """A socket file with nothing listening on it (a prior attempt's
    listener that exited without unlinking - `stop_and_finalize()` unlinks
    on a clean exit, but a killed process cannot) is a stale orphan, safe
    to clear and rebind."""
    sock_path = tmp_path / "trigger.sock"
    orphan = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    orphan.bind(str(sock_path))
    orphan.close()  # leaves the inode behind; nothing is listening
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel.start()  # must not raise
    try:
        reply = _send(sock_path, {"op": "disruption_check", "client_seq": 1})
    finally:
        channel.stop_and_finalize()
    assert reply == {"ok": True, "result": {"decision": "pass"}}


def test_a_live_listener_at_the_same_path_is_refused(tmp_path: Path) -> None:
    """Two attempts racing for the same hashed path: REFUSED, never
    silently shared - decision 4 of design doc §2f. The first channel is
    left undisturbed; only the second `start()` call fails."""
    sock_path = tmp_path / "trigger.sock"
    first = DecideReplyChannel(sock_path, _decide_fixed({}))
    first.start()
    try:
        second = DecideReplyChannel(sock_path, _decide_fixed({}))
        with pytest.raises(OSError, match="already listening"):
            second.start()
        # the first channel still works - refusing the second must not
        # have torn down or stolen the first's socket
        reply = _send(sock_path, {"op": "disruption_check", "client_seq": 1})
        assert reply == {"ok": True, "result": {"decision": "pass"}}
    finally:
        first.stop_and_finalize()


def test_a_non_socket_at_the_path_is_refused_not_replaced(tmp_path: Path) -> None:
    """This channel creates nothing but sockets at its own path. A regular
    file there is refused, never silently deleted and replaced - it is
    either a different caller's mistake or an adversarial pre-creation,
    and this channel does not guess which."""
    sock_path = tmp_path / "trigger.sock"
    sock_path.write_text("not a socket")
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    with pytest.raises(OSError, match="non-socket"):
        channel.start()
    assert sock_path.read_text() == "not a socket"  # untouched
    channel.close()


def test_custom_socket_mode_is_honored(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}), socket_mode=0o666)
    channel.start()
    try:
        mode = sock_path.stat().st_mode & 0o777
    finally:
        channel.stop_and_finalize()
    assert mode == 0o666


# ------------------------------------------------- in-flight handler draining


def test_stop_and_finalize_waits_for_an_in_flight_handler_before_returning(tmp_path: Path) -> None:
    """Counter-model review finding (msg 4685 item 3): `daemon_threads =
    True` means `server_close()` alone does not wait for a handler still
    inside `decide()`. Without the drain, a late append could land AFTER
    this call already returned a "finalized" log. Here `decide()` blocks
    briefly - well inside the default drain timeout - so the correct
    behaviour is to wait and return the completed entry, never a short
    snapshot missing it."""
    sock_path = tmp_path / "trigger.sock"
    released = threading.Event()

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        released.wait(timeout=5.0)
        return {"decision": "pass"}

    channel = DecideReplyChannel(sock_path, decide)
    channel.start()
    client = threading.Thread(target=_send, args=(sock_path, {"op": "disruption_check", "client_seq": 1}))
    client.start()
    time.sleep(0.05)  # let the handler thread reach decide() and block there
    released.set()  # releases shortly after finalize() starts draining, below
    log = channel.stop_and_finalize()
    client.join(timeout=5.0)
    assert len(log) == 1
    assert log[0].result == {"decision": "pass"}


def test_stop_and_finalize_raises_if_a_handler_outlives_the_drain_timeout(tmp_path: Path) -> None:
    """The other half of the same guarantee: if a handler is STILL running
    past `handler_drain_timeout`, `stop_and_finalize()` must raise rather
    than silently return a log that might still grow - a short snapshot
    read as complete is worse than an explicit failure."""
    sock_path = tmp_path / "trigger.sock"
    stuck = threading.Event()

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        stuck.wait(timeout=5.0)  # never set - simulates a wedged decide()
        return {"decision": "pass"}

    channel = DecideReplyChannel(sock_path, decide, handler_drain_timeout=0.2)
    channel.start()
    client = threading.Thread(target=_send, args=(sock_path, {"op": "disruption_check", "client_seq": 1}))
    client.start()
    time.sleep(0.05)
    try:
        with pytest.raises(RuntimeError, match="handler"):
            channel.stop_and_finalize()
    finally:
        stuck.set()  # unblock the handler so the test process doesn't leak a thread
        client.join(timeout=5.0)


# ------------------------------------------------------------ resource bounds


def test_an_oversized_request_is_refused_without_a_reply(tmp_path: Path) -> None:
    """Counter-model review finding (msg 4685 item 3): an unterminated
    line used to be buffered without any size cap - a subject streaming
    an unbounded line could grow this process's own memory without
    limit. A connection over `max_request_bytes` before any newline is
    simply closed, never logged as a decision."""
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}), max_request_bytes=1024)
    channel.start()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(str(sock_path))
        s.sendall(b"x" * 4096)  # no newline - would otherwise buffer forever
        data = s.recv(65536)
        s.close()
    finally:
        log = channel.stop_and_finalize()
    assert data == b""  # closed without a reply
    assert log == []


def test_connections_past_max_concurrent_handlers_are_refused(tmp_path: Path) -> None:
    """A subject opening more connections than declared capacity is
    refused outright on the excess ones - never queued behind the
    in-flight ones, and never allowed to spawn unbounded controller-side
    threads. The admitted connection is unaffected."""
    sock_path = tmp_path / "trigger.sock"
    released = threading.Event()

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        released.wait(timeout=5.0)
        return {"decision": "pass"}

    channel = DecideReplyChannel(sock_path, decide, max_concurrent_handlers=1)
    channel.start()
    try:
        first = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        first.settimeout(5.0)
        first.connect(str(sock_path))
        first.sendall(json.dumps({"op": "disruption_check", "client_seq": 1}).encode("utf-8") + b"\n")
        time.sleep(0.05)  # let the first handler be admitted and block in decide()

        second_data = b"\x00"  # sentinel - overwritten below if recv ever returns
        second = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        second.settimeout(1.0)
        second.connect(str(sock_path))
        second.sendall(json.dumps({"op": "disruption_check", "client_seq": 2}).encode("utf-8") + b"\n")
        try:
            second_data = second.recv(65536)
        except TimeoutError:
            second_data = b""  # refused by a hang this bound prevents
        except (ConnectionResetError, OSError):
            # The over-capacity handler returns without reading the bytes
            # already sent - closing a socket with unread buffered data
            # produces an abrupt reset on the peer, same as a plain EOF
            # for this test's purposes: no reply was ever sent.
            second_data = b""
        second.close()

        released.set()
        first_data = first.recv(65536)
        first.close()
    finally:
        log = channel.stop_and_finalize()
    assert second_data == b""  # the second connection got no reply
    assert json.loads(first_data.decode("utf-8").splitlines()[0]) == {"ok": True, "result": {"decision": "pass"}}
    assert len(log) == 1  # only the admitted connection's decision is logged


def test_an_idle_connection_is_closed_after_the_request_timeout(tmp_path: Path) -> None:
    """A connection that sends nothing at all must not hang its handler
    forever - `max_concurrent_handlers` could otherwise be exhausted by
    connections that never send a byte."""
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed({}), request_timeout=0.2)
    channel.start()
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(str(sock_path))
        data = s.recv(65536)  # blocks until the handler's own read deadline closes it
        s.close()
    finally:
        log = channel.stop_and_finalize()  # must not itself block on the idle handler
    assert data == b""
    assert log == []


def test_start_refuses_while_another_channel_holds_the_path_lock(tmp_path: Path) -> None:
    """Counter-model review finding (msg 4685 item 3): a bare probe-then-
    unlink-then-bind sequence has a real window between another channel's
    `bind()` and its `listen()` where `connect()` fails with the SAME
    `ConnectionRefusedError` a genuine dead orphan produces - a probe
    racing that window would misread a mid-start channel as stale and
    unlink its socket out from under it. Reproducing the exact race
    deterministically is impractical; this test instead holds the
    serializing lock directly (as a second channel's `start()` would, for
    the whole decide-then-act section) and confirms a racing `start()` is
    refused outright rather than guessing."""
    sock_path = tmp_path / "trigger.sock"
    lock_path = sock_path.with_name(sock_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held = open(lock_path, "wb")  # noqa: SIM115 - held deliberately across the assertion below
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        channel = DecideReplyChannel(sock_path, _decide_fixed({}))
        with pytest.raises(OSError, match="already working on this exact path"):
            channel.start()
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        held.close()
    # released: a later start() against the same path now succeeds normally
    channel2 = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel2.start()
    channel2.stop_and_finalize()


def test_a_chmod_failure_after_a_successful_bind_still_closes_the_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counter-model review finding (msg 4685 item 5): `_Server.__init__`
    (stdlib `TCPServer.__init__`) already self-closes on a bind/listen
    failure, but `os.chmod()` runs AFTER that succeeds - a chmod failure
    used to leave the already-bound, already-listening socket open with
    nothing EXPLICITLY tracking it.

    This test does not by itself distinguish the fix from its absence:
    with no other reference to the orphaned `_Server`, CPython's own
    refcounting GC closes the underlying socket as soon as `start()`'s
    stack frame unwinds, in this single-threaded case, whether or not the
    code explicitly calls `server_close()`. Checked directly - removing
    the explicit close left this test green. The explicit close remains
    correct regardless (resource cleanup should not depend on `__del__`
    timing, which the language does not guarantee), and this test still
    proves the observable END STATE a caller actually depends on: a
    chmod failure must not leave the path looking like a live listener to
    whatever starts the next channel there."""
    sock_path = tmp_path / "trigger.sock"
    real_chmod = os.chmod

    def failing_chmod(path: str | Path, mode: int) -> None:
        if path == str(sock_path) or path == sock_path:
            raise OSError("simulated chmod failure")
        real_chmod(path, mode)

    monkeypatch.setattr(d.os, "chmod", failing_chmod)
    channel = DecideReplyChannel(sock_path, _decide_fixed({}))
    with pytest.raises(OSError, match="simulated chmod failure"):
        channel.start()
    monkeypatch.undo()
    channel2 = DecideReplyChannel(sock_path, _decide_fixed({}))
    channel2.start()  # must not raise "already listening" - the first was closed
    channel2.stop_and_finalize()


# -------------------------------------------------------- log entry immutability


def test_a_reused_mutable_result_dict_does_not_rewrite_an_earlier_entry(tmp_path: Path) -> None:
    """Counter-model review finding (msg 4685 item 6): a `decide` function
    that returns the SAME dict object on every call (mutating it between
    calls, as a careless or adversarial implementation might) must not be
    able to rewrite an already-logged decision through that shared
    reference."""
    sock_path = tmp_path / "trigger.sock"
    shared: dict[str, object] = {"decision": "pass"}

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        shared["decision"] = request.get("client_seq") == 2 and "fail" or "pass"
        return shared

    channel = DecideReplyChannel(sock_path, decide)
    channel.start()
    try:
        _send(sock_path, {"op": "disruption_check", "client_seq": 1})
        _send(sock_path, {"op": "disruption_check", "client_seq": 2})
    finally:
        log = channel.stop_and_finalize()
    assert log[0].result == {"decision": "pass"}  # unchanged by the second call's mutation
    assert log[1].result == {"decision": "fail"}


def test_mutating_the_original_nested_object_after_logging_does_not_rewrite_the_record(tmp_path: Path) -> None:
    """A shallow `dict(x)` copy at logging time would already protect the
    top level - the real test is a NESTED mutable object the caller's
    `decide` still holds a reference to after returning it, which only a
    DEEP copy at logging time protects the stored record against."""
    sock_path = tmp_path / "trigger.sock"
    original_detail: dict[str, object] = {"nested": [1, 2, 3]}

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        return {"decision": "pass", "detail": original_detail}

    channel = DecideReplyChannel(sock_path, decide)
    channel.start()
    try:
        _send(sock_path, {"op": "disruption_check", "client_seq": 1})
    finally:
        log = channel.stop_and_finalize()
    nested = original_detail["nested"]
    assert isinstance(nested, list)
    nested.append(999)  # mutate the object `decide` returned, AFTER it was logged
    stored_detail = log[0].result["detail"]
    assert isinstance(stored_detail, dict)
    assert stored_detail["nested"] == [1, 2, 3]  # the stored entry is unaffected
