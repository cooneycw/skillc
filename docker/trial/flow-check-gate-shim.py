#!/usr/bin/env python3
"""Witnesses the subject's own `flow-finish-gate.sh` invocation (#332).

Installed by the `cpp-codex-flow-check-ea6dbfa` profile at the EXACT path
`reference.md` tells the agent to invoke (`~/.claude/scripts/flow-finish-
gate.sh`), replacing the real pinned helper there - `skillc profile
diagnose` still reports 0 problems; this is a declared, harness-owned
`synthetic` dependency (`replaces_pinned_digest` recorded), never part of
the subject's own surface, and `reference.md`'s text is unedited.

THE REAL RUNNER RUNS. This script never formats its own verdict and never
synthesises a `FLOW_FINISH_GATE:` line - it forwards the invocation to the
controller over #183's decide-and-reply channel as one `run_gate` request
naming a PRE-DECLARED gate (never the subject's own argv - the controller
owns what actually executes, exactly as `decide_reply_channel.py`'s own
module docstring requires: "the controller numbers requests, never the
subject"), the controller runs the REAL `flow-finish-gate.sh` inside the
SAME live attempt container via `exec_in_attempt()`, and this script
writes back the real stdout/stderr/exit code byte-for-byte. The agent's
own behaviour is therefore unchanged by this script's presence.

ONLY TWO INVOCATIONS ARE EVER WITNESSED, because `reference.md` prescribes
exactly two (Step 2 and Step 5) and nothing else:

    flow-finish-gate.sh --plan check --evidence flow-check   -> "flow-check-plan"
    flow-finish-gate.sh --check-summary                      -> "flow-check-summary"

Any OTHER argv is a bug or a bypass attempt, never a subject input to
guess at - refused immediately (exit 125), before the channel is even
reached. `reference.md`'s own documented fallbacks (exit 127 -> the
plugin-root or CPP-checkout copies) are a DIFFERENT path entirely - this
script is never installed there, so a subject that reaches one of those
instead bypasses this witness correctly and reads as `not-observed`
(#332's own acceptance item 2), never as a defect in this script.

EXIT 125 ON ANY CHANNEL FAILURE - never 0, and never 2 (the real script's
OWN "unknown argument: --evidence" exit per #581/#1366's text; colliding
with it would make the two failure modes indistinguishable to the agent
reading the exit code). 125 matches Docker's own convention for "the
launcher itself failed," distinct from anything the real script could
ever legitimately exit (0, 1, 2, 3, 4, 127).

CWD IS FORWARDED, ARGV IS NOT - the agent's own working tree is the one
thing the controller cannot pre-declare; everything else this script asks
for is one of exactly two fixed, controller-owned gate names. The
controller confines the forwarded `cwd` to the attempt's own workspace
root via a real in-container `realpath` before trusting it for anything
(`skillc/gate_witness.py`'s `_confine_requested_cwd`) - this script does
not need to, and does not, perform that check itself.

Deliberately stdlib-only, matching `skillc-disrupt-tool.py`/
`skillc-wrap.py`/`skillc-supervisor.py`.
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
    ("--plan", "check", "--evidence", "flow-check"): "flow-check-plan",
    ("--check-summary",): "flow-check-summary",
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
            "flow-check-gate-shim: this invocation does not match either prescribed "
            "flow-check gate call - refusing rather than guessing", file=sys.stderr,
        )
        return EXIT_CHANNEL_FAILURE
    try:
        result = _ask(gate)
    except _ChannelError as exc:
        print(f"flow-check-gate-shim: channel error: {exc}", file=sys.stderr)
        return EXIT_CHANNEL_FAILURE
    exit_code = result.get("exit_code")
    if not isinstance(exit_code, int):
        # The gate never genuinely exited (a refused/never-started attempt,
        # or `reason="unsupported"`) - never forwarded as if it were a real
        # exit code, which could otherwise accidentally collide with one of
        # the real script's own documented values.
        print(
            f"flow-check-gate-shim: the controller did not report a real exit code "
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
