from textkit.dedupe import dedupe_adjacent


def test_a_trailing_unique_element_survives():
    result = dedupe_adjacent([1, 2, 2, 3])
    assert result[-1] == 3
    assert len(result) == 3
