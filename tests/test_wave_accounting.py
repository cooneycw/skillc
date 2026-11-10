"""Authored numeric captures and projections; no native client or host probe."""
from __future__ import annotations

import copy
import inspect
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from skillc import cost_estimate as cost
from skillc import nhl_limits, schedule_budget
from skillc import wave_planning as planning
from skillc import wave_usage as usage

ROOT = Path(__file__).resolve().parents[1] / 'controls/wave-accounting'
SHAPES = json.loads((ROOT / 'shapes.json').read_text())


def fixture(name: str) -> Any:
    return json.loads((ROOT / (name + '.json')).read_text())


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def context() -> usage.Context:
    return usage.parse_context(fixture('context'))


def observed(value: object) -> dict[str, Any]:
    raw = encoded(value)
    return usage.evaluate(raw, usage.reference(raw, context()), context())


def plan(value: object | None = None) -> planning.Plan:
    data = fixture('plan') if value is None else value
    return planning.bind_plan(data, usage._hash(encoded(data)))


def change(value: Any, path: list[Any], replacement: object) -> Any:
    if not path:
        return copy.deepcopy(replacement)
    cursor = value
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = copy.deepcopy(replacement)
    return value


def test_complete_three_role_resumed_capture_uses_final_counters_and_common_wall() -> None:
    assert len(SHAPES) == 58 and sum(len(row['values']) for row in SHAPES) == 364
    result = observed(fixture('complete'))
    assert result['status'] == 'COMPLETE' and result['tokens_complete']
    assert [row['tokens'] for row in result['roles']] == [9, 6, 8]
    assert result['tokens'] == result['known_tokens_subtotal'] == 23
    assert result['known_roles'] == result['planned_roles'] == 3
    assert result['wall_seconds'] == 7 and result['role_active_seconds'] == 12
    assert [row['active_seconds'] for row in result['roles']] == [4, 4, 4]
    assert [row['session_elapsed'] for row in result['roles']] == [5, 5, 5]
    assert result['source'] == 'client-reported-not-provider-attested'
    assert not result['enforcement_authority'] and not result['admission_authority']


@pytest.mark.parametrize('fault', ['role-3', 'turn-3', 'samples-3', 'session-3', 'reset-3',
                                  'duplicate-role', 'duplicate-turn', 'role-order', 'turn-order'])
def test_missing_or_ambiguous_third_role_never_becomes_zero(fault: str) -> None:
    data = fixture('complete')
    third = data['roles'][2]
    if fault == 'role-3':
        data['roles'].pop()
    elif fault == 'turn-3':
        third['turns'].pop()
    elif fault == 'samples-3':
        third['turns'][-1]['samples'] = []
    elif fault == 'session-3':
        third['session_id'] = data['roles'][0]['session_id']
    elif fault == 'reset-3':
        third['turns'][-1]['samples'] = [0, 1]
    elif fault == 'duplicate-role':
        data['roles'].append(copy.deepcopy(third))
    elif fault == 'duplicate-turn':
        third['turns'].append(copy.deepcopy(third['turns'][-1]))
    elif fault == 'role-order':
        data['roles'].reverse()
    else:
        third['turns'].reverse()
    result = observed(data)
    assert result['status'] == 'UNKNOWN' and not result['tokens_complete'] and result['tokens'] is None
    if fault != 'role-order':
        assert result['known_roles'] == 2 and result['known_tokens_subtotal'] == 15
        assert result['roles'][2]['tokens'] is None


@pytest.mark.parametrize('damage', ['hash', 'size', 'context', 'payload', 'report-as-reference', 'empty'])
def test_expected_receipt_is_independent_of_capture_and_public_report(damage: str) -> None:
    raw = encoded(fixture('complete'))
    expected: Any = context()
    receipt: Any = usage.reference(raw, expected)
    if damage == 'hash':
        receipt = replace(receipt, digest='sha256:' + 'ff' * 32)
    elif damage == 'size':
        receipt = replace(receipt, size=receipt.size + 1)
    elif damage == 'context':
        expected = replace(expected, wave_id='different-wave')
    elif damage == 'payload':
        raw = raw.replace(b'"samples":[1,5]', b'"samples":[9,9]')
    elif damage == 'report-as-reference':
        receipt = {'version': 1, **asdict(receipt), 'status': 'COMPLETE', 'tokens': 999}
    else:
        raw = b''
    result = usage.evaluate(raw, receipt, expected)
    assert result['status'] == 'UNKNOWN' and result['tokens'] is None


