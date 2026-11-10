"""Closed synthetic CPU/memory inputs; never measure the host or reserve it."""
from __future__ import annotations

import copy
import inspect
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from test_wave_accounting import encoded
from test_wave_resource_declaration import data

from skillc import calibration, nhl_limits
from skillc import wave_planning as planning
from skillc import wave_resources as resources
from skillc import wave_usage as usage

ROOT = Path(__file__).resolve().parents[1] / 'controls/wave-resources'


def inputs() -> tuple[planning.Plan, resources.Binding, dict[str, Any]]:
    raw = data()
    plan = planning.bind_plan(raw, usage._hash(encoded(raw)))
    binding = resources.Binding('synthetic-collection', 'synthetic-window', 'synthetic-wave',
                                'sha256:' + 'ab' * 32, plan.approved_digest,
                                raw['wave_resources']['sizing_report_digest'])
    receipt = {'version': 1, 'binding': asdict(binding), 'started_at': 100, 'finished_at': 102,
               'complete': True, 'available_cpu_millicores': 5000, 'available_memory_bytes': 8192}
    return plan, binding, receipt


def evaluate(receipt: object | None = None) -> dict[str, Any]:
    plan, binding, default = inputs()
    return resources.evaluate(plan, default if receipt is None else receipt, binding, 105)


@pytest.mark.parametrize('case', ['enough', 'cpu-short', 'memory-short', 'reservation-pressure',
                                  'zero-capacity', 'unknown'], ids=str)
def test_capacity_pass_fail_unknown_have_real_numeric_twins(case: str) -> None:
    assert len(SHAPES) == 44 and sum(len(row['values']) for row in SHAPES) == 278
    plan, binding, receipt = inputs()
    if case == 'cpu-short':
        receipt['available_cpu_millicores'] = 3759
    elif case == 'memory-short':
        receipt['available_memory_bytes'] = 3943
    elif case == 'reservation-pressure':
        receipt['available_cpu_millicores'] = 3600
        receipt['available_memory_bytes'] = 3500
    elif case == 'zero-capacity':
        receipt['available_cpu_millicores'] = 0
    elif case == 'unknown':
        receipt['complete'] = False
    result = resources.evaluate(plan, receipt, binding, 105)
    assert result['status'] == ('PASS' if case == 'enough' else 'UNKNOWN' if case == 'unknown' else 'FAIL')
    assert result['admission_authority'] is False
    if case != 'unknown':
        assert result['required_cpu_millicores'] == 3760 and result['required_memory_bytes'] == 3944
        assert result['source'] == 'owner-supplied-facts-no-host-observation-here'


@pytest.mark.parametrize('fault', ['vm', 'declaration', 'sizing', 'window', 'wave', 'collection',
                                  'stale', 'future', 'backwards', 'slow', 'missing-counter', 'storage-pass'])
def test_wrong_or_incomplete_owner_facts_never_admit(fault: str) -> None:
    plan, binding, receipt = inputs()
    field = {'vm': 'vm_binding_digest', 'declaration': 'declaration_digest', 'sizing': 'sizing_report_digest',
             'window': 'window_id', 'wave': 'wave_id', 'collection': 'collection_id'}.get(fault)
    if field:
        receipt['binding'][field] = 'sha256:' + 'ff' * 32 if field.endswith('digest') else 'other'
    elif fault == 'stale':
        receipt['started_at'], receipt['finished_at'] = 1, 2
    elif fault == 'future':
        receipt['finished_at'] = 106
    elif fault == 'backwards':
        receipt['started_at'] = 103
    elif fault == 'slow':
        receipt['started_at'] = 90
    elif fault == 'missing-counter':
        del receipt['available_memory_bytes']
    else:
        receipt = {'status': 'PASS', 'admission_authority': False, 'filesystems': []}
    assert resources.evaluate(plan, receipt, binding, 105)['status'] == 'UNKNOWN'


