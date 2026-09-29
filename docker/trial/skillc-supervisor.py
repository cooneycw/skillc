#!/usr/bin/env python3
"""The trial container's foreground process (issue #158), replacing the
`sleep infinity` keep-alive placeholder `docker/trial/Dockerfile` bakes in
once this design lands (docs/specs/evaluation-facility/signal-forwarding.md
- currently HELD there, pending the operator's #150 discriminating run; this
file exists as a source file in the repo, not yet referenced by the
Dockerfile).

Runs as `candidate`, under `--init` (`tini` is PID 1; this process is
`tini`'s direct child, and `tini` already forwards a container-level signal
to it - that part is unchanged from the plain `sleep infinity` placeholder
this replaces). Listens on a Unix domain socket for a `skillc-wrap`
instance to register the subject's process group, and relays a received
SIGTERM to that group with SIGTERM of its own.

LOAD-BEARING RULE, stated once here and enforced by never doing the
opposite: this process MUST NOT exit after relaying a signal. It is
`tini`'s ONLY child - if it lets itself exit, `tini` has nothing left to
supervise and exits too, PID 1 is gone, and the kernel tears down the
container's PID namespace, SIGKILLing everything left in it (the subject
included) within microseconds. That would defeat forwarding via the exact
mechanism issue #176 modeled for the no-supervisor case, self-inflicted.
So the SIGTERM handler below only relays and returns; the main loop keeps
blocking afterward, and this file carries no code path - test-only or
otherwise - that lets it exit on TERM. `tests/test_skillc_supervisor.py`
proves the invariant by running an actual mutant handler, never a flag in
this file.

Deliberately stdlib-only (matches AGENTS.md's repo-wide rule and
`tests/fixtures/docker-backend/fake_docker.py`'s own self-containment): no
dependency on the `skillc` package being importable inside the trial image.
"""

from __future__ import annotations

import os
import signal
import socket
import sys
import threading

#: Overridable via $SKILLC_CONTROL_SOCKET so a host-side test can point this
#: at a writable tmp path (the real /run/skillc/ is root-owned outside the
#: trial container, where it is pre-created and chowned to candidate at
#: image build time - see docker/trial/Dockerfile's own eventual change,
#: held per docs/specs/evaluation-facility/signal-forwarding.md section 3).
#: This is configurability, not a safety-rule switch: it changes WHERE the
#: socket lives, never whether this process survives a relayed TERM.
CONTROL_SOCKET_PATH = os.environ.get("SKILLC_CONTROL_SOCKET", "/run/skillc/control.sock")
CONTROL_SOCKET_DIR = os.path.dirname(CONTROL_SOCKET_PATH)

_registered_pgid: int | None = None
_lock = threading.Lock()


def _handle_register(conn: socket.socket) -> None:
    """One connection, one message: `REGISTER <pgid>\n`. Best-effort - a
    malformed or unreadable message is dropped, never raised, since a
    supervisor that crashed handling a bad message would itself violate the
    must-not-exit rule this file exists to uphold.

    REFUSES `pgid <= 1` and `pgid == os.getpgrp()` (review must-fix, PR
    #182): this supervisor's own process group is exactly what `_on_term`
    would `os.killpg(..., SIGTERM)` right back at ITSELF if it accepted
    such a registration - a TERM storm (the handler re-entering itself via
    the very signal it just sent), not merely a wrong relay target. A
    hostile subject could request this directly; a `skillc-wrap` whose own
    `os.setsid()` failed silently would produce it by accident (`pgid <= 1`
    covers both PID 1 and PID 0, neither ever a legitimate registration).
    Refusing means `_registered_pgid` stays at its previous value (`None`,
    or whatever a prior legitimate registration set) rather than being
    overwritten by a bad one - the client gets no `OK`, matching the
    fail-open contract `skillc-wrap` already expects on any registration
    problem."""
    global _registered_pgid
    try:
        conn.settimeout(2.0)
        data = conn.recv(256)
        line = data.decode("utf-8", errors="replace").strip()
        if line.startswith("REGISTER "):
            pgid = int(line.removeprefix("REGISTER ").strip())
            if pgid <= 1 or pgid == os.getpgrp():
                return
            with _lock:
                _registered_pgid = pgid
            try:
                conn.sendall(b"OK\n")
            except OSError:
                pass
    except (OSError, ValueError):
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _accept_loop(server: socket.socket) -> None:
    """Runs on its own thread so registration handling never blocks this
    process's own signal responsiveness (the main thread stays free to
    receive and act on SIGTERM at any time)."""
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        _handle_register(conn)


def _on_term(_signum: int, _frame: object) -> None:
    """Relay-and-return, never relay-and-exit (see the module docstring's
    load-bearing rule). A liveness check (`os.killpg(pgid, 0)`) before the
    real signal avoids chasing a pgid a since-exited subject's slot may have
    been reused for by an unrelated process - the same discipline
    `docs/specs/evaluation-facility/signal-forwarding.md` section 2a
    specifies."""
    with _lock:
        pgid = _registered_pgid
    if pgid is None:
        return
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return
    except PermissionError:
        pass
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def main() -> int:
    """SHOULD-FIX (review, PR #182): a bind failure here must not crash this
    process. Letting an exception propagate would exit main(), which exits
    this process, which - being `tini`'s only child - takes the container
    down at `prepare()` time and fails the trial loudly. That contradicts
    the design's own fail-open principle just as much as exiting after a
    relay would: a supervisor that cannot get a socket should behave like
    the `sleep infinity` placeholder it replaces, not like a crash. So a
    bind failure is reported (one line to stderr - this process has no
    other channel) and falls through to the same pause loop either way;
    the capability gate then correctly sees no socket and reports
    `unavailable-in-image`, which is the honest answer."""
    signal.signal(signal.SIGTERM, _on_term)

    try:
        os.makedirs(CONTROL_SOCKET_DIR, exist_ok=True)
        try:
            os.unlink(CONTROL_SOCKET_PATH)
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(CONTROL_SOCKET_PATH)
        server.listen(8)
    except OSError as exc:
        print(f"skillc-supervisor: could not bind {CONTROL_SOCKET_PATH!r}: {exc}", file=sys.stderr)
    else:
        accept_thread = threading.Thread(target=_accept_loop, args=(server,), daemon=True)
        accept_thread.start()

    # The main loop: block forever. This is the keep-alive role
    # `sleep infinity` played before this file existed, and the only
    # correct response to SIGTERM is to keep doing exactly this afterward -
    # see the module docstring's load-bearing rule. signal.pause() wakes on
    # every delivered signal (not only ones with a handler installed), so
    # this simply re-blocks in a loop rather than treating a wakeup as a
    # reason to stop.
    while True:
        signal.pause()


if __name__ == "__main__":
    sys.exit(main())