@pytest.mark.parametrize('field', ['wave_id', 'declaration_digest', 'deadline_digest', 'clock',
                                  'client_version', 'counter_format'])
def test_captured_context_fields_cannot_replace_expected_binding(field: str) -> None:
    data = fixture('complete')
    data[field] = 'different'
    assert observed(data)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('case', SHAPES, ids=lambda case: case['id'])
def test_committed_closed_field_sweep(case: dict[str, Any]) -> None:
    kind = case['kind']
    original = (fixture(kind) if kind in ('context',) else fixture('complete') if kind == 'usage'
                else asdict(usage.reference(encoded(fixture('complete')), context())) if kind == 'reference'
                else fixture('plan')['wave_accounting'] if kind == 'plan' else fixture('plan')['nhl_limits'])
    for bad in case['values']:
        value = change(copy.deepcopy(original), case['path'], bad)
        if kind == 'usage':
            assert observed(value)['status'] == 'UNKNOWN'
        else:
            with pytest.raises(ValueError):
                if kind == 'context':
                    usage.parse_context(value)
                elif kind == 'reference':
                    usage.parse_reference(value)
                else:
                    declaration = fixture('plan')
                    declaration['wave_accounting' if kind == 'plan' else 'nhl_limits'] = value
                    plan(declaration)


def test_missing_sizing_and_changed_whole_approval_refuse_instead_of_free_plan() -> None:
    raw = fixture('plan')
    digest = usage._hash(encoded(raw))
    bound = planning.bind_plan(raw, digest)
    assert bound.verify()['input_tokens'] == 97
    raw['unrelated_but_approved_fact'] = 'edited'
    with pytest.raises(ValueError):
        planning.bind_plan(raw, digest)
    for field in list(fixture('plan')['wave_accounting']):
        raw = fixture('plan')
        del raw['wave_accounting'][field]
        with pytest.raises(ValueError):
            plan(raw)
    absent_values: list[Any] = [None, {}, [], 'not-sized']
    for value in absent_values:
        assert schedule_budget.wave_refusal_reason(value, waves=1, total_seconds=100) is not None


def test_multi_session_cost_counts_every_role_and_resume_but_judges_once_per_wave() -> None:
    price = cost.ModelPrice('synthetic-price', 1, 2, 'synthetic-fixture')
    value = cost.estimate_wave(plan(), trials=1, waves_per_trial=2, price=price,
                              judge_tiers_enabled=2, judge_price=price,
                              judge_input_tokens=17, judge_output_tokens=4)
    assert [role['turns'] for role in value.roles] == [3, 2, 4]
    assert [role['input_tokens'] for role in value.roles] == [20, 26, 51]
    assert value.cost.estimated_input_tokens_per_attempt == 97
    assert value.cost.estimated_output_tokens_per_attempt == 15
    assert value.cost.total_attempts == 2 and value.cost.judge_calls_total == 4
    assert value.cost.estimated_usd == pytest.approx(354 / 1_000_000)
    assert value.cost.judge_estimated_usd == pytest.approx(100 / 1_000_000)
    assert value.cost.assumptions['attempt_unit'] == 'wave'


def test_explicit_wave_critical_path_and_all_overhead_are_not_role_time_sum() -> None:
    value = planning.schedule(plan(), waves=2, total_seconds=28)
    assert [role['active_seconds'] for role in value['roles']] == [4, 4, 7]
    assert value['wave_seconds'] == 14 and value['required_seconds'] == 28
    assert schedule_budget.wave_refusal_reason(plan(), waves=2, total_seconds=28) is None
    assert schedule_budget.wave_refusal_reason(plan(), waves=2, total_seconds=27) is not None
    raw = fixture('plan')
    raw['wave_accounting']['critical_path_seconds'] = 6
    with pytest.raises(ValueError):
        plan(raw)


