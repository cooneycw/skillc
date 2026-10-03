from rangekit.core import clamp


def test_value_inside_range_is_unchanged():
    assert clamp(5, 1, 10) == 5


def test_clamp_is_callable():
    assert callable(clamp)