def test_whole_declaration_binding_and_sizing_identity_cover_resource_changes() -> None:
    raw = data()
    digest = usage._hash(encoded(raw))
    plan = planning.bind_plan(raw, digest)
    assert plan.verify()['wave_resources']['scope'] == 'declared-demand-only'
    raw['wave_resources']['roles'][2]['cpu_millicores'] += 1
    with pytest.raises(ValueError):
        planning.bind_plan(raw, digest)
    parsed = calibration.parse_declaration(data())
    parsed.data['wave_resources']['roles'][2]['memory_bytes'] = False
    with pytest.raises(calibration.DeclarationRefused, match='wave_resources'):
        calibration.require_approved(parsed, Path('.'))


def change(value: Any, path: list[Any], replacement: object) -> Any:
    if not path:
        return copy.deepcopy(replacement)
    cursor = value
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = copy.deepcopy(replacement)
    return value


SHAPES = json.loads((ROOT / 'shapes.json').read_text())


@pytest.mark.parametrize('case', SHAPES, ids=lambda case: case['id'])
def test_committed_resource_input_field_sweep(case: dict[str, Any]) -> None:
    plan, binding, receipt = inputs()
    kind = case['kind']
    initial = data()['wave_resources'] if kind == 'policy' else asdict(binding) if kind == 'binding' else receipt
    for invalid in case['values']:
        value = change(copy.deepcopy(initial), case['path'], invalid)
        if kind == 'policy':
            raw = data()
            raw['wave_resources'] = value
            with pytest.raises(ValueError):
                planning.bind_plan(raw, usage._hash(encoded(raw)))
        elif kind == 'binding':
            with pytest.raises(ValueError):
                resources.parse_binding(value)
        else:
            assert resources.evaluate(plan, value, binding, 105)['status'] == 'UNKNOWN'


def test_each_resource_object_is_closed_including_nested_demands_and_binding() -> None:
    def objects(value: Any, path: list[Any]) -> list[tuple[list[Any], dict[str, Any]]]:
        result = [(path, value)] if type(value) is dict else []
        if type(value) is dict:
            for key, child in value.items():
                result.extend(objects(child, [*path, key]))
        elif type(value) is list and value:
            result.extend(objects(value[0], [*path, 0]))
        return result
    plan, binding, receipt = inputs()
    for kind, initial in [('policy', data()['wave_resources']), ('binding', asdict(binding)), ('receipt', receipt)]:
        for path, row in objects(initial, []):
            for field in [*row, 'unexpected']:
                modified = copy.deepcopy(row)
                if field == 'unexpected':
                    modified[field] = None
                else:
                    del modified[field]
                value = change(copy.deepcopy(initial), path, modified)
                if kind == 'receipt':
                    assert resources.evaluate(plan, value, binding, 105)['status'] == 'UNKNOWN'
                else:
                    with pytest.raises(ValueError):
                        if kind == 'binding':
                            resources.parse_binding(value)
                        else:
                            raw = data()
                            raw['wave_resources'] = value
                            planning.bind_plan(raw, usage._hash(encoded(raw)))


@pytest.mark.parametrize('value', [None, False, 0, 1.5, [], {}, 'unbound'],
                         ids=['null', 'bool', 'int', 'float', 'list', 'object', 'text'])
def test_resource_reader_boundaries_and_current_time_are_controlled(value: Any) -> None:
    plan, binding, receipt = inputs()
    for args in [(value, receipt, binding, 105), (plan, value, binding, 105),
                 (plan, receipt, value, 105), (plan, receipt, binding, value)]:
        assert resources.evaluate(*args)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('value', [float('inf'), -float('inf'), float('nan'), 10**1000],
                         ids=['inf', 'minus-inf', 'nan', 'overflow'])
def test_all_resource_numbers_refuse_nonfinite_and_overflow(value: Any) -> None:
    plan, binding, receipt = inputs()
    for field in ['available_cpu_millicores', 'available_memory_bytes', 'started_at', 'finished_at']:
        changed = copy.deepcopy(receipt)
        changed[field] = value
        assert resources.evaluate(plan, changed, binding, 105)['status'] == 'UNKNOWN'
    raw = data()
    raw['wave_resources']['max_age_seconds'] = value
    with pytest.raises(ValueError):
        resources.parse(raw['wave_resources'], expected_roles=('orchestrator', 'worker-a', 'worker-b'),
                        expected_sizing_digest=raw['wave_accounting']['sizing_report_digest'])


