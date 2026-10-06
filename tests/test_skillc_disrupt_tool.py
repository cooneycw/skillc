"""Tests for `docker/trial/skillc-disrupt-tool.py` (issue #183 PR B2) - the
subject-side client for the decide-and-reply channel. Deferred from B1
(codex:code_review's red cases) since the script was committed there
unwired and untested; B2 wires it into the image and owns these.

Driven as a REAL subprocess against a REAL `DecideReplyChannel` (never a
hand-typed mock of the wire protocol) - these tests found a real bug before
anything else did: an earlier version of the script checked
`reply["allow"]` at the top level, but `_Handler._handle_admitted()` wraps
whatever `decide()` returns under a `"result"` key, so every real exchange
would have returned exit 2 regardless of the actual decision. Fixed before
these tests existed to prove it stays fixed.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Mapping
from pathlib import Path

import pytest

from skillc.decide_reply_channel import ChannelRefusal, DecideFn, DecideReplyChannel

SCRIPT = Path(__file__).resolve().parent.parent / "docker" / "trial" / "skillc-disrupt-tool.py"


def _decide_fixed(allow: bool) -> DecideFn:
    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        if request.get("op") != "tool-call":
            raise ChannelRefusal(f"unknown op {request.get('op')!r}")
        return {"allow": allow}

    return decide


def _decide_malformed() -> DecideFn:
    """A decide function whose own return value does not match the
    `{"allow": bool}` shape the proxy expects - exercises the proxy's own
    reply-shape validation, independent of the channel's wire framing."""

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        return {"allow": "yes"}  # a string, not a bool

    return decide


def _run_proxy(socket_path: Path) -> subprocess.CompletedProcess[str]:
    env = {"SKILLC_TRIGGER_SOCKET": str(socket_path), "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10, check=False,
    )


def test_exit_0_when_the_channel_allows(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed(True), "a1")
    channel.start()
    try:
        result = _run_proxy(sock_path)
    finally:
        channel.stop_and_finalize()
    assert result.returncode == 0
    assert result.stderr == ""


def test_exit_1_when_the_channel_refuses_the_tool_call(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed(False), "a1")
    channel.start()
    try:
        result = _run_proxy(sock_path)
    finally:
        channel.stop_and_finalize()
    assert result.returncode == 1
    assert "tool unavailable" in result.stderr


def test_exit_2_when_the_socket_is_unreachable(tmp_path: Path) -> None:
    # No channel listening at all - the proxy's own "infrastructure error"
    # bucket, never confused with either a real allow or a real refusal.
    result = _run_proxy(tmp_path / "nothing-here.sock")
    assert result.returncode == 2
    assert "channel error" in result.stderr


def test_exit_2_when_the_reply_does_not_match_the_expected_shape(tmp_path: Path) -> None:
    """THE RED CASE this test file exists for: proves the proxy reads
    `reply["result"]["allow"]`, not `reply["allow"]` - a decide() that
    returns a non-boolean `allow` surfaces as a shape error, which would
    also have caught the top-level-vs-nested bug this module's own
    docstring describes, had it existed when this test was written."""
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_malformed(), "a1")
    channel.start()
    try:
        result = _run_proxy(sock_path)
    finally:
        channel.stop_and_finalize()
    assert result.returncode == 2
    assert "not the expected" in result.stderr


def test_exit_2_when_the_channel_refuses_the_request_itself(tmp_path: Path) -> None:
    """Distinct from a `{"allow": false}` decision - a `ChannelRefusal`
    (wrong `op`, here deliberately triggered by a decide function that
    refuses everything) means the channel never decided at all, which
    must not be read as "the tool failed" (exit 1)."""
    sock_path = tmp_path / "trigger.sock"

    def refuse_everything(request: Mapping[str, object]) -> Mapping[str, object]:
        raise ChannelRefusal("refusing on purpose")

    channel = DecideReplyChannel(sock_path, refuse_everything, "a1")
    channel.start()
    try:
        result = _run_proxy(sock_path)
    finally:
        channel.stop_and_finalize()
    assert result.returncode == 2
    assert "refused" in result.stderr


def test_rejects_any_argument(tmp_path: Path) -> None:
    """THE RED CASE for the argument guard: decide_reply_channel.py's own
    principle is that the controller numbers requests, never the subject
    - so this script has nothing truthful to say via an argument, and
    must refuse one rather than silently ignoring it (e.g. a step number
    a future caller might mistakenly think it should pass)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "extra-argument"],
        env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 2
    assert "takes no arguments" in result.stderr


def test_the_request_carries_no_step_number_or_other_content(tmp_path: Path) -> None:
    """Direct proof of the "controller numbers, never the subject"
    principle: the request this script actually sends over the wire is
    exactly `{"op": "tool-call"}`, nothing else."""
    sock_path = tmp_path / "trigger.sock"
    seen: list[Mapping[str, object]] = []
    lock = threading.Lock()

    def recording_decide(request: Mapping[str, object]) -> Mapping[str, object]:
        with lock:
            seen.append(dict(request))
        return {"allow": True}

    channel = DecideReplyChannel(sock_path, recording_decide, "a1")
    channel.start()
    try:
        result = _run_proxy(sock_path)
    finally:
        channel.stop_and_finalize()
    assert result.returncode == 0
    assert seen == [{"op": "tool-call"}]


@pytest.mark.parametrize("call_count,expected_exits", [(1, [0]), (4, [0, 0, 0, 1])])
def test_exit_code_tracks_the_controllers_own_counter_not_a_step_argument(
    tmp_path: Path, call_count: int, expected_exits: list[int],
) -> None:
    """End-to-end proof that repeated, argument-free calls still produce
    the right sequence of decisions - the controller's own counter (not
    anything this script sends) is what determines each call's outcome."""
    sock_path = tmp_path / "trigger.sock"
    state = {"n": 0}
    lock = threading.Lock()

    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        with lock:
            state["n"] += 1
            return {"allow": state["n"] <= 3}

    channel = DecideReplyChannel(sock_path, decide, "a1")
    channel.start()
    try:
        exits = [_run_proxy(sock_path).returncode for _ in range(call_count)]
    finally:
        channel.stop_and_finalize()
    assert exits == expected_exits
