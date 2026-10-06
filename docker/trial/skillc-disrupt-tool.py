#!/usr/bin/env python3
"""The subject-side client for #183's controller-owned decide-and-reply
channel, baked into the trial image at a fixed path - "the required tool"
`evals/level5/recovery-partial-processing/goal.md` tells the subject may
become unavailable partway through. A subject's tool wrapper runs this
once per use of that tool; this script's EXIT CODE is the whole interface
back to it - 0 means proceed, 1 means the tool failed this time, per the
fixture's own semantics (orchestrator ruling on #183 PR B). Nothing this
script or the subject writes anywhere is ever read by a grader - the one
and only trusted side of this exchange is the controller's own log,
retrieved by the controller directly via `DecideReplyChannel.trusted_log()`,
never through this process or anything it could influence.

NO ARGUMENTS, NO REQUEST CONTENT BEYOND A FIXED `op`. `decide_reply_
channel.py`'s own module docstring is explicit: "THE CONTROLLER NUMBERS
REQUESTS, NEVER THE SUBJECT" - so this script has nothing truthful to say
about which step it is on, and says nothing at all. The controller's own
`decide` function (`evals/level5/recovery-partial-processing/
disruption_channel.py`) counts requests itself and decides allow/refuse
from ITS OWN counter against the fixture's calibrated threshold.

Exit codes, a closed, named vocabulary (never conflate two of these):
  0   allow - the tool call succeeded.
  1   fail-now - the controller decided this call fails (the calibrated
      disruption point), per the fixture's own semantics for "the tool
      became unavailable".
  2   infrastructure error - the channel could not be reached at all, or
      replied in a shape this script does not recognize. Distinct from 1
      on purpose: a caller must be able to tell "the fixture's disruption
      fired" from "something is broken here" without guessing from stderr
      text alone.

Deliberately stdlib-only, matching `skillc-wrap.py`/`skillc-supervisor.py`.
"""

from __future__ import annotations

import json
import os
import socket
import sys

#: Must resolve the same way `skillc.docker_backend.TRIGGER_SOCKET_PATH`
#: does - the one fixed in-container path the bind mount always lands on
#: (decide-reply-channel.md section 2a). Overridable only for testing
#: this script outside a real container; a real trial container never
#: sets this, so the default is what actually ships.
TRIGGER_SOCKET_PATH = os.environ.get("SKILLC_TRIGGER_SOCKET", "/run/skillc/trigger.sock")
_REQUEST_TIMEOUT = 5.0
OP = "tool-call"


def _ask() -> bool:
    """Connects, sends one request, reads one reply, closes - the exact
    one-shot framing `decide_reply_channel.py`'s own module docstring
    specifies. Raises `OSError` (unreachable, refused, timed out) or
    `ValueError` (a reply this script cannot parse as the expected
    shape) - both mapped to exit code 2 by `main()`, never silently
    treated as either allow or fail-now; a broken channel is not
    evidence of either."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(_REQUEST_TIMEOUT)
        sock.connect(TRIGGER_SOCKET_PATH)
        sock.sendall((json.dumps({"op": OP}) + "\n").encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    line = b"".join(chunks).decode("utf-8", errors="replace").strip()
    try:
        reply = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"reply is not JSON: {exc}") from exc
    if not isinstance(reply, dict) or reply.get("ok") is not True or not isinstance(reply.get("allow"), bool):
        raise ValueError(f"reply is not the expected {{'ok': true, 'allow': bool}} shape: {reply!r}")
    return bool(reply["allow"])


def main(argv: list[str]) -> int:
    if argv[1:]:
        print("skillc-disrupt-tool: takes no arguments", file=sys.stderr)
        return 2
    try:
        allow = _ask()
    except (OSError, ValueError) as exc:
        print(f"skillc-disrupt-tool: channel error: {exc}", file=sys.stderr)
        return 2
    if allow:
        return 0
    print("skillc-disrupt-tool: tool unavailable", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
