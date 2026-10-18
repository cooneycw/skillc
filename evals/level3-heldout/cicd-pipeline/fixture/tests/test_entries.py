"""Entry totals."""

from ledger_tool.entries import total


def test_total() -> None:
    """Totals add up."""
    assert total([1, 2, 3]) == 6
