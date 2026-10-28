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
- WITHDRAWN: any appearance of `auth.json` LATCHES an exposure. It is captured
  once its writer closes it (or after a short grace, for a writer that holds
  it open) - read, written to the vault as the CURRENT credential (the
  previous one kept beside it), then unlinked from the home - and reported
  `refreshed-captured`; a capture that fails reports `error` and is retried.
  Either way the controller stops the schedule: during the gap a nested
  client could have read it, so the attempt is never credited.
- SIGUSR1: a resume turn is next. The STEWARD restores the vaulted file
  itself, then discards its own write's events and re-arms (`armed`), so the
  opens it counts afterwards are the client's, never the restore's.
- SIGTERM: report `stopped` and exit.

FAILS CLOSED. Every path operation goes through ONE directory fd opened at
start with `O_NOFOLLOW`, so a candidate who swaps `.codex` or `auth.json` for
a symlink cannot steer a root read, write, chown or unlink anywhere else; the
restore is created `O_EXCL|O_NOFOLLOW` under a temporary name, owned via the
fd, and renamed into place. An inotify queue overflow, a watch the kernel
invalidates, or an unreadable queue reports `error`: events were lost, so
the record cannot be read as held.

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
import stat
import struct
import sys
import time

TRIGGER_SOCKET_PATH = "/run/skillc/trigger.sock"
NAME = "auth.json"
IN_OPEN, IN_CLOSE_WRITE, IN_CLOSE_NOWRITE, IN_MOVED_TO, IN_CREATE = 0x20, 0x08, 0x10, 0x80, 0x100
#: Nameless events that mean the watch lost events or no longer exists.
IN_DELETE_SELF, IN_MOVE_SELF, IN_UNMOUNT, IN_Q_OVERFLOW, IN_IGNORED = 0x400, 0x800, 0x2000, 0x4000, 0x8000
LOST = IN_DELETE_SELF | IN_MOVE_SELF | IN_UNMOUNT | IN_Q_OVERFLOW | IN_IGNORED
RESTORE_TMP = ".auth.json.skillc-restore"
#: A re-created file whose writer never closes it is captured after this long.
CLOSE_GRACE_S = 2.0
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


