#!/usr/bin/env python3
"""Test fixture only (issue #158) - a minimal stand-in for `tini`: execs
`argv[1:]` as a child, forwards a received SIGTERM to it, and - the one
property this file exists to provide - exits as soon as its child does,
mirroring both `tini`'s real forwarding behavior and, in a real container,
the fact that the kernel tears down the PID namespace once PID 1 exits.

Used by `tests/test_skillc_supervisor.py` to run the real (and, separately,
a monkeypatched mutant) `docker/trial/skillc-supervisor.py` under something
that behaves like its real parent, without this test environment needing
actual container/namespace privileges it does not have.
"""

from __future__ import annotations

import signal
import subprocess
import sys


def main(argv: list[str]) -> int:
    proc = subprocess.Popen(argv)

    def _forward(signum: int, _frame: object) -> None:
        proc.send_signal(signum)

    signal.signal(signal.SIGTERM, _forward)
    proc.wait()
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
