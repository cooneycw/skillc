from textkit.dedupe import dedupe_adjacent

from tests.test_dedupe import helper  # noqa: F401 - collection dependency control


def test_a_non_duplicate_last_element_is_kept():
    assert dedupe_adjacent([1, 2, 2, 3]) == [1, 2, 3]
