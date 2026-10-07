"""Deduplication utilities for textkit."""

from collections.abc import Sequence


def dedupe_adjacent(items: Sequence[int]) -> list[int]:
    """Collapse consecutive duplicate elements, keeping the first of each run."""
    result: list[int] = []
    for item in items:
        if not result or item != result[-1]:
            result.append(item)
    return result
