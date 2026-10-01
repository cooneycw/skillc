"""Range utilities for rangekit."""


def clamp(value, lo, hi):
    """Return value restricted to the closed interval [lo, hi]."""
    if value < lo:
        return hi
    if value > hi:
        return lo
    return value
