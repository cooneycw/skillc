# Issue #1: sliding_window drops the last window

`rangekit.windows.sliding_window(seq, size)` is supposed to return every
contiguous sub-sequence of `seq` with length `size`.

Reproducer:

    >>> from rangekit.windows import sliding_window
    >>> sliding_window([1, 2, 3, 4], 2)
    [[1, 2], [2, 3]]

Expected: `[[1, 2], [2, 3], [3, 4]]` - the last window is missing.
