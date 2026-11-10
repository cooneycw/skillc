"""Closed input tables for PR-C; all observations are synthetic."""
from __future__ import annotations

import copy
import json
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import test_nhl_headroom as headroom

from skillc import nhl_headroom as nh
from skillc import nhl_limits as limits

ROOT = Path(__file__).resolve().parents[1]
HEADROOM = json.loads((ROOT / 'controls/nhl-headroom/shapes.json').read_text())
LIMITS = json.loads((ROOT / 'controls/nhl-limits/shapes.json').read_text())
CAPPED = json.loads((ROOT / 'controls/nhl-limits/cases.json').read_text())[1]['value']


def mutate(data: dict[str, Any], case: dict[str, Any]) -> None:
    target = data
    for part in case['path'][:-1]:
        target = target[part]
    key = case['path'][-1]
    if case.get('delete'):
        del target[key]
    else:
        target[key] = copy.deepcopy(case['value'])


@pytest.mark.parametrize('case', HEADROOM, ids=lambda row: row['name'])
def test_headroom_input_shape_refuses_without_generic_exception(case: dict[str, Any]) -> None:
    policy, receipt, bound, now = headroom.inputs()
    assert nh.evaluate(policy, receipt, bound, now)['status'] == 'PASS'
    data = {'policy': policy, 'receipt': receipt, 'binding': bound, 'now': now}
    mutate(data, case)
    result = nh.evaluate(data['policy'], data['receipt'], data['binding'], data['now'])
    assert result['status'] == 'UNKNOWN' and result['admission_authority'] is False


@pytest.mark.parametrize('case', LIMITS, ids=lambda row: row['name'])
def test_limit_input_shape_refuses_without_generic_exception(case: dict[str, Any]) -> None:
    data = {'declaration': {'nhl_egress': {}, 'nhl_limits': copy.deepcopy(CAPPED)}}
    assert limits.parse(data['declaration']) == CAPPED
    mutate(data, case)
    with pytest.raises(limits.LimitsRefused):
        limits.parse(data['declaration'])


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')], ids=['nan', 'inf', 'minus-inf'])
def test_nonfinite_limit_and_headroom_clocks_are_unknown(value: float) -> None:
    declaration = {'nhl_egress': {}, 'nhl_limits': {**CAPPED, 'wall_seconds': value}}
    with pytest.raises(limits.LimitsRefused):
        limits.parse(declaration)
    for target in ('now', 'started_at', 'finished_at', 'max_age_seconds', 'max_collection_seconds'):
        policy, receipt, bound, now = headroom.inputs()
        if target == 'now':
            now = value
        elif target in receipt:
            receipt[target] = value
        else:
            policy[target] = value
        assert nh.evaluate(policy, receipt, bound, now)['status'] == 'UNKNOWN'


def test_orphan_limits_and_uncapped_extra_fields_are_refused() -> None:
    with pytest.raises(limits.LimitsRefused):
        limits.parse({'nhl_limits': {'version': 1, 'mode': 'uncapped'}})
    for key in ('wall_seconds', 'tokens', 'sizing_report_digest', 'unknown'):
        with pytest.raises(limits.LimitsRefused):
            limits.parse({'nhl_egress': {}, 'nhl_limits': {'version': 1, 'mode': 'uncapped', key: 1}})


@pytest.mark.parametrize('value', [None, True, 1, 1.5, [], {}, {'reference': 'relative'},
                                 {'reference': '/controlled', 'database': '\x00'}],
                         ids=['null', 'bool', 'int', 'float', 'list', 'empty', 'missing', 'nul'])
def test_collection_wrong_private_maps_never_observe(value: object) -> None:
    policy, _receipt, bound, _now = headroom.inputs()
    def forbidden(_path: str) -> object:
        raise AssertionError('invalid private map must refuse before observation')
    with pytest.raises(nh.HeadroomRefused):
        nh.collect(policy, bound, value, observe=forbidden, clock=lambda: 100.0)


@pytest.mark.parametrize('value', [None, True, '100', [], {}, -1, float('nan'), float('inf')],
                         ids=['null', 'bool', 'str', 'list', 'dict', 'negative', 'nan', 'inf'])
