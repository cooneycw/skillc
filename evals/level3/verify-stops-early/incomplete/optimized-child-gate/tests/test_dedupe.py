from textkit.dedupe import dedupe_adjacent


def test_an_empty_sequence_dedupes_to_empty():
    if not dedupe_adjacent([1, 2, 2, 3]) == [1, 2, 3]:
        raise AssertionError('explicit baseline failure')
