"""SCRATCH (#412 measurement, never merged): env-gated timing probe.

With SKILLC_TIMING_LOG=<dir>, every subprocess.run / Popen.wait / Popen.communicate
call that carries a timeout, and every DockerBackend.execute, appends one JSON line
to <dir>/<pid>.jsonl: test id, kind, argv head, deadline, elapsed, outcome. The
elapsed is measured at the CALLER, so it includes spawn and interpreter start -
the part host load inflates - not just the fake daemon's own work.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time

_TLS = threading.local()

_DIR = os.environ.get("SKILLC_TIMING_LOG")


def _emit(kind: str, argv: object, deadline: object, start: float, outcome: str) -> None:
    rec = {"t": round(start, 3), "test": os.environ.get("PYTEST_CURRENT_TEST", "").rsplit(" ", 1)[0],
           "kind": kind, "argv": [str(a) for a in (argv if isinstance(argv, (list, tuple)) else [argv])][:6],
           "deadline": deadline, "elapsed": round(time.time() - start, 4), "outcome": outcome}
    with open(os.path.join(_DIR, f"{os.getpid()}.jsonl"), "a", encoding="utf-8") as fh:  # type: ignore[arg-type]
        fh.write(json.dumps(rec) + "\n")



def install() -> None:
    if not _DIR:
        return
    os.makedirs(_DIR, exist_ok=True)
    real_run = subprocess.run

    def run(*args, **kwargs):  # type: ignore[no-untyped-def]
        timeout = kwargs.get("timeout")
        if timeout is None:
            return real_run(*args, **kwargs)
        start = time.time()
        _TLS.inner = True
        try:
            out = real_run(*args, **kwargs)
        except subprocess.TimeoutExpired:
            _TLS.inner = False
            _emit("run", args[0] if args else kwargs.get("args"), timeout, start, "TimeoutExpired")
            raise
        _TLS.inner = False
        _emit("run", args[0] if args else kwargs.get("args"), timeout, start, f"rc={out.returncode}")
        return out

    subprocess.run = run  # type: ignore[assignment]

    for name in ("wait", "communicate"):
        real = getattr(subprocess.Popen, name)

        def make(real=real, name=name):  # type: ignore[no-untyped-def]
            def wrapped(self, *a, **kw):  # type: ignore[no-untyped-def]
                timeout = kw.get("timeout", a[-1] if (name == "wait" and a) else (a[1] if len(a) > 1 else None))
                if timeout is None or getattr(_TLS, "inner", False):
                    return real(self, *a, **kw)
                start = time.time()
                try:
                    out = real(self, *a, **kw)
                except subprocess.TimeoutExpired:
                    _emit(f"popen.{name}", self.args, timeout, start, "TimeoutExpired")
                    raise
                _emit(f"popen.{name}", self.args, timeout, start, "ok")
                return out
            return wrapped

        setattr(subprocess.Popen, name, make())

    from skillc import docker_backend as d

    real_exec = d.DockerBackend.execute

    def execute(self, handle, argv, limits, *a, **kw):  # type: ignore[no-untyped-def]
        start = time.time()
        res = real_exec(self, handle, argv, limits, *a, **kw)
        _emit("execute", argv, getattr(limits, "timeout", None), start, f"reason={getattr(res, 'reason', '?')}")
        return res

    d.DockerBackend.execute = execute  # type: ignore[method-assign]
