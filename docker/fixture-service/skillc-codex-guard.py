#!/usr/bin/python3 -IS
"""The nested-codex guard (#434 PR 2b, D3).

A flow:auto attempt's agent IS codex. If it ever reaches Step 6 it may start a
SECOND codex as its counter-model reviewer, and under #442's provider-only
egress that nested call reaches an allowed host and spends. This guard is
installed, per attempt and root-owned, at `/usr/local/sbin/codex`, which the
image's PATH searches before `/usr/local/bin`, where npm's real `codex` symlink
stays untouched. Every bare `codex` therefore runs this script first:

- NO codex ancestor (the harness's own launch: `docker exec` -> `sh -c
  'exec "$@"'` -> skillc-wrap -> execvp, all one pid whose parent is outside
  the container's pid namespace): pass through. `execve` the real codex with
  the ORIGINAL argv and environment, byte for byte, read back from
  `/proc/self/cmdline` and `/proc/self/environ`. Python's own startup (locale
  coercion, say) can change `os.environ`; the kernel's copy of what this
  process was given cannot.
- A codex ancestor: refuse, exit 3, the "unavailable" contract a caller's
  counter-model step records as skipped / reviewer-unavailable (measured
  against the pinned CPP 86641e8 receipt writer).
- Ancestry that cannot be read (a /proc read error, a pid that vanished
  mid-walk, a loop, too deep): FAIL CLOSED, exit 3, as ancestry-unknown. So
  are this call's own inputs when they cannot be read or reproduced exactly
  (no readable config, cmdline or environ; either larger than the read bound
  or not NUL-terminated; a duplicate or malformed environment entry): a
  pass-through could not then be byte for byte.

AN ANCESTOR IS CODEX ONLY ON AN EXACT MATCH (orchestrator ruling, condition 1):
its `/proc/<pid>/exe` realpath is the node binary AND its argv[1], resolved
against its own cwd, realpaths to the real codex.js; OR its exe realpath is
one of the vendored native codex binaries. There is no substring matching on
names or command lines: `sh -c "grep codex"` and a process named
`codex-something` are not codex.

Those realpaths come from `CONFIG`, a root-owned file the controller writes at
install time and verifies the candidate cannot write. Nothing is derived at run
time from anything the candidate can write.

EVERY DECISION IS SENT to the controller over the attempt's one trigger socket
as one `codex_guard` request: the decision and a digest of argv, nothing else.
The controller keeps the record, so nothing in the container can edit it. A
failed send changes nothing here: a refusal still exits 3, and the harness
launch still passes through. The controller then sees fewer decisions than
happened, and reports its count as UNKNOWN instead of 0.

THE DETECTION BOUND. A subject that calls the real codex.js or native binary
by absolute path never runs this script, so that call leaves NO record and
the controller's count can still read zero: zero means "no nested launch
came through the guard", never "none happened". A subject that double-forks
so its codex reparents to PID 1 (tini) runs it with no codex ancestor, so it
passes, and the controller counts it as a SECOND top-level launch, reported
as nested-suspected. A send the controller never receives is likewise
invisible; one it refuses marks the record unhealthy (UNKNOWN).

Deliberately stdlib-only, like every other in-container helper. `-IS` keeps
PYTHON* variables and site packages from steering the guard itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys

CONFIG = "/opt/skillc-harness/codex-guard.json"
TRIGGER_SOCKET_PATH = "/run/skillc/trigger.sock"
EXIT_UNAVAILABLE = 3
_MAX_DEPTH = 256
_SEND_TIMEOUT = 5.0
#: This call's own argv and environment are read whole, up to this bound; more
#: is refused, never truncated (a cut-off pass-through is not byte for byte).
_MAX_SELF_BYTES = 64 << 20


class _TooLarge(Exception):
    """This call's own inputs exceed `_MAX_SELF_BYTES`."""


class _Unknown(Exception):
    """The ancestry could not be read completely."""


def _read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(1 << 20)


def _read_whole(path: str) -> bytes:
    """A NUL-terminated /proc block, read completely or refused."""
    with open(path, "rb") as handle:
        data = handle.read(_MAX_SELF_BYTES + 1)
    if len(data) > _MAX_SELF_BYTES:
        raise _TooLarge(path)
    if data and not data.endswith(b"\0"):
        raise _TooLarge(f"{path} is not NUL-terminated")
    return data


