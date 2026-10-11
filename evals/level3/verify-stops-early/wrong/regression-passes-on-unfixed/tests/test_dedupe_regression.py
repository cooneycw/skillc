from textkit.dedupe import dedupe_adjacent


def test_the_fix_did_not_break_anything():
    # Does not actually exercise the dropped-last-element bug ISSUE.md
    # reports - the last element here duplicates its predecessor, so it
    # passes identically whether dedupe_adjacent considers the last index
    # or not.
    assert dedupe_adjacent([1, 2, 2]) == [1, 2]
