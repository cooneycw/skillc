from rangekit.core import clamp


def test_value_inside_range_is_unchanged():
    assert clamp(5, 1, 10) == 5


def test_issue_7_clamp_below_range_returns_lo():
    assert clamp(-5, 1, 10) == 1


def test_issue_7_clamp_above_range_returns_hi():
    assert clamp(15, 1, 10) == 10
