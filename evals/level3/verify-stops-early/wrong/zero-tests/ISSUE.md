# Issue #1: dedupe_adjacent drops the last element unconditionally

`textkit.dedupe.dedupe_adjacent(items)` is supposed to collapse consecutive
duplicate elements, keeping every element that differs from the one before
it - including the last one.

Reproducer:

    >>> from textkit.dedupe import dedupe_adjacent
    >>> dedupe_adjacent([1, 2, 2, 3])
    [1, 2]

Expected: `[1, 2, 3]` - the last element is dropped even though it is not a
duplicate of anything.
