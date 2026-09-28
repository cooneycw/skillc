#!/usr/bin/env python3
"""A one-shot registering exec wrapper (issue #158). `docker_backend.py`'s
`execute()` prefixes the subject's argv with this script - once the #78
image change lands (currently HELD, see `skillc-supervisor.py`'s own
docstring) - instead of running the subject directly, so the container's
`skillc-supervisor` can learn the subject's real process group before a
container-level TERM ever needs to reach it.

Runs as `candidate`, inside the same container and the same trust boundary
as the subject it wraps - this registration is advisory instrumentation,
never trusted evidence (docs/specs/evaluation-facility/signal-forwarding.md
section 2b/5): anything this script tells the supervisor, the subject
itself could tell it too, once it takes over this process's identity in
step 2 below.

Deliberately stdlib-only, matching `skillc-supervisor.py`.
"""

from __future__ import annotations

import os
import socket
import sys

#: Must resolve the same way skillc-supervisor.py's own default does - see
#: that file's comment on $SKILLC_CONTROL_SOCKET for why this is overridable.
CONTROL_SOCKET_PATH = os.environ.get("SKILLC_CONTROL_SOCKET", "/run/skillc/control.sock")
_REGISTER_TIMEOUT = 1.0


def _register() -> None:
    """Best-effort, bounded, and never fatal to the subject's launch - a
    supervisor that is unreachable (image predates this work at the
    binary level, crashed, permission issue) must not block or refuse the
    subject: fails open to the pre-#158 behavior, just without forwarding."""
    pgid = os.getpgrp()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(_REGISTER_TIMEOUT)
            sock.connect(CONTROL_SOCKET_PATH)
            sock.sendall(f"REGISTER {pgid}\n".encode())
            try:
                sock.recv(64)
            except OSError:
                pass
    except OSError:
        pass


def main(argv: list[str]) -> int:
    if not argv:
        print("skillc-wrap: requires a subject argv", file=sys.stderr)
        return 2

    # Becomes its own process group leader BEFORE registering, so the pgid
    # reported is stable for the subject's whole life (a CLI agent subject
    # will plausibly fork its own children, which inherit this group unless
    # one explicitly starts its own session) - see the design doc section 2b.
    os.setsid()

    _register()

    # Replaces this process's own image with the subject's, preserving the
    # pid (and, from setsid() above, the pgid) - no separate parent/child
    # relationship to track, no second lookup. Everything the caller already
    # set up (stdin/stdout/stderr, the working directory) is inherited
    # unchanged, so this wrapper is invisible to DockerBackend.execute()
    # beyond the one-token argv prefix.
    os.execvp(argv[0], argv)
    return 1  # unreachable: execvp replaces this process or raises OSError


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
