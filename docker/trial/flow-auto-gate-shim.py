#!/usr/bin/env python3
"""Witnesses `/flow:auto` Step 6's BARE `flow-finish-gate.sh` invocation (#287 auto6).

Installed by a profile that declares `gate_witness: flow-finish` (the
`cpp-codex-flow-auto-86641e8-step6` subject) at the EXACT path flow-auto's
`reference.md` (CPP 86641e8, :1207-1217) tells the agent to invoke:
`~/.claude/scripts/flow-finish-gate.sh`, BARE. It replaces the pinned helper
there as a declared, harness-owned synthetic dependency, exactly as
`flow-check-gate-shim.py` does for flow-check's two calls. That shim and its
two-call map are UNCHANGED; this is a separate file with its own closed map.

THE REAL RUNNER RUNS. This script never formats a verdict: it forwards the
call to the controller over #183's decide-and-reply channel as one
`run_gate` request naming the PRE-DECLARED gate "flow-finish"; the
controller runs the REAL `flow-finish-gate.sh` (plan `finish`) inside the same
live container and this script writes back its real stdout, stderr and exit
code byte for byte.

ONLY THE BARE INVOCATION IS EVER WITNESSED. Any argv at all is refused (exit
125) before the channel is reached: Step 6 prescribes the bare call and
nothing else, so an argument is a bug or a bypass, never input to guess at.
Exit 125 on any channel failure as well, distinct from every exit the real
script uses (0, 1, 2, 3, 4, 127). CWD is forwarded (confined by the
controller), argv is not.

The channel code below is the flow-check shim's, unchanged.
"""
from __future__ import annotations

import json
import os
import socket
import sys

#: Must resolve the same way `skillc.docker_backend.TRIGGER_SOCKET_PATH`
#: does - overridable only for testing this script outside a real
#: container; a real trial container never sets this.
TRIGGER_SOCKET_PATH = os.environ.get("SKILLC_TRIGGER_SOCKET", "/run/skillc/trigger.sock")
_REQUEST_TIMEOUT = 300.0  # a real quality-gate run can take minutes

#: The CLOSED map from a prescribed argv shape to its declared gate name -
#: `reference.md`'s own Step 2 and Step 5, and nothing else. Extending
#: this requires extending `reference.md`'s own prescribed invocations
#: first; it is never inferred from whatever the subject happens to pass.
_DECLARED_INVOCATIONS: dict[tuple[str, ...], str] = {
    (): "flow-finish",
}

#: Exit codes `flow-finish-gate.sh` itself legitimately uses (#581/#1366's
#: own documented vocabulary) - this script's own infrastructure-failure
#: code must never collide with any of them.
EXIT_CHANNEL_FAILURE = 125


class _ChannelError(Exception):
    """Any failure to reach the channel, or a reply this script cannot
    recognize - never treated as a gate outcome of any kind."""


def _ask(gate: str) -> dict[str, object]:
    """One-shot connect/send/receive/close, the exact framing
    `decide_reply_channel.py`'s own module docstring specifies. Raises
    `_ChannelError` for anything short of a well-formed, accepted reply -
    never returns a guessed result."""
    request = json.dumps({"op": "run_gate", "gate": gate, "cwd": os.getcwd()}) + "\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(_REQUEST_TIMEOUT)
            sock.connect(TRIGGER_SOCKET_PATH)
            sock.sendall(request.encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    except OSError as exc:
        raise _ChannelError(f"could not reach the channel: {exc}") from exc
    line = b"".join(chunks).decode("utf-8", errors="replace").strip()
    try:
        reply = json.loads(line)
    except json.JSONDecodeError as exc:
        raise _ChannelError(f"reply is not JSON: {exc}") from exc
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        raise _ChannelError(f"the channel refused this request: {reply!r}")
    result = reply.get("result")
    if not isinstance(result, dict):
        raise _ChannelError(f"reply's 'result' is not a mapping: {reply!r}")
    return result


def main(argv: list[str]) -> int:
    gate = _DECLARED_INVOCATIONS.get(tuple(argv[1:]))
    if gate is None:
        print(
            "flow-auto-gate-shim: only the bare flow-finish-gate.sh call that /flow:auto Step 6 "
            "prescribes is witnessed - refusing rather than guessing", file=sys.stderr,
        )
        return EXIT_CHANNEL_FAILURE
    try:
        result = _ask(gate)
    except _ChannelError as exc:
        print(f"flow-auto-gate-shim: channel error: {exc}", file=sys.stderr)
        return EXIT_CHANNEL_FAILURE
    exit_code = result.get("exit_code")
    if not isinstance(exit_code, int):
        # The gate never genuinely exited (a refused/never-started attempt,
        # or `reason="unsupported"`) - never forwarded as if it were a real
        # exit code, which could otherwise accidentally collide with one of
        # the real script's own documented values.
        print(
            f"flow-auto-gate-shim: the controller did not report a real exit code "
            f"(reason={result.get('reason')!r}) - treating as a channel failure", file=sys.stderr,
        )
        return EXIT_CHANNEL_FAILURE
    stdout = result.get("stdout")
    if isinstance(stdout, str):
        sys.stdout.write(stdout)
    stderr = result.get("stderr")
    if isinstance(stderr, str):
        sys.stderr.write(stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
