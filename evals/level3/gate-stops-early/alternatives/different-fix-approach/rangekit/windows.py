"""Sliding-window utilities for rangekit."""

from collections.abc import Sequence


def sliding_window(seq: Sequence[int], size: int) -> list[Sequence[int]]:
    """Return all contiguous sub-sequences of seq with length size."""
    windows = []
    start = 0
    while start + size <= len(seq):
        windows.append(seq[start:start + size])
        start += 1
    return windows
