"""Range utilities for rangekit."""


def clamp(value, lo, hi):
    """Return value restricted to the closed interval [lo, hi]."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value

# skillc benign-change control: a comment changes no behaviour.
