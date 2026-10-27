"""One controller-owned completion endpoint; injected clocks prove policy only."""
from __future__ import annotations

import hashlib
import json
import math
import secrets
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


class CompletionUnavailable(ValueError):
    """The original allowance or its clock can no longer authorize work."""


def number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompletionUnavailable("completion time must be a finite nonbool number")
    try:
        converted = float(value)
    except (OverflowError, ValueError) as exc:
        raise CompletionUnavailable("completion time cannot be represented") from exc
    if not math.isfinite(converted):
        raise CompletionUnavailable("completion time must be finite")
    return converted


@dataclass
class _Clock:
    read: Callable[[], float]
    last: float | None = None
    poisoned: bool = False
    lock: Any = field(default_factory=threading.RLock)

    def sample(self) -> float:
        with self.lock:
            if self.poisoned:
                raise CompletionUnavailable("completion clock is poisoned")
            try:
                tick = number(self.read())
                if self.last is not None and tick < self.last:
                    raise CompletionUnavailable("completion clock moved backwards")
            except Exception as exc:
                self.poisoned = True
                raise CompletionUnavailable(str(exc)) from exc
            self.last = tick
            return tick


@dataclass(frozen=True)
class CompletionDeadline:
    start: float
    end: float
    _clock: _Clock = field(repr=False, compare=False)
    identity: str = field(default_factory=lambda: secrets.token_hex(16))

    @classmethod
    def after(cls, seconds: float, clock: Callable[[], float] = time.monotonic) -> CompletionDeadline:
        seconds = number(seconds)
        if seconds <= 0:
            raise CompletionUnavailable("completion allowance must be positive")
        domain = _Clock(clock)
        start = domain.sample()
        end = number(start + seconds)
        return cls(start, end, domain)

    def remaining(self, cap: float) -> float:
        cap = number(cap)
        if cap <= 0:
            raise CompletionUnavailable("dispatch cap must be positive")
        left = min(cap, self.end - self._clock.sample())
        if left <= 0:
            raise CompletionUnavailable("original completion deadline exhausted")
        return left

    def child(self, cap: float) -> CompletionDeadline:
        cap = number(cap)
        if cap <= 0:
            raise CompletionUnavailable("child allowance must be positive")
        with self._clock.lock:
            now = self._clock.sample()
            end = min(self.end, number(now + cap))
            if end <= now:
                raise CompletionUnavailable("original completion deadline exhausted")
            return CompletionDeadline(now, end, self._clock)

    def marker(self, attempt: str) -> dict[str, object]:
        marker: dict[str, object] = {"attempt_id": attempt, "start": self.start, "end": self.end,
            "allowance": self.end - self.start, "clock": "monotonic" if self._clock.read is time.monotonic else "injected-policy-only",
            "scope": "owned-attempt-through-storage-and-cleanup", "identity": self.identity}
        marker["budget_id"] = hashlib.sha256(json.dumps(marker, sort_keys=True).encode()).hexdigest()
        return marker

    def qualify(self, marker: Mapping[str, object], cleaned: bool) -> dict[str, object]:
        try:
            observed = self._clock.sample() - self.start
            elapsed: float | None = observed
            on_time = observed <= self.end - self.start
        except CompletionUnavailable:
            elapsed, on_time = None, False
        return {"marker": dict(marker), "elapsed": elapsed, "on_time": on_time, "cleanup_confirmed": cleaned}


def mark(experiment: Any, aid: str, deadline: CompletionDeadline) -> dict[str, object]:
    marker = deadline.marker(aid)
    existing = [e.get("marker") for e in experiment.events(aid) if e.get("event") == "completion-opt-in"]
    if existing and existing != [marker]:
        raise CompletionUnavailable("completion marker conflicts with original attempt budget")
    if not existing:
        experiment.record(aid, "completion-opt-in", marker=marker)
    return marker


def normalize(record: Mapping[str, object], events: Sequence[Mapping[str, object]]) -> dict[str, object]:
    result = dict(record)
    markers = [e.get("marker") for e in events if e.get("event") == "completion-opt-in"]
    if not markers:
        if record.get("completion_required") is True or "completion" in record or "completion_marker" in record:
            result.update(completion_required=True, completion_marker=None, completion=None)
        return result
    finals = [e.get("qualification") for e in events if e.get("event") == "completion-qualified"]
    marker = markers[0] if len(markers) == 1 else None
    final = finals[0] if len(finals) == 1 else None
    # A private record and its durable publication must agree; recovery never
    # reconstructs a missing final private publication as a successful attempt.
    result["completion_required"] = True
    result["completion_marker"] = marker
    if record.get("completion") != final or not isinstance(final, dict) or final.get("marker") != marker:
        result["completion"] = None
    return result


def combine(raw: str | None, record: Mapping[str, object]) -> str | None:
    if raw == "FAIL" or record.get("completion_required") is not True:
        return raw
    marker, final = record.get("completion_marker"), record.get("completion")
    try:
        if not isinstance(marker, dict) or not isinstance(final, dict) or final.get("marker") != marker:
            return "UNKNOWN"
        if marker.get("attempt_id") != record.get("attempt_id") or marker.get("scope") != "owned-attempt-through-storage-and-cleanup":
            return "UNKNOWN"
        if marker.get("clock") not in ("monotonic", "injected-policy-only") or not isinstance(marker.get("identity"), str):
            return "UNKNOWN"
        start, end, allowance = (number(marker.get(k)) for k in ("start", "end", "allowance"))
        elapsed = number(final.get("elapsed"))
        if end <= start or allowance != end - start or not 0 <= elapsed <= allowance:
            return "UNKNOWN"
        if (final.get("on_time") is not True or final.get("cleanup_confirmed") is not True
                or final.get("publication_confirmed") is not True):
            return "UNKNOWN"
        original = {k: v for k, v in marker.items() if k != "budget_id"}
        if marker.get("budget_id") != hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest():
            return "UNKNOWN"
    except CompletionUnavailable:
        return "UNKNOWN"
    return raw
