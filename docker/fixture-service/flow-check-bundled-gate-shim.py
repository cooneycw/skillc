#!/usr/bin/env python3
"""Witnesses a flow-check `flow-finish-gate.sh` call through a MIRRORED copy
of the gate (#529): the skill-bundled copy CPP #1408 makes every generated
Codex skill invoke, and the CPP checkout copy its exit-127 fallback names.

The flow-check variant of `flow-auto-gate-shim.py`, which it follows in
everything but its closed map. The controller places one copy of this shim
over each declared copy, with `_VIA` set to that copy's route
(`agent_trial.bundled_gate_shim`), after the real gate and its whole
`scripts/` directory are mirrored root-owned. It forwards the invocation over
#183's decide-and-reply channel as one `run_gate` request naming a
PRE-DECLARED gate and its `via`; the controller runs that copy's mirror, so
the real script's `BASH_SOURCE`-relative siblings are its own, and this
script writes back the real stdout, stderr and exit code.

TWO INVOCATIONS ARE WITNESSED, because flow-check's `reference.md`
prescribes exactly two (Step 2 and Step 5), re-read at CPP f857754d:

    flow-finish-gate.sh --plan check --evidence flow-check  -> "flow-check-plan"
    flow-finish-gate.sh --check-summary                     -> "flow-check-summary"

The same map as `docker/trial/flow-check-gate-shim.py` (#332), which stays
unchanged: every file there moves the pinned flow-check runtime's
`build_context_sha256`. Any other argv - including the documented pre-#1366
retry without `--evidence` - is refused with exit 125 before the channel is
reached, and the refusal is REPORTED and counted (#279). The call reaches
this script only through a path that names the copy: at CPP f857754d the
skill anchors it, `"${CPP_SKILL_DIR:-/dev/null}"/scripts/flow-finish-gate.sh`
(CPP #1546). With `CPP_SKILL_DIR` unset the shell fails at `/dev/null/...`
(126), and a bare `scripts/flow-finish-gate.sh` from a target worktree exits
127 or runs the target's own script; neither reaches this script, and both
read `not-observed`.

EXIT 125 ON ANY CHANNEL FAILURE, never a value the real helper uses
(0, 1, 2, 3, 4, 127).

Deliberately stdlib-only.
"""

from __future__ import annotations

import json
import os
import socket
import sys

TRIGGER_SOCKET_PATH = os.environ.get("SKILLC_TRIGGER_SOCKET", "/run/skillc/trigger.sock")
_REQUEST_TIMEOUT = 600.0  # a real quality-gate run can take minutes

#: The CLOSED map from a prescribed argv to its declared gate name.
_DECLARED_INVOCATIONS: dict[tuple[str, ...], str] = {
    ("--plan", "check", "--evidence", "flow-check"): "flow-check-plan",
    ("--check-summary",): "flow-check-summary",
}

EXIT_CHANNEL_FAILURE = 125

#: #529: which declared copy of the gate this shim stands in for. The
#: controller generates each placed copy with this one line set
#: (`agent_trial.bundled_gate_shim`), so it runs that copy's own root-owned
#: mirror and records the run's `via`. Never left `None` once placed.
_VIA: str | None = None


class _ChannelError(Exception):
    """Any failure to reach the channel, or a reply this script cannot read."""


def _ask(gate: str) -> dict[str, object]:
    body: dict[str, object] = {"op": "run_gate", "gate": gate, "cwd": os.getcwd()}
    if _VIA is not None:
        body["via"] = _VIA
    request = json.dumps(body) + "\n"
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


def _report_refusal(argv: list[str]) -> None:
    """#279 (orchestrator): a refused call is a behaviour the subject would not
    meet in real use, so it is COUNTED - reported to the controller before the
    125. Best effort: a report that cannot be sent changes nothing here, and
    the attempt's dropped-connection count says so."""
    body: dict[str, object] = {"op": "gate_refused", "argv": [a[:512] for a in argv[:64]], "cwd": os.getcwd()}
    if _VIA is not None:
        body["via"] = _VIA
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(10.0)
            sock.connect(TRIGGER_SOCKET_PATH)
            sock.sendall((json.dumps(body) + "\n").encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            while sock.recv(65536):
                pass
    except OSError:
        pass


def main(argv: list[str]) -> int:
    gate = _DECLARED_INVOCATIONS.get(tuple(argv[1:]))
    if gate is None:
        _report_refusal(argv[1:])
        print("flow-check-bundled-gate-shim: this invocation matches neither prescribed flow-check gate call - "
              "refusing rather than guessing", file=sys.stderr)
        return EXIT_CHANNEL_FAILURE
    try:
        result = _ask(gate)
    except _ChannelError as exc:
        print(f"flow-check-bundled-gate-shim: channel error: {exc}", file=sys.stderr)
        return EXIT_CHANNEL_FAILURE
    exit_code = result.get("exit_code")
    if not isinstance(exit_code, int):
        print(f"flow-check-bundled-gate-shim: the controller did not report a real exit code "
              f"(reason={result.get('reason')!r}) - treating as a channel failure", file=sys.stderr)
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
