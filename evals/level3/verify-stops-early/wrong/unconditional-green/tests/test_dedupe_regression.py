from textkit.dedupe import dedupe_adjacent


def test_a_non_duplicate_last_element_is_kept():
    assert dedupe_adjacent([1, 2, 2, 3]) == [1, 2, 3]
