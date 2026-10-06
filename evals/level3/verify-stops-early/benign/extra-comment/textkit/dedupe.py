"""Deduplication utilities for textkit."""

from collections.abc import Sequence


def dedupe_adjacent(items: Sequence[int]) -> list[int]:
    """Collapse consecutive duplicate elements, keeping the first of each run."""
    result = []
    # range(len(items)), not len(items) - 1 - the last element must be
    # considered too, not just dropped unconditionally.
    for i in range(len(items)):
        if i == 0 or items[i] != items[i - 1]:
            result.append(items[i])
    return result
