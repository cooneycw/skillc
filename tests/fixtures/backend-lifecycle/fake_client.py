"""A deterministic stand-in for an agent under test, run by FakeBackend (#10,
PR1b) inside its (fake) isolation.

    fake_client.py MODE

Modes:
    work        touch the planted liveness canary if present (read
                `.skillc-canary`, write `.skillc-canary-result`), write
                ordinary output, then exit 0
    fail        same as work, then exit 1 - a "semantic failure": it ran, but
                the task did not succeed. The lifecycle driver still captures
                it; whether it PASSES is verify.py's question (#9), not this
                driver's.
    hang        same as work, then sleep until killed (timeout / cancellation)
    noop        exit 0 immediately, touching nothing at all
    reply-only  write plausible-looking output, but do NOT touch the canary.
                The addendum's own extended negative control (issue #10
                comment 5848522578, items 1-2): a "reply OK" that never
                invoked the actual skill or tool. Defeats the weaker
                content-diff liveness fallback (new prose IS a change) but
                must not defeat the nonce canary.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

CANARY_INPUT = Path(".skillc-canary")
CANARY_OUTPUT = Path(".skillc-canary-result")


def _touch_canary() -> None:
    if CANARY_INPUT.is_file():
        nonce = CANARY_INPUT.read_text(encoding="utf-8")
        CANARY_OUTPUT.write_text(f"touched:{nonce}", encoding="utf-8")


def main() -> int:
    mode = sys.argv[1]
    if mode == "noop":
        return 0
    if mode == "reply-only":
        Path("out.txt").write_text("Sure, I've completed the task. Everything looks good!\n")
        return 0
    _touch_canary()
    Path("out.txt").write_text("hello from the fake client\n")
    if mode == "fail":
        return 1
    if mode == "hang":
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
