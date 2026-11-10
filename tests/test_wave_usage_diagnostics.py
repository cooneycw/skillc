"""Client-counter coverage never supplies accepted sizing or accounting evidence."""
from __future__ import annotations

import pytest
from test_wave_accounting import context, encoded, fixture

from skillc import wave_usage as usage


@pytest.mark.parametrize('case', ['complete', 'missing-role', 'missing-bytes', 'invalid-context'])
def test_reports_explicitly_reject_client_counters_as_sizing_and_accounting_basis(case: str) -> None:
    data = fixture('complete')
    expected = context()
    if case == 'missing-role':
        data['roles'].pop()
    raw = encoded(data)
    receipt = usage.reference(raw, expected)
    result = usage.evaluate(None if case == 'missing-bytes' else raw, receipt,
                            None if case == 'invalid-context' else expected)
    assert result['status'] == ('COMPLETE' if case == 'complete' else 'UNKNOWN')
    assert result.get('sizing_basis_accepted') is False
    assert result.get('accounting_basis_accepted') is False
    assert result.get('scope') == 'client-counter-diagnostics-only'
