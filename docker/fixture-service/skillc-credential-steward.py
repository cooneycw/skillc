#!/usr/bin/python3 -IS
"""The credential steward (#518 A): keep the agent's codex credential out of
its home except while the controller's own client is reading it.

Runs INSIDE the attempt container AS ROOT, started by the controller
(`docker exec -d -u 0`) and placed root-owned like the nested-codex guard, so
the candidate (a different uid) can neither signal it nor read its vault.

WHY. `refusal-expected` was enforced only by the guard shim, and a login shell
never reached it (#518): a nested client the agent launched found the agent's
own `auth.json` and reached the model. Withdrawing the file removes what a
second client would authenticate with.

MEASURED BEHAVIOUR IT RELIES ON (codex-cli 0.157.1, #518 A1, network none):
- a healthy session reads `auth.json` 4 times and then never again (no write):
  read 1 at ~0.03 s, then a GAP of 0.49 / 0.51 / 1.33 s (three runs), then
  reads 2-4 within 5 ms. Withdrawing on the first close, or after a 500 ms
  quiet period, fell inside that gap and the client hung; a 3000 ms quiet
  period (2.25x the worst gap seen) withdrew after 4/4 reads and the client
  matched its baseline. Nested launches come minutes later (Step 6);
- a refresh (an expired token at start, or a 401) re-reads the file and
  rewrites it in place with O_CREAT. While ARMED that rewrite is captured at
  withdrawal, rotated tokens included. Once WITHDRAWN, 21 x 401 produced NO
  refresh and no rewrite: the client re-reads, finds nothing, and fails. The
  re-creation capture below is defence in depth for a version that differs.

STATES.
- ARMED: the file is present. Once `--quiet-ms` pass after the last close with
  no open in progress, it is moved into the vault: `withdrawn`. If no close is
  seen by `--deadline-s`, it is withdrawn anyway: `withdrawn-at-deadline`,
  which the controller reads as UNKNOWN (it cannot say the client loaded it).
- WITHDRAWN: any re-creation of `auth.json` is captured once its writer
  closes it - read, written to the vault as the CURRENT credential (the
  previous one kept beside it), then unlinked from the home - and reported
  `refreshed-captured`. The controller stops the schedule: during the gap a
  nested client could have read it, so the attempt is never credited.
- SIGUSR1: the controller restored the file for a resume turn; re-arm.
- SIGTERM: report `stopped` and exit.

RESIDUAL (orchestrator A3). The agent shares the client's uid, so the client's
memory and /proc are reachable. This enforces against an instructed or
accidental nested launch, not a hostile agent: ADR 0007's hygiene boundary,
never a security boundary.

Every event is sent to the controller over the attempt's trigger socket as
one closed `credential_steward` request. A send that fails changes nothing
here; the controller then sees fewer events than happened and reads UNKNOWN.

Deliberately stdlib-only, like every other in-container helper.
"""

from __future__ import annotations

import ctypes
import json
import os
import select
import signal
import socket
import struct
import sys
import time

TRIGGER_SOCKET_PATH = "/run/skillc/trigger.sock"
NAME = "auth.json"
IN_OPEN, IN_CLOSE_WRITE, IN_CLOSE_NOWRITE, IN_MOVED_TO, IN_CREATE = 0x20, 0x08, 0x10, 0x80, 0x100
_SEND_TIMEOUT = 5.0

_seq = 0
_rearm = False
_stop = False


