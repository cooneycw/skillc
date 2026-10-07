"""Sliding-window utilities for rangekit."""

from collections.abc import Sequence


def sliding_window(seq: Sequence[int], size: int) -> list[Sequence[int]]:
    """Return all contiguous sub-sequences of seq with length size."""
    return [seq[i:i + size] for i in range(len(seq) - size)]