def test_uncapped_capped_and_storage_helpers_do_not_acquire_new_authority() -> None:
    raw = data()
    assert nhl_limits.require_for_execution(raw) is not None
    raw['nhl_limits'] = {'version': 1, 'mode': 'capped', 'sizing_report_digest': raw['wave_resources']['sizing_report_digest'],
                         'wall_seconds': 14, 'tokens': 1}
    plan = planning.bind_plan(raw, usage._hash(encoded(raw)))
    assert planning.report(plan)['mode'] == 'capped'
    with pytest.raises(nhl_limits.LimitsRefused, match='enforcement'):
        nhl_limits.require_for_execution(raw)
    assert evaluate()['admission_authority'] is False


def compiled(monkeypatch: pytest.MonkeyPatch, function: Any, before: str, after: str) -> None:
    source = inspect.getsource(function)
    assert source.count(before) == 1
    namespace = vars(resources)
    exec(compile(source.replace(before, after), '<blind-wave-resources>', 'exec'), namespace)  # noqa: S102
    mutant = namespace[function.__name__]
    namespace[function.__name__] = function
    monkeypatch.setattr(resources, function.__name__, mutant)


def test_always_pass_mutant_loses_cpu_shortage_witness(monkeypatch: pytest.MonkeyPatch) -> None:
    compiled(monkeypatch, resources._evaluate,
             "status = ('PASS' if cpu >= policy['required_cpu_millicores']\n              and memory >= policy['required_memory_bytes'] else 'FAIL')",
             "status = 'PASS'")
    with pytest.raises(AssertionError):
        test_capacity_pass_fail_unknown_have_real_numeric_twins('cpu-short')


def test_ignored_reservations_mutant_loses_pressure_witness(monkeypatch: pytest.MonkeyPatch) -> None:
    compiled(monkeypatch, resources.parse,
             "demands = role_demands + groups['auxiliaries'] + groups['reservations']",
             "demands = role_demands + groups['auxiliaries']")
    with pytest.raises(AssertionError):
        test_capacity_pass_fail_unknown_have_real_numeric_twins('reservation-pressure')


def test_wrong_vm_blind_mutant_loses_owner_binding_witness(monkeypatch: pytest.MonkeyPatch) -> None:
    compiled(monkeypatch, resources._evaluate, "or parse_binding(row['binding']) != expected", 'or False')
    with pytest.raises(AssertionError):
        test_wrong_or_incomplete_owner_facts_never_admit('vm')


def test_resource_technical_bounds_and_explicit_empty_reservations() -> None:
    raw = data()
    raw['wave_resources']['reservations'] = []
    result = planning.bind_plan(raw, usage._hash(encoded(raw))).verify()['wave_resources']
    assert result['required_cpu_millicores'] == 3560 and result['required_memory_bytes'] == 3432
    for group in ['roles', 'auxiliaries', 'reservations']:
        modified = data()
        modified['wave_resources'][group] *= 257
        with pytest.raises(ValueError):
            planning.bind_plan(modified, usage._hash(encoded(modified)))
    for value in [True, 0, -1, 1.5, 1 << 63]:
        modified = data()
        modified['wave_resources']['roles'][2]['cpu_millicores'] = value
        with pytest.raises(ValueError):
            planning.bind_plan(modified, usage._hash(encoded(modified)))


def test_unknown_output_does_not_echo_private_supplied_identity() -> None:
    plan, binding, receipt = inputs()
    marker = 'private-resource-marker'
    receipt['unexpected'] = marker
    result = resources.evaluate(plan, receipt, binding, 105)
    assert result['status'] == 'UNKNOWN' and marker not in json.dumps(result)
    assert marker in json.dumps({**result, 'injected': marker})