def _send(event: str, **counts: int) -> None:
    global _seq
    _seq += 1
    body = {"op": "credential_steward", "event": event, "seq": _seq,
            "opens": int(counts.get("opens", 0)), "closes": int(counts.get("closes", 0))}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(_SEND_TIMEOUT)
            sock.connect(TRIGGER_SOCKET_PATH)
            sock.sendall((json.dumps(body) + "\n").encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            while sock.recv(65536):
                pass
    except OSError:
        pass  # the controller's record is then incomplete, which it reports


def _capture(home: str, vault: str) -> bool:
    """Move `home/auth.json` into the vault: read it whole, write it as the
    vault's current credential (keeping the previous one), then unlink it."""
    src = os.path.join(home, NAME)
    try:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return False
    with os.fdopen(fd, "rb") as handle:
        data = handle.read()
    current = os.path.join(vault, NAME)
    if os.path.exists(current):
        os.replace(current, os.path.join(vault, "auth.previous.json"))
    tmp = os.path.join(vault, ".auth.json.tmp")
    out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(out, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, current)
    os.unlink(src)
    return True


def _events(fd: int, timeout: float) -> list[int]:
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return []
    try:
        buf = os.read(fd, 65536)
    except OSError:
        return []
    masks, i = [], 0
    while i < len(buf):
        _, mask, _, length = struct.unpack_from("iIII", buf, i)
        name = buf[i + 16:i + 16 + length].rstrip(b"\0").decode("utf-8", errors="replace")
        i += 16 + length
        if name == NAME:
            masks.append(mask)
    return masks


def run(home: str, vault: str, quiet_s: float, deadline_s: float) -> int:
    global _rearm
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    if fd < 0 or libc.inotify_add_watch(fd, home.encode(), IN_OPEN | IN_CLOSE_WRITE | IN_CLOSE_NOWRITE
                                        | IN_MOVED_TO | IN_CREATE) < 0:
        _send("error")
        return 3
    os.makedirs(vault, mode=0o700, exist_ok=True)
    os.chmod(vault, 0o700)
    state, armed_at, last_close, open_now, opens, closes = "armed", time.monotonic(), None, 0, 0, 0
    pending_recreate = False
    _send("armed")
    while not _stop:
        if _rearm:
            _rearm = False
            state, armed_at, last_close, open_now, opens, closes = "armed", time.monotonic(), None, 0, 0, 0
            _send("armed")
        for mask in _events(fd, 0.05):
            if state == "armed":
                if mask & IN_OPEN:
                    opens += 1
                    open_now += 1
                if mask & (IN_CLOSE_NOWRITE | IN_CLOSE_WRITE):
                    closes += 1
                    open_now = max(0, open_now - 1)
                    last_close = time.monotonic()
            else:  # withdrawn: any appearance is a re-creation
                if mask & (IN_CREATE | IN_MOVED_TO):
                    pending_recreate = True
                if mask & IN_CLOSE_WRITE or (mask & IN_MOVED_TO):
                    pending_recreate = True
        now = time.monotonic()
        if state == "armed":
            quiet = last_close is not None and open_now == 0 and now - last_close >= quiet_s
            late = now - armed_at >= deadline_s
            if quiet or late:
                captured = _capture(home, vault)
                state = "withdrawn"
                _send("withdrawn" if quiet and captured else "withdrawn-at-deadline" if captured else "error",
                      opens=opens, closes=closes)
        elif pending_recreate:
            # Wait for the writer's close, then capture what it wrote.
            time.sleep(0.05)
            if _capture(home, vault):
                _send("refreshed-captured")
            pending_recreate = False
    _send("stopped")
    return 0


def _on_usr1(signum: int, frame: object) -> None:
    global _rearm
    _rearm = True


def _on_term(signum: int, frame: object) -> None:
    global _stop
    _stop = True


def main(argv: list[str]) -> int:
    args = dict(zip(argv[1::2], argv[2::2], strict=False))
    try:
        home, vault = args["--home-codex"], args["--vault"]
        quiet_s = int(args.get("--quiet-ms", "3000")) / 1000
        deadline_s = float(args.get("--deadline-s", "30"))
    except (KeyError, ValueError):
        return 2
    with open(args.get("--pidfile", "/run/skillc/credential-steward.pid"), "w") as pid:
        pid.write(f"{os.getpid()}\n")
    signal.signal(signal.SIGUSR1, _on_usr1)
    signal.signal(signal.SIGTERM, _on_term)
    return run(home, vault, quiet_s, deadline_s)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