def _capture(dfd: int, vault: str) -> bool:
    """Move `auth.json` (in the watched directory, by fd) into the vault: read
    it whole, write it as the vault's current credential (keeping the
    previous one), then unlink it. Never follows a link; refuses a non-file;
    any failure is `False` (the caller reports it), never a dead steward."""
    try:
        fd = os.open(NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dfd)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return False
            data = handle.read()
        current = os.path.join(vault, NAME)
        tmp = os.path.join(vault, ".auth.json.tmp")
        out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(out, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if os.path.exists(current):
            os.replace(current, os.path.join(vault, "auth.previous.json"))
        os.replace(tmp, current)
        os.unlink(NAME, dir_fd=dfd)
        return True
    except OSError:
        return False


def _restore(dfd: int, vault: str) -> bool:
    """Put the vaulted credential back for a resume turn, owned like the
    directory (the candidate), 0600: created `O_EXCL|O_NOFOLLOW` under a
    temporary name, owned and moded through its fd, then renamed over
    `auth.json` - which replaces a planted link rather than following it."""
    try:
        with open(os.path.join(vault, NAME), "rb") as handle:
            data = handle.read()
        owner = os.fstat(dfd)
        for _ in range(2):
            try:
                fd = os.open(RESTORE_TMP, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=dfd)
                break
            except FileExistsError:
                os.unlink(RESTORE_TMP, dir_fd=dfd)  # unlinkat never follows
        else:
            return False
        with os.fdopen(fd, "wb") as handle:
            os.fchown(handle.fileno(), owner.st_uid, owner.st_gid)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(RESTORE_TMP, NAME, src_dir_fd=dfd, dst_dir_fd=dfd)
        return True
    except OSError:
        return False


def _events(fd: int, timeout: float) -> list[int] | None:
    """The masks for `auth.json`, plus every NAMELESS mask (overflow, a
    removed or moved watch). `None` when the queue could not be read."""
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return []
    try:
        buf = os.read(fd, 65536)
    except BlockingIOError:
        return []
    except OSError:
        return None
    masks, i = [], 0
    while i + 16 <= len(buf):
        _, mask, _, length = struct.unpack_from("iIII", buf, i)
        name = buf[i + 16:i + 16 + length].rstrip(b"\0").decode("utf-8", errors="replace")
        i += 16 + length
        if name == NAME or not name:
            masks.append(mask)
    return masks


def _drain(fd: int) -> list[int] | None:
    """Everything already queued (the steward's own restore), discarded -
    except a lost-events mask, which the caller must still see."""
    lost: list[int] = []
    while True:
        masks = _events(fd, 0)
        if masks is None:
            return None
        if not masks:
            return lost
        lost += [m for m in masks if m & LOST]


def run(home: str, vault: str, quiet_s: float, deadline_s: float) -> int:
    global _rearm
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        dfd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        _send("error")
        return 3
    fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    # Watched through the held fd, so a later swap of the path is not followed.
    # DELETE_SELF/MOVE_SELF are asked for: the directory moved away leaves this
    # watch on the old inode while a new `.codex` could appear at the path.
    if fd < 0 or libc.inotify_add_watch(fd, f"/proc/self/fd/{dfd}".encode(), IN_OPEN | IN_CLOSE_WRITE
                                        | IN_CLOSE_NOWRITE | IN_MOVED_TO | IN_CREATE
                                        | IN_DELETE_SELF | IN_MOVE_SELF) < 0:
        _send("error")
        return 3
    os.makedirs(vault, mode=0o700, exist_ok=True)
    os.chmod(vault, 0o700)
    state, armed_at, last_close, open_now, opens, closes = "armed", time.monotonic(), None, 0, 0, 0
    exposed_at: float | None = None  # a re-creation seen while withdrawn, not yet captured
    writer_closed = capture_failed = False
    broken = False  # events were lost; reported once, never cleared
    _send("armed")
    while not _stop:
        if _rearm:
            _rearm = False
            if state != "withdrawn" or exposed_at is not None or not _restore(dfd, vault):
                _send("error")
            else:
                lost = _drain(fd)
                if lost is None or lost:
                    broken = True
                    _send("error")
                state, armed_at, last_close, open_now, opens, closes = "armed", time.monotonic(), None, 0, 0, 0
                _send("armed")
        masks = _events(fd, 0.05)
        if masks is None:
            masks = [IN_Q_OVERFLOW]
        for mask in masks:
            if mask & LOST:
                if not broken:
                    broken = True
                    _send("error")
                continue
            if state == "armed":
                if mask & IN_OPEN:
                    opens += 1
                    open_now += 1
                if mask & (IN_CLOSE_NOWRITE | IN_CLOSE_WRITE):
                    closes += 1
                    open_now = max(0, open_now - 1)
                    last_close = time.monotonic()
            else:  # withdrawn: any appearance is a re-creation, latched until captured
                # Only a create or a move can make it re-appear; the steward's
                # own capture read (OPEN, CLOSE_NOWRITE) never latches.
                if mask & (IN_CREATE | IN_MOVED_TO) and exposed_at is None:
                    exposed_at, writer_closed, capture_failed = time.monotonic(), False, False
                if mask & (IN_CLOSE_WRITE | IN_MOVED_TO):
                    writer_closed = True
        now = time.monotonic()
        if state == "armed":
            quiet = last_close is not None and open_now == 0 and now - last_close >= quiet_s
            late = now - armed_at >= deadline_s
            if quiet or late:
                captured = _capture(dfd, vault)
                state = "withdrawn"
                _send("withdrawn" if quiet and captured else "withdrawn-at-deadline" if captured else "error",
                      opens=opens, closes=closes)
        elif exposed_at is not None and (writer_closed or now - exposed_at >= CLOSE_GRACE_S):
            if _capture(dfd, vault):
                _send("refreshed-captured")
                exposed_at = None
            else:
                # Still latched: retried after another grace, reported once.
                if not capture_failed:
                    capture_failed = True
                    _send("error")
                exposed_at, writer_closed = now, False
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
        home, vault = args["--codex-dir"], args["--vault"]
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