def _ppid(pid: int) -> int:
    stat = _read(f"/proc/{pid}/stat")
    # The command name sits in parentheses and may itself hold ") "; the
    # fields after the LAST ")" are fixed: state, then ppid.
    fields = stat[stat.rindex(b")") + 2:].split()
    return int(fields[1])


def _is_codex(pid: int, config: dict[str, object]) -> bool:
    exe = os.path.realpath(os.readlink(f"/proc/{pid}/exe"))
    if exe in config["native"]:  # type: ignore[operator]
        return True
    if exe != config["node"]:
        return False
    argv = _read(f"/proc/{pid}/cmdline").split(b"\0")
    if len(argv) < 2 or not argv[1]:
        return False
    script = os.fsdecode(argv[1])
    if not script.startswith("/"):
        script = os.path.join(os.readlink(f"/proc/{pid}/cwd"), script)
    return os.path.realpath(script) == config["codex_js"]


def decide(config: dict[str, object], start: int) -> str:
    """`passed-top-level`, `refused-nested` or `refused-ancestry-unknown`."""
    pid, seen = start, set()
    try:
        while pid != 0:  # 0: the parent is outside this pid namespace
            if pid in seen or len(seen) >= _MAX_DEPTH:
                raise _Unknown(f"ancestry loops or is deeper than {_MAX_DEPTH}")
            seen.add(pid)
            if _is_codex(pid, config):
                return "refused-nested"
            pid = _ppid(pid)
    except (OSError, ValueError, IndexError, _Unknown):
        return "refused-ancestry-unknown"
    return "passed-top-level"


def _load_config() -> dict[str, object] | None:
    try:
        config = json.loads(_read(CONFIG))
    except (OSError, ValueError):
        return None
    if (not isinstance(config, dict) or set(config) != {"real", "node", "codex_js", "native"}
            or not all(isinstance(config[k], str) and config[k].startswith("/") for k in ("real", "node", "codex_js"))
            or not isinstance(config["native"], list) or not config["native"]
            or not all(isinstance(n, str) and n.startswith("/") for n in config["native"])):
        return None
    return config


def _send(decision: str, argv: list[bytes]) -> None:
    digest = "sha256:" + hashlib.sha256(b"\0".join(argv)).hexdigest()
    line = json.dumps({"op": "codex_guard", "decision": decision, "argv_digest": digest}) + "\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(_SEND_TIMEOUT)
            sock.connect(TRIGGER_SOCKET_PATH)
            sock.sendall(line.encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            while sock.recv(65536):
                pass
    except OSError:
        pass  # the controller's count is then incomplete, which it reports


def main() -> int:
    try:
        cmdline = _read_whole("/proc/self/cmdline").split(b"\0")[:-1]
        environ = [e for e in _read_whole("/proc/self/environ").split(b"\0") if e]
    except (OSError, _TooLarge):
        cmdline, environ = [], []
    # The kernel ran `python3 -IS <this script> <args...>`: the caller's own
    # arguments start after the script path.
    script = os.fsencode(sys.argv[0])
    args = cmdline[cmdline.index(script) + 1:] if script in cmdline else None
    config = _load_config()
    # `os.execve` takes a mapping, so an environment it cannot carry exactly
    # (a duplicate name, an entry with no "=") would reach the real codex
    # changed. That call's inputs cannot be reproduced, so it is refused.
    names = [entry.partition(b"=")[0] for entry in environ]
    exact = bool(environ) and all(b"=" in entry for entry in environ) and len(set(names)) == len(names)
    if config is None or args is None or not exact:
        decision = "refused-ancestry-unknown"
    else:
        decision = decide(config, os.getppid())
    _send(decision, [script, *(args or [])])
    if decision != "passed-top-level":
        sys.stderr.write("CODEX_REVIEW: unavailable (a nested codex is not available inside this trial: "
                         f"{decision})\n")
        return EXIT_UNAVAILABLE
    assert config is not None and args is not None
    real = str(config["real"])
    env = {}
    for entry in environ:
        key, _, value = entry.partition(b"=")
        env[key] = value
    os.execve(real, [os.fsencode(os.path.basename(real)), *args], env)
    return EXIT_UNAVAILABLE  # unreachable: execve replaces this process or raises


if __name__ == "__main__":
    sys.exit(main())
