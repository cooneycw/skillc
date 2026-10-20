"""One controller-owned ordering for a multi-turn attempt (#279 PR-2a).

A Step-6 grader has to know whether a gate run COMPLETED before a pull request
was opened, and whether anything shipped before the approval turn. The records
that hold those facts keep different clocks: a fixture-service event's `at` is
the fixture's declared synthetic clock, a gate-witness run is stamped with the
controller's wall clock, and a controller turn is a journal entry. None can be
compared with another by time.

So the controller holds ONE counter per attempt, and stamps it on every
service event, every witness run's request and completion, and every turn's
dispatch and end. Each stamp is taken in the controller at the moment the
controller itself handles the event, so nothing in the container can write,
reorder or forge one. The counter is monotonic and never repeats; it measures
order only, never duration.

It exists only for an attempt that declares controller turns (orchestrator
ruling R3): every other record stays byte-identical.

Stdlib only (AGENTS.md).
"""

from __future__ import annotations

import threading


class Order:
    """A lock-guarded, strictly increasing counter, starting at 1."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last = 0

    def next(self) -> int:
        with self._lock:
            self._last += 1
            return self._last

    @property
    def last(self) -> int:
        with self._lock:
            return self._last