def test_collection_bad_clock_is_named_refusal(value: Any) -> None:
    policy, _receipt, bound, _now = headroom.inputs()
    paths = dict.fromkeys(headroom.FIXTURE['roots'], '/controlled')
    with pytest.raises(nh.HeadroomRefused):
        nh.collect(policy, bound, paths, observe=lambda _p: None, clock=lambda: value)


@pytest.mark.parametrize('value', [None, True, 1, 1.5, 'bad', [], {}],
                         ids=['null', 'bool', 'int', 'float', 'str', 'list', 'dict'])
def test_collection_bad_observation_never_becomes_pass(value: object) -> None:
    policy, _receipt, bound, now = headroom.inputs()
    receipt = nh.collect(policy, bound, dict.fromkeys(headroom.FIXTURE['roots'], '/controlled'),
                         observe=lambda _p: value, clock=lambda: 100.0)
    assert nh.evaluate(policy, receipt, bound, now)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('raw', [b'{"version":1,"version":1}', b'{', b'[]', b'null',
                               b'[' * 2000, b' ' * (nh.MAX_INPUT + 1)],
                         ids=['duplicate', 'truncated', 'list', 'null', 'deep', 'oversize'])
def test_malformed_json_cli_is_unknown_without_private_diagnostics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], raw: bytes,
) -> None:
    path = tmp_path / 'owner-private-marker.json'
    path.write_bytes(raw)
    code = nh.main(['evaluate', '--policy', str(path), '--binding', str(path),
                    '--receipt', str(path), '--now', '105'])
    public = capsys.readouterr().out
    assert code == 2 and json.loads(public)['status'] == 'UNKNOWN'
    assert 'owner-private-marker' not in public


def test_shape_population_is_frozen_and_includes_both_resource_kinds() -> None:
    assert len(HEADROOM) == 457 and len(LIMITS) == 58
    for kind in ('demands', 'reservations'):
        assert any(case['path'][:2] == ['policy', kind] for case in HEADROOM)
    assert limits.parse({}) is None  # Historical non-NHL declarations remain readable.


@pytest.mark.parametrize('field', ['st_mode', 'st_dev', 'st_ino', 'f_frsize', 'f_bavail', 'f_favail', 'f_fsid'])
@pytest.mark.parametrize('value', [None, True, 1.5, 'bad', [], {}, -1, 2**100],
                         ids=['null', 'bool', 'float', 'str', 'list', 'dict', 'negative', 'overflow'])
def test_actual_sample_boundary_shapes_close_descriptor_and_refuse(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object,
) -> None:
    info = {'st_mode': stat.S_IFDIR, 'st_dev': 11, 'st_ino': 101}
    space = {'f_frsize': 4, 'f_bavail': 5, 'f_favail': 7, 'f_fsid': 111}
    (info if field in info else space)[field] = value  # type: ignore[assignment]
    closed: list[int] = []
    with monkeypatch.context() as patch:
        patch.setattr(nh.os, 'open', lambda *_a: 123)
        patch.setattr(nh.os, 'close', closed.append)
        patch.setattr(nh.os, 'fstat', lambda _fd: SimpleNamespace(**info))
        patch.setattr(nh.os, 'fstatvfs', lambda _fd: SimpleNamespace(**space))
        with pytest.raises(nh.HeadroomRefused):
            nh._sample('/controlled')
    assert closed == [123]


def test_policy_duplicate_empty_oversize_overflow_populations() -> None:
    for kind in ('demands', 'reservations'):
        for defect in ('duplicate', 'oversize', 'empty-row', 'product-overflow'):
            policy, _receipt, _bound, _now = headroom.inputs()
            row = policy[kind][0]
            if defect == 'duplicate':
                policy[kind].append(copy.deepcopy(row))
            elif defect == 'oversize':
                policy[kind] *= nh.MAX_ROWS + 1
            elif defect == 'empty-row':
                row.update(bytes=0, inodes=0)
            else:
                row.update(bytes=nh.MAX_VALUE, multiplicity=2)
            with pytest.raises(nh.HeadroomRefused):
                nh.parse_policy(policy)
    policy, receipt, bound, now = headroom.inputs()
    for row in policy['demands']:
        row.update(bytes=nh.MAX_VALUE, multiplicity=1)
    receipt['policy_digest'] = nh.policy_digest(policy)
    assert nh.evaluate(policy, receipt, bound, now)['status'] == 'UNKNOWN'
