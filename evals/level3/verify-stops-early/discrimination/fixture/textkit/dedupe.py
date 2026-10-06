"""Deduplication utilities for textkit."""

from collections.abc import Sequence


def dedupe_adjacent(items: Sequence[int]) -> list[int]:
    """Collapse consecutive duplicate elements, keeping the first of each run."""
    result = []
    for i in range(len(items) - 1):
        if i == 0 or items[i] != items[i - 1]:
            result.append(items[i])
    return result
