"""`docker/fixture-service/flow-auto-gate-shim.py` (#434 PR 2b): the flow-auto
variant of the flow-check gate shim. Its one prescribed call forwards the
controller's real result byte for byte; every other argv, and every channel
failure, exits 125 without reaching or trusting the channel."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

SHIM = Path(__file__).resolve().parent.parent / "docker" / "fixture-service" / "flow-auto-gate-shim.py"


class _Controller:
    def __init__(self, path: Path, reply: dict[str, Any]) -> None:
        self.requests: list[dict[str, Any]] = []
        self.reply = reply
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(2)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = b""
                while chunk := conn.recv(65536):
                    data += chunk
                self.requests.append(json.loads(data))
                conn.sendall(json.dumps(self.reply).encode() + b"\n")


@pytest.fixture
def controller(tmp_path: Path) -> Iterator[tuple[_Controller, Path]]:
    sock = tmp_path / "trigger.sock"
    ctl = _Controller(sock, {"ok": True, "result": {"exit_code": 3, "stdout": "FLOW_FINISH_GATE: warn\n",
                                                    "stderr": "zero tests\n"}})
    yield ctl, sock
    ctl.server.close()


def _run(args: list[str], sock: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SHIM), *args], env={"SKILLC_TRIGGER_SOCKET": str(sock)},
                          cwd=cwd, capture_output=True, text=True, timeout=30, check=False)


def test_the_prescribed_bare_call_forwards_the_real_result(controller: tuple[_Controller, Path],
                                                          tmp_path: Path) -> None:
    ctl, sock = controller
    proc = _run([], sock, tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (3, "FLOW_FINISH_GATE: warn\n", "zero tests\n")
    assert ctl.requests == [{"op": "run_gate", "gate": "flow-auto-finish", "cwd": str(tmp_path)}]


@pytest.mark.parametrize("args", [["--plan", "check", "--evidence", "flow-check"], ["--check-summary"], ["-h"]])
def test_any_other_argv_is_refused_before_the_channel(controller: tuple[_Controller, Path], tmp_path: Path,
                                                      args: list[str]) -> None:
    ctl, sock = controller
    proc = _run(args, sock, tmp_path)
    assert proc.returncode == 125 and proc.stdout == ""
    # Never asked to RUN: the only request is the refusal's own report, which
    # the controller counts (#279, orchestrator).
    assert ctl.requests == [{"op": "gate_refused", "argv": args, "cwd": str(tmp_path)}]


def test_an_unreachable_channel_is_125(tmp_path: Path) -> None:
    proc = _run([], tmp_path / "no-such.sock", tmp_path)
    assert proc.returncode == 125 and "channel error" in proc.stderr


@pytest.mark.parametrize("reply", [{"ok": False, "error": "refused"},
                                   {"ok": True, "result": {"exit_code": None, "reason": "launch-failed"}}])
def test_a_refusal_or_a_result_with_no_real_exit_is_125(tmp_path: Path, reply: dict[str, Any]) -> None:
    sock = tmp_path / "trigger.sock"
    ctl = _Controller(sock, reply)
    try:
        proc = _run([], sock, tmp_path)
    finally:
        ctl.server.close()
    assert proc.returncode == 125 and proc.stdout == ""


def test_red_279_a_flow_check_call_through_the_bundled_flow_check_copy_is_125_and_reported(
        controller: tuple[_Controller, Path], tmp_path: Path) -> None:
    """The 125 parity deviation (orchestrator, #279): the flow-auto shim placed
    over flow-check's bundled gate refuses flow-check's own call - and REPORTS
    it, naming its copy, so it is counted rather than silent."""
    from skillc import agent_trial as at
    shim = tmp_path / "flow-finish-gate.sh"
    shim.write_bytes(at.bundled_gate_shim(SHIM.read_bytes(), "bundled:flow-check"))
    ctl, sock = controller
    args = ["--plan", "check", "--evidence", "flow-check"]
    proc = subprocess.run([sys.executable, str(shim), *args], env={"SKILLC_TRIGGER_SOCKET": str(sock)}, cwd=tmp_path,
                          capture_output=True, text=True, timeout=30, check=False)
    assert proc.returncode == 125
    assert ctl.requests == [{"op": "gate_refused", "argv": args, "cwd": str(tmp_path), "via": "bundled:flow-check"}]


def test_a_refusal_with_no_channel_is_still_125(tmp_path: Path) -> None:
    proc = _run(["--check-summary"], tmp_path / "no-such.sock", tmp_path)
    assert proc.returncode == 125
