#!/usr/bin/python3 -I
"""The project-gate `make` shim (#508). Installed root-owned as
`/opt/skillc-harness/make-shim/make`, a directory prepended to the AGENT's PATH
only; the real make stays at `/usr/bin/make`, and controller execs never see
this directory.

Every invocation is first offered to the controller over #183's
decide-and-reply channel as one `run_gate` request for the gate
`project-check`, carrying the argv as `make_args`. The CONTROLLER decides
whether it is a gate invocation (`skillc.project_gate.ProjectGate.resolve`):

  - if it is, the controller runs each declared stage itself and replies with
    make's rendered stdout, stderr and exit status, which this script writes
    back unchanged;
  - if it is not (other targets, flags, variables), or the channel refuses or
    fails, or the controller reports no real exit status, this script runs the
    REAL make with the same argv, so the agent's workflow is unchanged
    (#508 ruling 1), then logs the invocation with `make_passthrough`. That log
    is SUBJECT-REPORTED and never evidence: nothing grades it.

Lives outside `docker/trial/` on purpose: every file there moves the pinned
flow-check runtime's `build_context_sha256`.

Deliberately stdlib-only.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

TRIGGER_SOCKET_PATH = os.environ.get("SKILLC_TRIGGER_SOCKET", "/run/skillc/trigger.sock")
REAL_MAKE = "/usr/bin/make"
GATE = "project-check"
_REQUEST_TIMEOUT = 600.0  # a real quality-gate run can take minutes
_LOG_TIMEOUT = 5.0


class _ChannelError(Exception):
    """Any failure to reach the channel, or a reply this script cannot read."""


def _ask(request: dict[str, object], timeout: float) -> dict[str, object]:
    line = json.dumps(request) + "\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(TRIGGER_SOCKET_PATH)
            sock.sendall(line.encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    except OSError as exc:
        raise _ChannelError(f"could not reach the channel: {exc}") from exc
    try:
        reply = json.loads(b"".join(chunks).decode("utf-8", errors="replace").strip())
    except json.JSONDecodeError as exc:
        raise _ChannelError(f"reply is not JSON: {exc}") from exc
    if not isinstance(reply, dict) or reply.get("ok") is not True or not isinstance(reply.get("result"), dict):
        raise _ChannelError("the channel refused this request")
    return reply["result"]


def _passthrough(args: list[str], why: str) -> int:
    try:
        code = subprocess.call([REAL_MAKE, *args])
    except OSError as exc:
        print(f"make: {exc}", file=sys.stderr)
        code = 127
    try:
        _ask({"op": "make_passthrough", "argv": args, "cwd": os.getcwd(), "exit_code": code, "why": why},
             _LOG_TIMEOUT)
    except _ChannelError:
        pass  # the log is subject-reported and never evidence; losing it changes nothing
    return code


def main(argv: list[str]) -> int:
    args = argv[1:]
    try:
        result = _ask({"op": "run_gate", "gate": GATE, "cwd": os.getcwd(), "make_args": args}, _REQUEST_TIMEOUT)
    except _ChannelError:
        return _passthrough(args, "channel-unavailable-or-refused")
    if result.get("passthrough") is True:
        return _passthrough(args, "not-a-gate-invocation")
    exit_code = result.get("exit_code")
    if result.get("accepted") is not True or not isinstance(exit_code, int):
        return _passthrough(args, "no-controller-exit-status")
    stdout, stderr = result.get("stdout"), result.get("stderr")
    if isinstance(stdout, str):
        sys.stdout.write(stdout)
        sys.stdout.flush()
    if isinstance(stderr, str):
        sys.stderr.write(stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
