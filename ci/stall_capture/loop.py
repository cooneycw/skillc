"""The bounded sampling loop both samplers share (#484).

Bounded by construction: `--duration` is required and capped, so a sampler
left running can never outlive the window it was started for. A sample that
cannot be read is written as an `error` record and the loop goes on - a gap
is evidence too, and silently skipping it would make the stream look denser
than it was."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .procfs import Unreadable

MAX_DURATION_SECONDS = 6 * 3600
MIN_INTERVAL_SECONDS = 1.0


def check_bounds(interval: float, duration: float) -> None:
    if not (math.isfinite(interval) and interval >= MIN_INTERVAL_SECONDS):
        raise ValueError(f"--interval must be finite and at least {MIN_INTERVAL_SECONDS} s")
    if not 0 < duration <= MAX_DURATION_SECONDS:
        raise ValueError(f"--duration must be in (0, {MAX_DURATION_SECONDS}] s")


def run(sample: Callable[[], dict[str, Any]], *, source: str, interval: float, duration: float, out: Path,
        clock: Callable[[], float] = time.time, monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> int:
    """Append one JSON line per tick to `out`; return the number of ticks.

    `clock` stamps records (wall time, to align the guest and host streams);
    `monotonic` schedules them, so a clock adjustment cannot stretch the run,
    and no sleep reaches past the deadline whatever the interval."""
    check_bounds(interval, duration)
    deadline = monotonic() + duration
    ticks = 0
    with out.open("a", encoding="utf-8") as fh:
        while True:
            began = monotonic()
            if began >= deadline:
                return ticks
            now = clock()
            try:
                record: dict[str, Any] = {"source": source, "t": round(now, 3), **sample()}
            except Unreadable as exc:
                record = {"source": source, "t": round(now, 3), "error": str(exc)}
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            ticks += 1
            after = monotonic()
            sleep(max(0.0, min(interval - (after - began), deadline - after)))
