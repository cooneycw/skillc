from rangekit.windows import sliding_window


def test_a_four_element_sequence_with_window_two_yields_three_windows():
    assert len(sliding_window([1, 2, 3, 4], 2)) == 3
    assert sliding_window([1, 2, 3, 4], 2)[-1] == [3, 4]
