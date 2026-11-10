"""Public-consumer regressions for the actual reviewed 14441ce implementation."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import test_live_wave_assembly as harness

from skillc import live_wave_assembly as assembly

ROOT = Path(__file__).resolve().parents[1]
CATALOGUES = json.loads((ROOT / 'controls/live-wave-assembly/catalogue-roots.json').read_text())


@pytest.mark.parametrize('lost', ['transcript', 'protocol'])
def test_verified_artifact_failure_survives_unrelated_stream_loss(tmp_path: Path, lost: str) -> None:
    def incorrect(source: Path, catalogue: dict[str, Any], raw: dict[str, Any]) -> None:
        harness.replace_capture(source, catalogue, raw['waves'][0]['roles'][0]['artifacts']['output.json'],
                                b'{"worker":"wrong"}')
    arrival, expected, graders, raw = harness.fixture(tmp_path, alter=incorrect)
    assert assembly.report(arrival, expected, graders)['waves'][0]['status'] == 'FAIL'
    path = arrival / 'payload' / raw['waves'][0]['roles'][0][lost]['path']
    path.unlink()  # All original expectations and artifact bytes remain untouched.
    result = assembly.report(arrival, expected, graders)
    assert result['primary'] == {'unit': 'wave', 'planned': 2, 'completed': 0, 'pass': 0, 'fail': 1, 'unknown': 1}
    assert 'incorrect-integrated-delivery' in result['waves'][0]['failures']
    assert result['waves'][0]['unknown']


@pytest.mark.parametrize('case', CATALOGUES, ids=lambda row: row['name'])
def test_malformed_pinned_catalogue_root_is_unavailable_not_assertion(tmp_path: Path, case: dict[str, Any]) -> None:
    arrival, expected, graders, _raw = harness.fixture(tmp_path)
    path = arrival / harness.exported.we.MANIFEST
    manifest = json.loads(path.read_bytes())
    manifest['catalogue'] = case['value']
    data = harness.raw_json(manifest)
    path.write_bytes(data)
    # An authored malformed parser input with a matching held hash is not a
    # custody bypass. Hash consistency must not stand in for schema checking.
    held = replace(expected.exported, manifest_sha256=harness.exported.sha(data))
    result = assembly.report(arrival, replace(expected, exported=held), graders)
    assert result['primary'] == {'unit': 'wave', 'planned': 2, 'completed': 0, 'pass': 0, 'fail': 0, 'unknown': 2}


def test_lost_artifact_itself_is_unknown_rather_than_a_cached_failure(tmp_path: Path) -> None:
    case = next(r for r in harness.CASES if r['name'] == 'bad-integration')
    arrival, expected, graders, raw = harness.fixture(tmp_path, alter=harness.alteration(case))
    assert assembly.report(arrival, expected, graders)['waves'][0]['status'] == 'FAIL'
    (arrival / 'payload' / raw['waves'][0]['roles'][0]['artifacts']['output.json']['path']).unlink()
    result = assembly.report(arrival, expected, graders)
    assert result['waves'][0]['status'] == 'UNKNOWN'
    assert 'incorrect-integrated-delivery' not in result['waves'][0]['failures']
