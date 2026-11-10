"""Closed wake input controls; scripted actors only, never real containers."""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from test_wave_wake import BASE, SID, ScriptedWave, policy

from skillc import wave_wake as ww

ROOT = Path(__file__).resolve().parents[1]
SHAPES = json.loads((ROOT / 'controls/wave-wake/shapes.json').read_text())
NONCE = 'ab' * 16


def capture_refusal(call: Any) -> Exception:
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - prove the refusal class, not an incidental exception
        assert isinstance(exc, ValueError), type(exc).__name__
        return exc
    raise AssertionError('unsafe wake input accepted')


@pytest.mark.parametrize('bad', [None, True, 1, [], {}, '', 'role/escape'],
                         ids=['null', 'bool', 'int', 'list', 'dict', 'empty', 'path'])
def test_existing_state_constructor_refuses_invalid_population_members(bad: Any) -> None:
    capture_refusal(lambda: ww.WakeState(policy(), (bad,)))


@pytest.mark.parametrize('field', ['role', 'session', 'revision', 'nonce'])
@pytest.mark.parametrize('bad', [None, True, 1, [], {}, ''], ids=['null', 'bool', 'int', 'list', 'dict', 'empty'])
def test_existing_poke_constructor_refuses_invalid_identity(field: str, bad: Any) -> None:
    values = {'role': 'worker-a', 'session': SID, 'revision': BASE.identity, 'nonce': NONCE}
    values[field] = bad
    capture_refusal(lambda: ww.Poke(**values))


@pytest.mark.parametrize('change', ['literal', 'policy', 'roles', 'approval', 'absent'])
def test_existing_driver_refuses_changed_caller_approval_before_prepare(
    tmp_path: Path, change: str,
) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    proposed = policy()
    if change == 'literal':
        proposed = replace(proposed, literal='A different declared instruction.')
    elif change == 'policy':
        proposed = replace(proposed, max_pokes=2)
    elif change == 'roles':
        wave.roles.reverse()
    elif change == 'approval':
        # Existing class on main need not know a new API to expose the missing fence.
        wave.approved_wake = type(wave.approved_wake)(declaration=wave.approved_wake.declaration,
                                                   approved_digest=BASE.identity)
    else:
        del wave.approved_wake
    capture_refusal(lambda: ww.drive(wave, proposed, read_revision=wave.read))
    assert wave._prepared is False and not wave.calls and not wave.closed
    assert not (wave.root / 'wake-declaration.json').exists()


def declaration() -> dict[str, Any]:
    return {'roles': ['worker-a', 'worker-b'], 'controller_wake': {'version': 1, **asdict(policy())},
            'other_caller_fact': 'included-in-whole-approval'}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(raw: bytes) -> str:
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def mutate(value: Any, path: list[Any], replacement: Any) -> Any:
    if not path:
        return copy.deepcopy(replacement)
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = copy.deepcopy(replacement)
    return None


@pytest.mark.parametrize('case', SHAPES, ids=lambda row: row['name'])
def test_all_closed_input_levels_refuse_the_committed_wrong_types(case: dict[str, Any]) -> None:
    raw = declaration()
    kind = case['kind']
    initial: Any = {'policy': raw['controller_wake'], 'revision': asdict(BASE),
                    'poke': {'role': 'worker-a', 'session': SID, 'revision': BASE.identity, 'nonce': NONCE},
                    'declaration': raw, 'state': {'policy': raw['controller_wake'], 'roles': raw['roles']}, 'binding': {'declaration': canonical(raw),
                                                  'approved_digest': digest(canonical(raw))}}[kind]
    value = copy.deepcopy(initial)
    root = mutate(value, case['path'], case['value'])
    if not case['path']:
        value = root
    call: Callable[[], object]
    if kind == 'state':
        call = lambda: ww.parse_state(value)
    elif kind == 'policy':
        call = lambda: ww.parse_policy(value)
    elif kind == 'revision':
        call = lambda: ww.parse_revision(value)
    elif kind == 'poke':
        call = lambda: ww.parse_poke(value)
    elif kind == 'declaration':
        call = lambda: ww.bind_declaration(value, digest(canonical(value)))
    elif type(value) is dict:
        call = lambda: ww.parse_binding(value)
    else:
        call = lambda: ww.bind_declaration(value, BASE.identity)
    capture_refusal(call)


@pytest.mark.parametrize('kind', ['policy', 'revision', 'poke'])
def test_closed_objects_refuse_every_missing_or_extra_field(kind: str) -> None:
    value = {'policy': declaration()['controller_wake'], 'revision': asdict(BASE),
             'poke': {'role': 'worker-a', 'session': SID, 'revision': BASE.identity, 'nonce': NONCE}}[kind]
    parse = {'policy': ww.parse_policy, 'revision': ww.parse_revision, 'poke': ww.parse_poke}[kind]
    assert parse(value)
    for key in [*value, 'unknown']:
        changed = copy.deepcopy(value)
        if key == 'unknown':
            changed[key] = None
        else:
            del changed[key]
        capture_refusal(lambda changed=changed: parse(changed))


def test_whole_approval_and_canonical_binding_are_verified() -> None:
    raw = declaration()
    approved = digest(canonical(raw))
    bound = ww.bind_declaration(raw, approved)
    assert bound.verify() == (('worker-a', 'worker-b'), policy())
    raw['other_caller_fact'] = 'edited'
    capture_refusal(lambda: ww.bind_declaration(raw, approved))
    for payload in [b'{}', b'null', b'{', b'[' * 2000, b'x' * (ww.MAX_DECLARATION + 1),
                    b'{"roles":[],"roles":[]}']:
        capture_refusal(lambda payload=payload: ww.WakeBinding(payload, digest(payload)).verify())


