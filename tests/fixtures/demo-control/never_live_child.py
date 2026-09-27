"""Red-case child for `skillc demo --control`'s cancellation seed (issue #122).

Runs skillc's own CLI with ONE change: the cancel-target's subject sleeps
without ever writing `CANCEL_LIVE_FILE`, so its exec is never observed live.
The seed must send no SIGINT, kill the child, and report NOT CAUGHT - a
marker printed before `execute()` is not evidence of a live exec. Used only
by `tests/test_demo.py`.
"""

from __future__ import annotations

import sys

from skillc import cli, demo

demo._cancel_target_argv = demo._sleep_argv  # type: ignore[assignment]

if __name__ == "__main__":
    raise SystemExit(cli.main(sys.argv[1:]))
