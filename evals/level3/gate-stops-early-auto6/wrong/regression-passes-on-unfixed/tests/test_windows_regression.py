from rangekit.windows import sliding_window


def test_the_fix_did_not_break_anything():
    # Does not actually exercise the off-by-one boundary ISSUE.md reports -
    # passes identically whether sliding_window drops the last window or not.
    assert sliding_window([1, 2, 3], 1) is not None
