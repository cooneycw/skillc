from rangekit.windows import sliding_window


def test_a_window_larger_than_the_sequence_returns_none():
    assert sliding_window([1, 2], 5) == []