def test_uncapped_measurement_does_not_install_a_token_stopper_and_capped_stays_held() -> None:
    raw = fixture('plan')
    expected = planning.report(plan(raw))
    data = fixture('complete')
    for role in data['roles']:
        role['turns'][-1]['samples'] = [1000, 2000]
    observed_usage = observed(data)
    assert observed_usage['status'] == 'COMPLETE' and observed_usage['tokens'] == 6000
    assert observed_usage['tokens'] > expected['input_tokens'] + expected['output_tokens']
    assert expected['mode'] == 'uncapped' and expected['token_enforcement'] == 'unavailable'
    mode = nhl_limits.require_for_execution(raw)
    assert mode is not None and mode['mode'] == 'uncapped'
    raw['nhl_limits'] = {'version': 1, 'mode': 'capped', 'wall_seconds': 10, 'tokens': 1,
                         'sizing_report_digest': raw['wave_accounting']['sizing_report_digest']}
    assert planning.report(plan(raw))['mode'] == 'capped'
    with pytest.raises(nhl_limits.LimitsRefused, match='enforcement'):
        nhl_limits.require_for_execution(raw)


def compiled(monkeypatch: pytest.MonkeyPatch, module: Any, function: Any, before: str, after: str) -> None:
    source = inspect.getsource(function)
    assert source.count(before) == 1
    namespace = vars(module)
    name = function.__name__
    exec(compile(source.replace(before, after), '<blind-wave-accounting>', 'exec'), namespace)  # noqa: S102
    mutant = namespace[name]
    namespace[name] = function
    monkeypatch.setattr(module, name, mutant)


def test_sum_cumulative_samples_mutant_loses_complete_counter_witness(monkeypatch: pytest.MonkeyPatch) -> None:
    compiled(monkeypatch, usage, usage._last_counter, 'return samples[-1]', 'return sum(samples)')
    with pytest.raises(AssertionError):
        test_complete_three_role_resumed_capture_uses_final_counters_and_common_wall()


def test_always_complete_mutant_loses_missing_third_role_witness(monkeypatch: pytest.MonkeyPatch) -> None:
    compiled(monkeypatch, usage, usage._project,
             "'status': 'COMPLETE' if complete and completion is not None else 'UNKNOWN'", "'status': 'COMPLETE'")
    with pytest.raises(AssertionError):
        test_missing_or_ambiguous_third_role_never_becomes_zero('role-3')


def test_flat_single_role_cost_mutant_loses_projection_witness(monkeypatch: pytest.MonkeyPatch) -> None:
    compiled(monkeypatch, planning, planning._validate,
             'planned = [_role_plan(role) for role in roles]', 'planned = [_role_plan(role) for role in roles[:1]]')
    with pytest.raises(AssertionError):
        test_multi_session_cost_counts_every_role_and_resume_but_judges_once_per_wave()


def test_hash_blind_reader_loses_independent_reference_witness(monkeypatch: pytest.MonkeyPatch) -> None:
    compiled(monkeypatch, usage, usage.evaluate, '_hash(raw) != receipt.digest', 'False')
    with pytest.raises(AssertionError):
        test_expected_receipt_is_independent_of_capture_and_public_report('hash')


def test_summed_parallel_wall_mutant_loses_common_clock_witness(monkeypatch: pytest.MonkeyPatch) -> None:
    compiled(monkeypatch, usage, usage._project, "'wall_seconds': completion",
             "'wall_seconds': sum(role['active_seconds'] or 0 for role in records)")
    with pytest.raises(AssertionError):
        test_complete_three_role_resumed_capture_uses_final_counters_and_common_wall()


@pytest.mark.parametrize('value', [None, True, 0, 1.5, '', [], {}],
                         ids=['null', 'bool', 'int', 'float', 'text', 'list', 'object'])
def test_public_boundaries_refuse_wrong_types(value: Any) -> None:
    raw = encoded(fixture('complete'))
    receipt = usage.reference(raw, context())
    for args in [(value, receipt, context()), (raw, value, context()), (raw, receipt, value)]:
        assert usage.evaluate(*args)['status'] == 'UNKNOWN'
    with pytest.raises(ValueError):
        usage.reference(value, context())
    with pytest.raises(ValueError):
        usage.reference(raw, value)
    with pytest.raises(ValueError):
        planning.parse_plan(value)
    with pytest.raises(ValueError):
        planning.report(value)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), 10**1000],
                         ids=['nan', 'inf', 'minus-inf', 'overflow'])
