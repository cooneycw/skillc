#!/usr/bin/env python3
"""A `gh` stand-in that forwards to the controller's fixture service (#276).

Installed by a trial profile where `gh` would be (that wiring is #434's).
The trial image has no `gh` and no network, and real GitHub is never
reached: every invocation is sent, as one `op: "gh"` request, over #183's
decide-and-reply channel to `skillc/fixture_service.py` running in the
CONTROLLER, which parses it against a closed grammar, records it and
answers. This script writes the answer back byte for byte - stdout, stderr
and exit code - and decides nothing itself.

WHAT IT SENDS, AND WHY THAT IS NOT A TRUST GAP. Beside argv and cwd it sends
the two pieces of local git context real `gh` reads from the checkout - the
`origin` URL (which repository) and the current branch (which PR, for
`gh pr view` with no number) - and the contents of any `--body-file`, which
real `gh` also reads locally. All of it is the subject's own input in real
use too. The service only ever answers for ONE declared repository, so a
forged origin can only make a request fail as `wrong-repository`; it cannot
reach another repository's state, and nothing here can write the record.

EXIT 125 ON ANY CHANNEL FAILURE, the same convention as
`flow-check-gate-shim.py`: never 0, and never a value the service itself
returns, so a failure to reach the controller is never read as a gh answer.

Deliberately stdlib-only, matching the other `docker/trial/` helpers.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys

#: Must resolve the same way `skillc.docker_backend.TRIGGER_SOCKET_PATH`
#: does - overridable only for testing this script outside a container.
TRIGGER_SOCKET_PATH = os.environ.get("SKILLC_TRIGGER_SOCKET", "/run/skillc/trigger.sock")
_REQUEST_TIMEOUT = 60.0
_MAX_BODY_FILE = 48 * 1024  # the channel refuses a request line over 64 KiB
EXIT_CHANNEL_FAILURE = 125


class _ChannelError(Exception):
    """Any failure to reach the channel, or a reply this script cannot read."""


def _git(*args: str) -> str | None:
    try:
        proc = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def _body_files(argv: list[str]) -> dict[str, str]:
    """The contents of every `--body-file`/`-F` value, keyed by the value as
    given (`-` is stdin), base64-encoded."""
    files: dict[str, str] = {}
    for index, token in enumerate(argv):
        name, eq, inline = token.partition("=")
        if name not in ("--body-file", "-F"):
            continue
        path = inline if eq else (argv[index + 1] if index + 1 < len(argv) else None)
        if path is None or path in files:
            continue
        try:
            if path == "-":
                data = sys.stdin.buffer.read(_MAX_BODY_FILE + 1)
            else:
                with open(path, "rb") as handle:
                    data = handle.read(_MAX_BODY_FILE + 1)
        except OSError:
            continue  # the service answers "no such file", as gh would
        if len(data) > _MAX_BODY_FILE:
            raise _ChannelError(f"--body-file {path!r} is larger than {_MAX_BODY_FILE} bytes")
        files[path] = base64.b64encode(data).decode("ascii")
    return files


def _ask(request: dict[str, object]) -> dict[str, object]:
    line = json.dumps(request) + "\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(_REQUEST_TIMEOUT)
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
        reply = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ChannelError(f"reply is not JSON: {exc}") from exc
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        raise _ChannelError(f"the channel refused this request: {reply!r}")
    result = reply.get("result")
    if (not isinstance(result, dict) or not isinstance(result.get("exit_code"), int)
            or not isinstance(result.get("stdout"), str) or not isinstance(result.get("stderr"), str)):
        raise _ChannelError(f"reply's 'result' is not a gh answer: {reply!r}")
    return result


def main(argv: list[str]) -> int:
    args = argv[1:]
    try:
        context = {"origin_url": _git("config", "--get", "remote.origin.url"),
                   "branch": _git("branch", "--show-current")}
        request = {"op": "gh", "argv": args, "cwd": os.getcwd(), "context": context,
                   "body_files": _body_files(args)}
        result = _ask(request)
    except _ChannelError as exc:
        print(f"skillc-gh-shim: channel error: {exc}", file=sys.stderr)
        return EXIT_CHANNEL_FAILURE
    sys.stdout.write(str(result["stdout"]))
    sys.stderr.write(str(result["stderr"]))
    code = int(result["exit_code"])  # type: ignore[call-overload]
    return code if code != EXIT_CHANNEL_FAILURE else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
