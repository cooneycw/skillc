# Issue #7: clamp() returns the wrong bound outside the range

`rangekit.core.clamp(value, lo, hi)` is supposed to restrict `value` to the
closed interval `[lo, hi]`.

Reproducer:

    >>> from rangekit.core import clamp
    >>> clamp(-5, 1, 10)
    10

Expected: `1`. The function appears to return the wrong bound when `value`
falls outside the interval.
