"""pytest plugin (`-p ci.load_diag462`): record WHICH branch produced stop_confirmed=False (#462 Hold A).

Wraps DockerBackend._read_in_container_pid and _confirm_and_kill_in_container and
appends one JSON line per call to $DIAG462_OUT. During the confirm call, every
`kill -0` / `kill -SIG` exec is recorded with its exit, stderr head and duration,
so the outcome is attributable to: pid-None (marker poll expired), TERM-window
(alive past grace, then confirmed after KILL), KILL-poll (never confirmed dead),
or UNKNOWN (_alive() answered None: exec failed or timed out).
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from skillc import docker_backend as d

OUT = os.environ.get("DIAG462_OUT", "/dev/null")
_orig_read = d.DockerBackend._read_in_container_pid
_orig_confirm = d.DockerBackend._confirm_and_kill_in_container


def _log(rec: dict) -> None:
    rec["pid_of_test"] = os.getpid()
    rec["t"] = time.time()
    with open(OUT, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def _read(self, handle, marker_path, timeout=2.0):
    # Negative control only: DIAG462_FORCE_READ_TIMEOUT shrinks the poll so the
    # pid-None branch is shown to be recordable.
    timeout = float(os.environ.get("DIAG462_FORCE_READ_TIMEOUT", timeout))
    t0 = time.monotonic()
    pid = _orig_read(self, handle, marker_path, timeout)
    _log({"call": "read_pid", "pid": pid, "seconds": round(time.monotonic() - t0, 3),
          "timeout": timeout, "daemon_timeout": self.daemon_timeout})
    return pid


def _confirm(self, handle, pid, grace):
    calls: list[dict] = []
    real_run = subprocess.run

    def run(argv, *a, **kw):
        t0 = time.monotonic()
        try:
            proc = real_run(argv, *a, **kw)
        except subprocess.TimeoutExpired:
            calls.append({"argv": argv[-1], "exc": "timeout",
                          "seconds": round(time.monotonic() - t0, 3)})
            raise
        if isinstance(argv, list) and argv and "kill" in str(argv[-1]):
            calls.append({"argv": argv[-1], "rc": proc.returncode,
                          "stderr": proc.stderr[:120].decode("utf-8", "replace")
                          if isinstance(proc.stderr, bytes) else "",
                          "seconds": round(time.monotonic() - t0, 3)})
        return proc

    t0 = time.monotonic()
    subprocess.run = run
    try:
        ok = _orig_confirm(self, handle, pid, grace)
    finally:
        subprocess.run = real_run
    _log({"call": "confirm", "pid": pid, "grace": grace, "result": ok,
          "seconds": round(time.monotonic() - t0, 3), "execs": calls})
    return ok


setattr(d.DockerBackend, "_read_in_container_pid", _read)  # noqa: B010 - a monkeypatch
setattr(d.DockerBackend, "_confirm_and_kill_in_container", _confirm)  # noqa: B010 - a monkeypatch


# evidence_export: the captured attempt's WHOLE wall time beside its `timeout`.
# Hold A showed the two are different things: `timeout` is the agent exec's
# Limits(timeout=...) only, and whole attempts ran 12.8-32.4 s, all captured.
from skillc import collection_conformance as _cc

_orig_attempt = _cc.run_collection_agent_attempt


def _attempt(*a, **kw):
    t0 = time.monotonic()
    result = _orig_attempt(*a, **kw)
    _log({"call": "collection_attempt", "seconds": round(time.monotonic() - t0, 3),
          "timeout": kw.get("timeout"),
          "disposition": getattr(result, "record", {}).get("disposition")})
    return result


_cc.run_collection_agent_attempt = _attempt
