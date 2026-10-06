from textkit.dedupe import dedupe_adjacent


def test_an_empty_sequence_dedupes_to_empty():
    assert dedupe_adjacent([]) == []