def test_nonfinite_and_overflow_counters_and_clocks_are_unavailable(value: Any) -> None:
    data = fixture('complete')
    data['completion_elapsed'] = value
    raw = json.dumps(data).encode()
    assert usage.evaluate(raw, usage.reference(raw, context()), context())['status'] == 'UNKNOWN'
    raw_plan = fixture('plan')
    raw_plan['wave_accounting']['critical_path_seconds'] = value
    with pytest.raises(ValueError):
        planning.bind_plan(raw_plan, usage._hash(json.dumps(raw_plan, sort_keys=True, separators=(',', ':')).encode()))
    data = fixture('complete')
    data['roles'][2]['turns'][-1]['samples'] = [value]
    raw = json.dumps(data).encode()
    assert usage.evaluate(raw, usage.reference(raw, context()), context())['tokens'] is None


def test_missing_extra_duplicate_and_deep_json_do_not_become_complete() -> None:
    for _kind, original, parse in [
        ('context', fixture('context'), usage.parse_context),
        ('reference', asdict(usage.reference(encoded(fixture('complete')), context())), usage.parse_reference),
    ]:
        for key in [*original, 'unexpected']:
            value = copy.deepcopy(original)
            if key == 'unexpected':
                value[key] = None
            else:
                del value[key]
            with pytest.raises(ValueError):
                parse(value)
    for key in [*fixture('complete'), 'unexpected']:
        value = fixture('complete')
        if key == 'unexpected':
            value[key] = None
        else:
            del value[key]
        assert observed(value)['status'] == 'UNKNOWN'
    raw = encoded(fixture('complete'))
    duplicate = raw.replace(b'"version":1', b'"version":1,"version":1')
    for payload in [duplicate, b'\xff', b'[', b'[' * 2000 + b'0' + b']' * 2000]:
        assert usage.evaluate(payload, usage.reference(payload, context()), context())['status'] == 'UNKNOWN'


def test_no_samples_empty_population_counter_overflow_and_missing_completion_keep_unknown() -> None:
    zero = fixture('complete')
    for role in zero['roles']:
        for turn in role['turns']:
            turn['samples'] = [0]
    assert observed(zero)['tokens'] == 0 and observed(zero)['known_roles'] == 3
    data = fixture('complete')
    data['roles'] = []
    result = observed(data)
    assert result['known_roles'] == 0 and result['known_tokens_subtotal'] is None
    assert result['planned_roles'] == 3 and result['tokens'] is None
    data = fixture('complete')
    data['completion_elapsed'] = None
    result = observed(data)
    assert result['status'] == 'UNKNOWN' and result['wall_seconds'] is None
    assert result['tokens_complete'] and result['tokens'] == 23
    data = fixture('complete')
    for role in data['roles']:
        role['turns'][-1]['samples'] = [usage.MAX_COUNT]
    assert observed(data)['tokens'] is None


def test_context_turn_boundary_and_distinct_session_population() -> None:
    bad_turn_values: list[Any] = [None, False, [], {}, '', 'initial', 'AB' * 16, 'ab' * 15]
    for value in bad_turn_values:
        raw = fixture('context')
        raw['roles'][0]['turns'][1] = value
        with pytest.raises(ValueError):
            usage.parse_context(raw)
    raw = fixture('context')
    raw['roles'][1]['session_id'] = raw['roles'][0]['session_id']
    with pytest.raises(ValueError):
        usage.parse_context(raw)


def test_sizing_source_and_all_cost_entry_argument_types_are_bound() -> None:
    raw = fixture('plan')
    raw['nhl_limits'] = {'version': 1, 'mode': 'capped', 'wall_seconds': 10, 'tokens': 1,
                         'sizing_report_digest': 'sha256:' + 'ff' * 32}
    with pytest.raises(ValueError):
        plan(raw)
    price = cost.ModelPrice('synthetic-price', 1, 2, 'synthetic-fixture')
    for key in ['trials', 'waves_per_trial', 'judge_tiers_enabled', 'judge_input_tokens', 'judge_output_tokens',
                'price', 'judge_price']:
        for value in [False, 1.5, [], {}, 'unknown']:
            kwargs: dict[str, Any] = {'trials': 1, 'waves_per_trial': 1, 'price': price, key: value}
            with pytest.raises(ValueError):
                cost.estimate_wave(plan(), **kwargs)


