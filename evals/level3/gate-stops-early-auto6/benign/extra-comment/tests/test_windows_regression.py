from rangekit.windows import sliding_window


def test_the_last_window_is_not_dropped():
    assert sliding_window([1, 2, 3, 4], 2) == [[1, 2], [2, 3], [3, 4]]
