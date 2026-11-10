"""Committed input-level qualification before the first full assembler gate."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import test_live_wave_assembly as harness

from skillc import live_wave
from skillc import live_wave_assembly as assembly

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / 'controls/live-wave-assembly/shapes-base.json').read_text())
CASES = json.loads((ROOT / 'controls/live-wave-assembly/shapes.json').read_text())
OBSERVATIONS = json.loads((ROOT / 'controls/live-wave-assembly/observation-shapes.json').read_text())
STREAMS = json.loads((ROOT / 'controls/live-wave-assembly/stream-shapes.json').read_text())
PLAN_CASES = [case for case in CASES if len(case['path']) < 2 or case['path'][0] != 'waves'
              or len(case['path']) == 2 or case['path'][2] in ('plan', 'budget_digest', 'clock', 'grader_digest', 'unexpected')]


@pytest.fixture(scope='module')
def bundle(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, ...]:
    return harness.fixture(tmp_path_factory.mktemp('assembly-shapes'))


def changed(value: object, case: dict[str, Any]) -> object:
    root = copy.deepcopy(value)
    if not case['path']:
        return case['value']
    target = root
    for key in case['path'][:-1]:
        target = target[key]  # type: ignore[index]
    if case.get('delete'):
        del target[case['path'][-1]]  # type: ignore[attr-defined]
    else:
        target[case['path'][-1]] = case['value']  # type: ignore[index]
    return root


@pytest.mark.parametrize('case', CASES, ids=lambda row: row['name'])
def test_committed_contract_levels_refuse_without_generic_exception(bundle: tuple[Any, ...], case: dict[str, Any]) -> None:
    _arrival, expected, _graders, _raw = bundle
    assembly.freeze(BASE, expected.exported, expected.planned)  # This exact parser accepts the intact opposite.
    with pytest.raises(assembly.AssemblyRefused):
        assembly.freeze(changed(BASE, case), expected.exported, expected.planned)


@pytest.mark.parametrize('case', PLAN_CASES, ids=lambda row: row['name'])
def test_original_preobservation_plan_uses_the_committed_unmasked_levels(
    bundle: tuple[Any, ...], case: dict[str, Any],
) -> None:
    _arrival, expected, _graders, _raw = bundle
    original = json.loads(expected.planned.data)
    assembly.freeze_plan(original)
    with pytest.raises(assembly.AssemblyRefused):
        assembly.freeze_plan(changed(original, case))


@pytest.mark.parametrize('field', ['manifest_sha256', 'declaration_digest', 'plan', 'outcomes'])
@pytest.mark.parametrize('bad', [None, True, 1, 1.5, 'bad', [], {}],
                         ids=['null', 'bool', 'int', 'float', 'str', 'list', 'dict'])
def test_export_expectation_boundaries_are_not_assumed_well_shaped(
    bundle: tuple[Any, ...], field: str, bad: Any,
) -> None:
    _arrival, expected, _graders, raw = bundle
    with pytest.raises(assembly.AssemblyRefused):
        assembly.freeze(raw, replace(expected.exported, **{field: bad}), expected.planned)


@pytest.mark.parametrize('raw', [None, b'', b'{', b'[]', b'null', b'{"x":1,"x":2}',
                               b'[' * 2000, b' ' * (assembly.MAX_METADATA + 1), b'\xff'],
                         ids=['null', 'empty', 'truncated', 'list', 'scalar', 'duplicate', 'deep', 'oversize', 'utf8'])
def test_malformed_frozen_bytes_cannot_become_an_arrival_result(bundle: tuple[Any, ...], raw: Any) -> None:
    arrival, expected, graders, _raw = bundle
    with pytest.raises(assembly.AssemblyRefused):
        assembly.report(arrival, replace(expected, data=raw), graders)


@pytest.mark.parametrize('kind', ['wave', 'role'])
@pytest.mark.parametrize('bad', [None, True, 1, 1.5, 'bad', [], {}],
                         ids=['null', 'bool', 'int', 'float', 'str', 'list', 'dict'])
def test_observation_roots_are_closed(bundle: tuple[Any, ...], kind: str, bad: object) -> None:
    _arrival, _expected, _graders, raw = bundle
    row = raw['waves'][0]
    binding = assembly._plan(row['plan']).roles[0] if kind == 'role' else None
    with pytest.raises(assembly.AssemblyRefused):
        assembly._observation(bad, row, role=binding)


@pytest.mark.parametrize('level', ['wave', 'role'])
def test_every_observation_field_has_direct_unmasked_wrong_type_controls(bundle: tuple[Any, ...], level: str) -> None:
    arrival, _expected, _graders, raw = bundle
    row = raw['waves'][0]
    reference = row['observation'] if level == 'wave' else row['roles'][0]['observation']
    intact = json.loads((arrival / 'payload' / reference['path']).read_bytes())
    binding = assembly._plan(row['plan']).roles[0] if level == 'role' else None
    assert assembly._observation(intact, row, role=binding) == intact
    for key in intact:
        with pytest.raises(assembly.AssemblyRefused):
            assembly._observation({k: v for k, v in intact.items() if k != key}, row, role=binding)
        bad_values: tuple[object, ...] = ([], {})
        for bad in bad_values:
            with pytest.raises(assembly.AssemblyRefused):
                assembly._observation({**intact, key: bad}, row, role=binding)
    with pytest.raises(assembly.AssemblyRefused):
        assembly._observation({**intact, 'unexpected': 0}, row, role=binding)


@pytest.mark.parametrize('case', OBSERVATIONS, ids=lambda row: row['name'])
def test_committed_observation_fields_refuse_directly_before_binding_can_mask_them(
    bundle: tuple[Any, ...], case: dict[str, Any],
) -> None:
    arrival, _expected, _graders, raw = bundle
    row = raw['waves'][0]
    reference = row['observation'] if case['level'] == 'wave' else row['roles'][0]['observation']
    intact = json.loads((arrival / 'payload' / reference['path']).read_bytes())
    binding = assembly._plan(row['plan']).roles[0] if case['level'] == 'role' else None
    assembly._observation(intact, row, role=binding)
    if case.get('delete'):
        del intact[case['key']]
    else:
        intact[case['key']] = case['value']
    with pytest.raises(assembly.AssemblyRefused):
        assembly._observation(intact, row, role=binding)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), 10**400],
                         ids=['nan', 'inf', 'minus-inf', 'overflow'])
def test_time_domains_refuse_nonfinite_without_math_overflow(bundle: tuple[Any, ...], value: Any) -> None:
    arrival, _expected, _graders, raw = bundle
    row = raw['waves'][0]
    role = assembly._plan(row['plan']).roles[0]
    for reference, binding, keys in [(row['observation'], None,
                                    ['completion_elapsed', 'infrastructure_failed_at', 'deadline_witnessed_at']),
                                   (row['roles'][0]['observation'], role, ['stop_elapsed', 'wall_seconds'])]:
        intact = json.loads((arrival / 'payload' / reference['path']).read_bytes())
        for key in keys:
            with pytest.raises(assembly.AssemblyRefused):
                assembly._observation({**intact, key: value}, row, role=binding)


def test_frozen_shape_case_population_is_nonempty_and_unique() -> None:
    assert len(CASES) == 646 and len({r['name'] for r in CASES}) == len(CASES)


@pytest.mark.parametrize('case', STREAMS, ids=lambda row: row['name'])
def test_protocol_field_shapes_are_unavailable_without_generic_exception(case: dict[str, Any]) -> None:
    binding = BASE['waves'][0]['plan']['roles'][0]
    event = {k: v for k, v in binding.items() if k != 'required_artifacts'}
    event.update(wave_id=BASE['waves'][0]['plan']['wave_id'], op='ack', elapsed=1)
    intact = harness._blind_protocol(assembly._plan(BASE['waves'][0]['plan']), live_wave.RoleBinding(
        **{**binding, 'required_artifacts': tuple(binding['required_artifacts'])}))
    assert assembly._stream(intact, protocol=True) is intact
    if case.get('delete'):
        del event[case['key']]
    else:
        event[case['key']] = case['value']
    data = harness.raw_json(event) + b'\n'
    assert assembly._stream(live_wave.Blob(data, harness.exported.sha(data)[7:]), protocol=True) is None


@pytest.mark.parametrize('raw', [b'', b'{}', b'[]\n', b'null\n', b'{"x":1,"x":2}\n', b'{\n',
                               b'[' * 2000 + b'\n', b'\xff\n', b'{}\n' * (assembly.MAX_ROWS + 1)],
                         ids=['empty', 'truncated', 'list', 'scalar', 'duplicate', 'bad-json', 'deep', 'utf8', 'population'])
def test_raw_protocol_shape_and_population_controls(raw: bytes) -> None:
    assert assembly._stream(live_wave.Blob(raw, harness.exported.sha(raw)[7:]), protocol=True) is None
