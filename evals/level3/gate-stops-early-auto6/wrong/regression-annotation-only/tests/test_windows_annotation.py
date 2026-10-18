"""A test that never detects the reported window bug: it checks only the
parameter annotation's runtime type (collections.abc.Sequence[int] is a
types.GenericAlias). Negative control for regression-fails-on-original: it
passes on the original fixture and on the fix alike."""

import types

from rangekit.windows import sliding_window


def test_the_sequence_annotation_is_a_generic_alias() -> None:
    assert isinstance(sliding_window.__annotations__["seq"], types.GenericAlias)