def test_each_owned_nested_object_refuses_missing_and_extra_members() -> None:
    def objects(value: Any, path: list[Any]) -> list[tuple[list[Any], dict[str, Any]]]:
        found = [(path, value)] if type(value) is dict else []
        if type(value) is dict:
            for key, child in value.items():
                found.extend(objects(child, [*path, key]))
        elif type(value) is list and value:
            found.extend(objects(value[0], [*path, 0]))
        return found

    reference = asdict(usage.reference(encoded(fixture('complete')), context()))
    for kind, original in [('context', fixture('context')), ('reference', reference),
                           ('usage', fixture('complete')), ('plan', fixture('plan')['wave_accounting']),
                           ('limits', fixture('plan')['nhl_limits'])]:
        for path, obj in objects(original, []):
            for field in [*obj, 'unexpected']:
                changed = copy.deepcopy(obj)
                if field == 'unexpected':
                    changed[field] = None
                else:
                    del changed[field]
                value = change(copy.deepcopy(original), path, changed)
                if kind == 'usage':
                    assert observed(value)['status'] == 'UNKNOWN'
                else:
                    with pytest.raises(ValueError):
                        if kind == 'context':
                            usage.parse_context(value)
                        elif kind == 'reference':
                            usage.parse_reference(value)
                        else:
                            raw = fixture('plan')
                            raw['wave_accounting' if kind == 'plan' else 'nhl_limits'] = value
                            plan(raw)


@pytest.mark.parametrize('fault', ['raw-none', 'hash', 'size', 'receipt-type', 'empty', 'context-digest'])
def test_existing_reader_preserves_independent_planned_population_on_custody_loss(fault: str) -> None:
    raw: Any = encoded(fixture('complete'))
    expected = context()
    receipt: Any = usage.reference(raw, expected)
    if fault == 'raw-none':
        raw = None
    elif fault == 'hash':
        receipt = replace(receipt, digest='sha256:' + 'ff' * 32)
    elif fault == 'size':
        receipt = replace(receipt, size=receipt.size + 1)
    elif fault == 'receipt-type':
        receipt = asdict(receipt)
    elif fault == 'empty':
        raw = b''
    else:
        receipt = replace(receipt, context_digest='sha256:' + 'ff' * 32)
    result = usage.evaluate(raw, receipt, expected)
    assert result['status'] == 'UNKNOWN'
    assert result.get('planned_roles') == 3
    assert [(role['role'], role['session_id']) for role in result['roles']] == [
        (role.role, role.session_id) for role in expected.roles]
    assert all(role['tokens'] is None and role['turns'] is None for role in result['roles'])
    assert [role['planned_turns'] for role in result['roles']] == [2, 2, 2]
    assert result['known_tokens_subtotal'] is None and result['known_roles'] == 0


@pytest.mark.parametrize('unstarted', [(2,), (1, 2), (0, 1, 2)], ids=['one', 'two', 'all'])
def test_existing_context_keeps_planned_nonstarts_with_null_session(unstarted: tuple[int, ...]) -> None:
    raw_context = fixture('context')
    data = fixture('complete')
    for index in unstarted:
        raw_context['roles'][index]['session_id'] = None
        raw_context['roles'][index]['turns'] = ['initial']
        data['roles'][index]['session_id'] = None
        data['roles'][index]['turns'] = []
    try:
        expected = usage.parse_context(raw_context)
    except ValueError:
        pytest.fail('planned nonstart with unobserved session was refused')
    raw = encoded(data)
    result = usage.evaluate(raw, usage.reference(raw, expected), expected)
    assert result['status'] == 'UNKNOWN' and result['planned_roles'] == 3
    assert result['known_roles'] == 3 - len(unstarted) and result['tokens'] is None
    assert len(result['roles']) == 3
    for index in unstarted:
        assert result['roles'][index]['session_id'] is None and result['roles'][index]['tokens'] is None
        assert result['roles'][index]['planned_turns'] == 1 and result['roles'][index]['turns'] is None


def test_null_expected_session_cannot_be_promoted_by_claimed_usage() -> None:
    raw_context = fixture('context')
    raw_context['roles'][2]['session_id'] = None
    try:
        expected = usage.parse_context(raw_context)
    except ValueError:
        pytest.fail('planned nonstart with unobserved session was refused')
    data = fixture('complete')
    data['roles'][2]['session_id'] = None
    raw = encoded(data)
    result = usage.evaluate(raw, usage.reference(raw, expected), expected)
    assert result['tokens'] is None and result['known_tokens_subtotal'] == 15
    assert result['roles'][2]['tokens'] is None and result['known_roles'] == 2
