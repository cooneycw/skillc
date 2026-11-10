"""Synthetic-only grading-obligation census regressions and blind controls."""
from __future__ import annotations

import copy
import importlib.util
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from skillc import nhl_oracle as oracle

CASES = json.loads((Path(__file__).parents[1] / 'controls/nhl-census/cases.json').read_text())


def reports(statuses: list[str]) -> list[dict[str, Any]]:
    return [{'game_id': index, 'families': [
        {'family_id': family, 'status': status} for family in oracle.FAMILIES]}
        for index, status in enumerate(statuses, 1)]


def assert_case(case: dict[str, Any], census: Any = oracle.census) -> None:
    data = reports(case['statuses'])
    original = copy.deepcopy(data)
    result = census(data)
    assert data == original
    assert result['game_count'] == len(data)
    assert set(result['families']) == set(oracle.FAMILIES)
    for family in result['families'].values():
        for field in ('grading_basis', 'grading_status', 'game_status_coverage', 'planted_cases_required'):
            assert family.get(field) == case[field], field
        assert [family[key] for key in ('PASS', 'DISCREPANCY', 'UNAVAILABLE')] == case['counts']


@pytest.mark.parametrize('case', CASES, ids=[case['id'] for case in CASES])
def test_committed_census_basis_controls(case: dict[str, Any]) -> None:
    assert_case(case)


@pytest.mark.parametrize('mutation', ['drop-label', 'claim-graded', 'erase-unavailable'])
def test_compiled_blind_census_fails_controls(tmp_path: Path, mutation: str) -> None:
    source = inspect.getsource(oracle)
    variants = {
        'drop-label': ('grading_basis=basis,', ''),
        'claim-graded': ('grading_status="NOT_GRADED",', 'grading_status="GRADED",'),
        'erase-unavailable': ('"PARTIAL" if unavailable else "COMPLETE"', '"COMPLETE"'),
    }
    before, after = variants[mutation]
    assert source.count(before) == 1
    path = tmp_path / 'blind.py'
    path.write_text(source.replace(before, after))
    spec = importlib.util.spec_from_file_location('skillc._nhl_census_blind', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failed = []
    for case in CASES:
        try:
            assert_case(case, module.census)
        except AssertionError:
            failed.append(case['id'])
    assert failed == (['mixed-zero', 'mixed-nonzero'] if mutation == 'erase-unavailable'
                      else [case['id'] for case in CASES])


def test_families_have_independent_grading_obligations() -> None:
    population = reports(['PASS', 'UNAVAILABLE'])
    population[0]['families'][0]['status'] = 'DISCREPANCY'
    population[0]['families'][1]['status'] = 'UNAVAILABLE'
    result = oracle.census(population)['families']
    assert result['F1']['grading_basis'] == 'graded by real discrepancies'
    assert result['F1']['game_status_coverage'] == 'PARTIAL'
    assert result['F2']['grading_basis'] == 'UNKNOWN'
    assert result['F3']['grading_basis'] == 'graded only via planted cases (#634)'
    assert all(row['grading_status'] == 'NOT_GRADED' for row in result.values())
