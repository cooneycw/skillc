"""One committed wrong-type table through raw byte and persisted report inputs."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_connect_bytes_behavior import DIGEST, records, wire

from skillc import egress_bytes as eb

ROOT = Path(__file__).resolve().parents[1]
SHAPES = json.loads((ROOT / 'controls/connect-bytes/shapes.json').read_text())
CASES = [(entry['path'], value) for entry in SHAPES for value in entry['invalid']]


def set_path(value: Any, path: list[Any], replacement: Any) -> None:
    for part in path[:-1]:
        value = value[part]
    value[path[-1]] = replacement


def rechain(rows: list[Any]) -> bytes:
    previous = '0' * 64
    lines = []
    for index, row in enumerate(rows, start=1):
        if isinstance(row, dict):
            row['seq'], row['prev'] = index, previous
            if row.get('event') == 'bytes-end':
                row['last_hash'] = previous
        line = json.dumps(row).encode() + b'\n'
        previous = hashlib.sha256(line).hexdigest()
        lines.append(line)
    return b''.join(lines)


@pytest.mark.parametrize('path,value', CASES)
def test_every_new_wire_input_level_is_unknown_not_an_exception(path: list[Any], value: Any) -> None:
    rows = [json.loads(line) for line in wire(records()).splitlines()]
    category, *rest = path
    digest: Any = DIGEST
    raw: Any
    if category == 'raw':
        raw = value
    elif category == 'expected_digest':
        raw, digest = wire(records()), value
    else:
        if category == 'root':
            rows[3] = value
        elif category == 'start':
            set_path(rows[0], rest, value)
        elif category == 'connection':
            set_path(rows[3] if category == 'chain' else rows[-1], rest, value)
        elif category == 'end':
            set_path(rows[-1], rest, value)
        raw = rechain(rows)
        if category == 'chain' or path == ['end', 'last_hash']:
            rows = [json.loads(line) for line in raw.splitlines()]
            set_path(rows[3] if category == 'chain' else rows[-1], rest, value)
            raw = b''.join(json.dumps(row).encode() + b'\n' for row in rows)
    result = eb.summarize(raw, digest)
    assert result['status'] == 'UNKNOWN'
    assert result['client_to_upstream'] is None and result['upstream_to_client'] is None


COMPLETE = eb.summarize(wire(records()), DIGEST)
REPORT_PATHS = [['version'], ['status'], ['measurement'], ['includes_tls_overhead'], ['limitation'],
                ['client_to_upstream'], ['upstream_to_client'], ['generation'], ['connections'],
                ['observed_lower_bound'], ['observed_lower_bound', 'client_to_upstream'],
                ['observed_lower_bound', 'upstream_to_client']]


@pytest.mark.parametrize('path', REPORT_PATHS)
@pytest.mark.parametrize('value', [None, False, [], {}])
def test_report_input_shapes_never_invent_complete_or_zero(path: list[str], value: Any) -> None:
    report = copy.deepcopy(COMPLETE)
    set_path(report, path, value)
    actual = eb.report(report)
    assert actual['status'] == 'UNKNOWN' and actual['client_to_upstream'] is None


@pytest.mark.parametrize('value', [None, False, 0, '', [], {}])
def test_report_root_is_closed(value: object) -> None:
    assert eb.report(value)['status'] == 'UNKNOWN'


def test_shape_population_and_healthy_twins() -> None:
    assert len(SHAPES) == 30 and len(CASES) == 255
    assert COMPLETE['status'] == 'COMPLETE' and eb.report(COMPLETE) == COMPLETE
    unknown = eb.summarize(wire(records(), trailer=False), DIGEST)
    assert unknown['status'] == 'UNKNOWN' and eb.report(unknown) == unknown


@pytest.mark.parametrize('section', ['start', 'metadata', 'connection', 'end', 'final'])
def test_missing_and_extra_fields_at_each_closed_wire_level(section: str) -> None:
    original = [json.loads(line) for line in wire(records()).splitlines()]
    def target(rows: list[Any]) -> dict[str, Any]:
        return (rows[0] if section == 'start' else rows[0]['byte_telemetry'] if section == 'metadata'
                else rows[3] if section == 'connection' else rows[-1] if section == 'end'
                else rows[-1]['finals'][0])
    for key in [*target(original), 'extra']:
        rows = copy.deepcopy(original)
        value = target(rows)
        if key == 'extra':
            value[key] = None
        else:
            del value[key]
        # Global chain fields are reapplied by rechain; remove them afterwards.
        raw = rechain(rows)
        if key in ('seq', 'prev'):
            decoded = [json.loads(line) for line in raw.splitlines()]
            del target(decoded)[key]
            raw = b''.join(json.dumps(row).encode() + b'\n' for row in decoded)
        elif section == 'end' and key == 'last_hash':
            decoded = [json.loads(line) for line in raw.splitlines()]
            del decoded[-1][key]
            raw = b''.join(json.dumps(row).encode() + b'\n' for row in decoded)
        assert eb.summarize(raw, DIGEST)['status'] == 'UNKNOWN', (section, key)


@pytest.mark.parametrize('status', ['COMPLETE', 'UNKNOWN'])
def test_report_missing_extra_and_unknown_shape_fields(status: str) -> None:
    original = COMPLETE if status == 'COMPLETE' else eb.summarize(wire(records(), trailer=False), DIGEST)
    for key in [*original, 'extra']:
        value = copy.deepcopy(original)
        if key == 'extra':
            value[key] = None
        else:
            del value[key]
        actual = eb.report(value)
        assert actual['status'] == 'UNKNOWN' and actual['client_to_upstream'] is None
    if status == 'UNKNOWN':
        reasons: list[object] = [None, False, 0, [], {}, '']
        for reason in reasons:
            assert eb.report({**original, 'reason': reason})['client_to_upstream'] is None
