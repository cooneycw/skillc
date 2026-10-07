"""Tests for `docker/trial/flow-check-gate-shim.py` (#332) - the subject-
side client witnessing the subject's own `flow-finish-gate.sh` invocation.

Driven as a REAL subprocess against a REAL `DecideReplyChannel`, same
discipline as `test_skillc_disrupt_tool.py` - never a hand-typed mock of
the wire protocol."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from skillc.decide_reply_channel import ChannelRefusal, DecideFn, DecideReplyChannel

SCRIPT = Path(__file__).resolve().parent.parent / "docker" / "trial" / "flow-check-gate-shim.py"

PLAN_ARGV = ["--plan", "check", "--evidence", "flow-check"]
SUMMARY_ARGV = ["--check-summary"]


def _decide_fixed(result: Mapping[str, object]) -> DecideFn:
    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        if request.get("op") != "run_gate":
            raise ChannelRefusal(f"unknown op {request.get('op')!r}")
        return dict(result)

    return decide


def _decide_refusing() -> DecideFn:
    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        raise ChannelRefusal("gate refused for this test")

    return decide


def _decide_capturing(sink: list[Mapping[str, object]], result: Mapping[str, object]) -> DecideFn:
    def decide(request: Mapping[str, object]) -> Mapping[str, object]:
        sink.append(request)
        return dict(result)

    return decide


def _run_shim(
    socket_path: Path | None, argv: list[str], *, cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin"}
    if socket_path is not None:
        env["SKILLC_TRIGGER_SOCKET"] = str(socket_path)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv], env=env, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=10, check=False,
    )


def _accepted(exit_code: int, stdout: str = "", stderr: str = "") -> dict[str, object]:
    return {"accepted": True, "exit_code": exit_code, "reason": "exited", "stdout": stdout, "stderr": stderr}


# -------------------------------------------------------- the forwarding path


@pytest.mark.parametrize("argv", [PLAN_ARGV, SUMMARY_ARGV])
def test_the_real_exit_code_stdout_and_stderr_are_forwarded_exactly(tmp_path: Path, argv: list[str]) -> None:
    """The shim's whole job: a pure pipe, never a reformatter. Both of
    `reference.md`'s own prescribed invocations are covered."""
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(
        sock_path, _decide_fixed(_accepted(3, stdout="gate output\n", stderr="gate warning\n")), "a1",
    )
    channel.start()
    try:
        result = _run_shim(sock_path, argv)
    finally:
        channel.stop_and_finalize()
    assert result.returncode == 3
    assert result.stdout == "gate output\n"
    assert result.stderr == "gate warning\n"


def test_cwd_is_forwarded_as_the_shims_own_working_directory(tmp_path: Path) -> None:
    """The ONE dynamic input: the controller cannot pre-declare the
    agent's own working tree, so the shim must report its own `os.getcwd()`
    - never a fixed or omitted value."""
    sock_path = tmp_path / "trigger.sock"
    requests: list[Mapping[str, object]] = []
    channel = DecideReplyChannel(sock_path, _decide_capturing(requests, _accepted(0)), "a1")
    channel.start()
    work_dir = tmp_path / "agent-cwd"
    work_dir.mkdir()
    try:
        result = _run_shim(sock_path, PLAN_ARGV, cwd=work_dir)
    finally:
        channel.stop_and_finalize()
    assert result.returncode == 0
    assert len(requests) == 1
    assert requests[0]["cwd"] == str(work_dir.resolve())
    assert requests[0]["gate"] == "flow-check-plan"


def test_the_summary_invocation_requests_the_other_declared_gate(tmp_path: Path) -> None:
    sock_path = tmp_path / "trigger.sock"
    requests: list[Mapping[str, object]] = []
    channel = DecideReplyChannel(sock_path, _decide_capturing(requests, _accepted(0)), "a1")
    channel.start()
    try:
        _run_shim(sock_path, SUMMARY_ARGV)
    finally:
        channel.stop_and_finalize()
    assert requests[0]["gate"] == "flow-check-summary"


# -------------------------------------------------------------- refusal paths


def test_an_unrecognized_argv_is_refused_before_the_channel_is_even_reached(tmp_path: Path) -> None:
    """Red case: a bypass attempt or a shim-side bug, never a subject input
    to guess at - no channel is running at all, proving the shim never even
    tries to connect for an argv outside the two declared shapes."""
    result = _run_shim(tmp_path / "no-such-socket.sock", ["--something-else"])
    assert result.returncode == 125
    assert "does not match" in result.stderr


def test_an_unreachable_channel_exits_125_never_0(tmp_path: Path) -> None:
    result = _run_shim(tmp_path / "no-such-socket.sock", PLAN_ARGV)
    assert result.returncode == 125
    assert "channel error" in result.stderr


def test_a_channel_refusal_exits_125_never_the_real_scripts_own_exit_2(tmp_path: Path) -> None:
    """125 is deliberately NOT 2 - flow-finish-gate.sh's own "unknown
    argument: --evidence" (a stale-helper signal per #581/#1366) already
    uses exit 2; colliding would make the two failure modes indistinguishable
    to the agent reading the exit code alone."""
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_refusing(), "a1")
    channel.start()
    try:
        result = _run_shim(sock_path, PLAN_ARGV)
    finally:
        channel.stop_and_finalize()
    assert result.returncode == 125
    assert result.returncode != 2


@pytest.mark.parametrize(
    "result",
    [
        {"accepted": True, "exit_code": None, "reason": "attempt-not-running", "stdout": "", "stderr": ""},
        {"accepted": True, "exit_code": None, "reason": "unsupported", "stdout": "", "stderr": ""},
    ],
)
def test_a_missing_real_exit_code_exits_125_never_a_guessed_value(tmp_path: Path, result: dict[str, object]) -> None:
    """A gate that never genuinely exited (refused before launch, or the
    backend declared the whole mechanism unsupported) must not be forwarded
    as if `None` meant some real exit code - exit 125, same as any other
    channel-side failure to produce a trustworthy result."""
    sock_path = tmp_path / "trigger.sock"
    channel = DecideReplyChannel(sock_path, _decide_fixed(result), "a1")
    channel.start()
    try:
        shim_result = _run_shim(sock_path, PLAN_ARGV)
    finally:
        channel.stop_and_finalize()
    assert shim_result.returncode == 125


def test_takes_no_other_argument_shapes_without_crashing(tmp_path: Path) -> None:
    """Defensive: an empty argv list is also simply "not a declared
    invocation" - refused the same way, never an unhandled exception."""
    result = _run_shim(tmp_path / "no-such-socket.sock", [])
    assert result.returncode == 125
