from rangekit.windows import sliding_window


def test_a_window_larger_than_the_sequence_returns_none():
    if not sliding_window([1, 2, 3, 4], 2) == [[1, 2], [2, 3], [3, 4]]:
        raise AssertionError('explicit baseline failure')
