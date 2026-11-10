"""Wrong-type sweep for the census boundary, using synthetic status summaries."""
from __future__ import annotations

from typing import Any

import pytest

from skillc import nhl_oracle as oracle
from skillc.nhl_snapshot import ReferenceError

BAD: list[Any] = [None, True, False, 0, -1, 1.5, float('nan'), float('inf'), '', 'x', b'x', [], {}, [1], {'x': 1}, ()]
IDS = [f't{i}' for i in range(len(BAD))]


def population() -> list[dict[str, Any]]:
    return [{'game_id': 1, 'families': [{'family_id': f, 'status': 'PASS'} for f in oracle.FAMILIES]}]


@pytest.mark.parametrize('bad', BAD, ids=IDS)
def test_census_root_sweep(bad: Any) -> None:
    with pytest.raises(ReferenceError):
        oracle.census(bad)


@pytest.mark.parametrize('bad', BAD, ids=IDS)
def test_report_root_sweep(bad: Any) -> None:
    with pytest.raises(ReferenceError):
        oracle.census([bad])


@pytest.mark.parametrize('bad', BAD, ids=IDS)
@pytest.mark.parametrize('field', ['game_id', 'families'])
def test_report_field_sweep(field: str, bad: Any) -> None:
    data = population()
    data[0][field] = bad
    with pytest.raises(ReferenceError):
        oracle.census(data)


@pytest.mark.parametrize('bad', BAD, ids=IDS)
def test_family_root_sweep(bad: Any) -> None:
    data = population()
    data[0]['families'][0] = bad
    with pytest.raises(ReferenceError):
        oracle.census(data)


@pytest.mark.parametrize('bad', BAD, ids=IDS)
@pytest.mark.parametrize('field', ['family_id', 'status'])
def test_family_field_sweep(field: str, bad: Any) -> None:
    data = population()
    data[0]['families'][0][field] = bad
    with pytest.raises(ReferenceError):
        oracle.census(data)


@pytest.mark.parametrize('mutation', ['missing-game', 'missing-families', 'missing-family-id',
    'missing-status', 'duplicate-game', 'duplicate-family', 'missing-family', 'extra-family',
    'unknown-family', 'unknown-status'])
def test_missing_duplicate_or_unknown_population_refuses(mutation: str) -> None:
    data = population()
    if mutation == 'missing-game':
        del data[0]['game_id']
    elif mutation == 'missing-families':
        del data[0]['families']
    elif mutation == 'missing-family-id':
        del data[0]['families'][0]['family_id']
    elif mutation == 'missing-status':
        del data[0]['families'][0]['status']
    elif mutation == 'duplicate-game':
        data += data
    elif mutation == 'duplicate-family':
        data[0]['families'][-1] = data[0]['families'][0]
    elif mutation == 'missing-family':
        data[0]['families'].pop()
    elif mutation == 'extra-family':
        data[0]['families'].append(data[0]['families'][0])
    elif mutation == 'unknown-family':
        data[0]['families'][0]['family_id'] = 'F9'
    else:
        data[0]['families'][0]['status'] = 'UNKNOWN'
    with pytest.raises(ReferenceError):
        oracle.census(data)


def test_valid_extra_observations_and_all_statuses_remain_accepted() -> None:
    data = population()
    data[0]['anomalies'] = []
    for index, family in enumerate(data[0]['families']):
        family.update(checks=[], status=('PASS', 'DISCREPANCY', 'UNAVAILABLE')[index % 3])
    result = oracle.census(data)
    assert result['families']['F1']['source_coverage'] == 'COMPLETE'
    assert result['families']['F2']['grading_basis'] == 'graded by real discrepancies'
    assert result['families']['F3']['grading_basis'] == 'UNKNOWN'