@pytest.mark.parametrize('value', [float('inf'), float('nan'), -float('inf'), 10**1000],
                         ids=['inf', 'nan', 'minus-inf', 'overflow'])
def test_policy_clocks_refuse_unrepresentable_values(value: Any) -> None:
    for field in ['poll_seconds', 'min_spacing_seconds']:
        capture_refusal(lambda field=field: policy(**{field: value}))


def test_technical_bounds_and_zero_spacing_and_cap_twins() -> None:
    assert policy(max_pokes=0, min_spacing_seconds=0)
    assert policy(max_pokes=64, max_files=ww.MAX_FILES, max_bytes=ww.MAX_BYTES)
    for change in [{'max_pokes': 65}, {'max_files': ww.MAX_FILES + 1}, {'max_bytes': ww.MAX_BYTES + 1},
                   {'literal': '\ud800'}]:
        capture_refusal(lambda change=change: policy(**change))


def test_state_methods_refuse_malformed_inputs_without_consuming_a_valid_target() -> None:
    state = ww.WakeState(policy(), ('worker-a',))
    bad_roles: list[Any] = [None, [], {}, 'undeclared']
    for role in bad_roles:
        capture_refusal(lambda role=role: state.offer(role, BASE, 0))  # type: ignore[arg-type]
        assert state.events[-1]['event'] == 'poke-refused'
    assert state.slots['worker-a'].phase == 'running'
    bad_pokes: list[Any] = [None, [], {}, True]
    for value in bad_pokes:
        assert state.dispatch(value, BASE, current_role='worker-a', current_session=SID,
                              idle=True, live=True, now=0) is False  # type: ignore[arg-type]
    assert state.slots['worker-a'].pokes == 0
    assert state.report('UNKNOWN')['poke_count'] == 0


def test_shape_population_and_healthy_twins() -> None:
    assert len(SHAPES) == 275
    assert ww.parse_policy(declaration()['controller_wake']) == policy()
    assert ww.parse_revision(asdict(BASE)) == BASE
    assert ww.parse_poke({'role': 'worker-a', 'session': SID, 'revision': BASE.identity, 'nonce': NONCE})


@pytest.mark.parametrize('kind', ['state', 'binding'])
def test_state_and_binding_envelopes_are_closed(kind: str) -> None:
    raw = declaration()
    value: dict[str, Any] = ({'policy': raw['controller_wake'], 'roles': raw['roles']} if kind == 'state' else
             {'declaration': canonical(raw), 'approved_digest': digest(canonical(raw))})
    parse = ww.parse_state if kind == 'state' else ww.parse_binding
    assert parse(value)
    for key in [*value, 'unknown']:
        changed = copy.deepcopy(value)
        if key == 'unknown':
            changed[key] = None
        else:
            del changed[key]
        capture_refusal(lambda changed=changed: parse(changed))


def test_population_and_identity_boundary_twins() -> None:
    for names in [[], ['worker-a', 'worker-a'], ['worker-a'] * (ww.MAX_ROLES + 1)]:
        raw = declaration()
        raw['roles'] = names
        capture_refusal(lambda raw=raw: ww.bind_declaration(raw, digest(canonical(raw))))
    for key, value in [('session', SID + '\n'), ('nonce', NONCE + '\n'),
                       ('revision', BASE.identity.upper()), ('role', 'worker-a\n')]:
        values = {'role': 'worker-a', 'session': SID, 'revision': BASE.identity, 'nonce': NONCE}
        values[key] = value
        capture_refusal(lambda values=values: ww.parse_poke(values))


@pytest.mark.parametrize('value', [None, True, [], {}, 'claimed'],
                         ids=['null', 'bool', 'list', 'dict', 'text'])
def test_invalid_observer_return_never_starts_roles(tmp_path: Path, value: Any) -> None:
    from test_wave_wake import PolicyClock

    from skillc.completion import CompletionDeadline
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    clock = PolicyClock()
    wave.deadline = CompletionDeadline.after(.005, clock)
    def advance(seconds: float) -> None:
        clock.value += seconds
    report = ww.drive(wave, policy(), read_revision=lambda: value, clock=clock, sleep=advance)
    assert report['outcome'] == 'DEADLINE' and not wave.calls and wave.closed


@pytest.mark.parametrize('value', [None, True, 1, 1.5, 'policy', [], {}],
                         ids=['null', 'bool', 'int', 'float', 'text', 'list', 'dict'])
def test_existing_state_constructor_refuses_unparsed_policy(value: Any) -> None:
    capture_refusal(lambda: ww.WakeState(value, ('worker-a',)))


@pytest.mark.parametrize('payload', [
    ('{"files":"' + BASE.files + '","files":"' + BASE.files + '","refs":"' + BASE.refs + '"}').encode(),
    b'[' * 2000,
], ids=['duplicate-digest', 'deep-json'])
def test_existing_observer_refuses_duplicate_or_deep_response(payload: bytes) -> None:
    from types import SimpleNamespace

    from skillc.backend import BackendUnavailable
    wave = SimpleNamespace(remote=object(), _name=lambda _: 'controller-helper', _call=lambda _: payload)
    try:
        ww.observe(wave, policy())
    except Exception as exc:  # noqa: BLE001 - generic recursion is not a controlled unavailable verdict
        assert isinstance(exc, BackendUnavailable), type(exc).__name__
    else:
        raise AssertionError('ambiguous controller observation accepted')
