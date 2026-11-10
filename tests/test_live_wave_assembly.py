"""New-instrument authored assembly qualification, not a live producer/run."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
import test_wave_export as exported
from test_wave_wake import BASE, FILE, policy

from skillc import controller_turns, live_wave, wave_capture, wave_wake, wave_wake_capture
from skillc import live_wave_assembly as assembly
from skillc.backend import ExecuteResult

ROOT = Path(__file__).resolve().parents[1]
CONTROL = json.loads((ROOT / 'controls/live-wave-assembly/fixture.json').read_text())
CASES = json.loads((ROOT / 'controls/live-wave-assembly/cases.json').read_text())
MUTANTS = json.loads((ROOT / 'controls/live-wave-assembly/mutants.json').read_text())
DIGEST = 'sha256:' + 'ab' * 32
GRADER_DIGEST = 'sha256:' + 'cd' * 32


def raw_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def graded(plan: live_wave.WavePlan, artifacts: Any) -> live_wave.DeliveryGrade:
    expected = {'worker': json.loads(artifacts['worker']['output.json'])}
    actual = json.loads(artifacts[plan.integrator]['output.json'])
    return live_wave.DeliveryGrade('PASS' if actual == expected else 'FAIL', CONTROL['grader_elapsed'])


def fixture(tmp_path: Path, *, alter: Callable[[Path, dict[str, Any], dict[str, Any]], None] | None = None,
            ) -> tuple[Path, assembly.Expected, dict[str, assembly.Grader], dict[str, Any]]:
    source, declaration, catalogue = exported.fixture(tmp_path)
    entries = catalogue['entries']
    def directory(rel: str, mode: int = 0o755) -> None:
        parts = Path(rel).parts
        for i in range(1, len(parts) + 1):
            name = Path(*parts[:i]).as_posix()
            if name not in entries:
                (source / name).mkdir(exist_ok=True)
                (source / name).chmod(mode)
                entries[name] = {'kind': 'directory', 'mode': mode}
    def write(rel: str, data: bytes, mode: int = 0o600) -> None:
        directory(str(Path(rel).parent))
        (source / rel).write_bytes(data)
        (source / rel).chmod(mode)
        entries[rel] = {'kind': 'file', 'mode': mode, 'bytes': len(data), 'sha256': exported.sha(data)}
    def record(wave: dict[str, Any], role: str | None, kind: str, name: str, data: bytes) -> dict[str, Any]:
        slot = next((r for r in wave['records'] if r['role'] == role and r['kind'] == kind), None)
        if slot is None:
            slot = {'id': (role or 'wave') + '-' + name, 'kind': kind, 'role': role,
                    'availability': 'CAPTURED', 'path': wave['wave_id'] + '/' + (role or 'wave') + '/' + name,
                    'reason': None}
            wave['records'].append(slot)
        write(slot['path'], data)
        return {'slot': slot['id'], 'path': slot['path'], 'size': len(data), 'sha256': exported.sha(data)}
    planned_rows = []
    for index, wave in enumerate(catalogue['waves']):
        bindings = [{'role': role, 'attempt_id': wave['wave_id'] + '-' + role,
                     'session_id': f'00000000-0000-0000-0000-{number + 1:012x}' if index == 0 else None,
                     'task': role, 'generation': 0, 'revision': 1, 'nonce': 'task-nonce-' + role,
                     'required_artifacts': ['output.json']} for number, role in enumerate(CONTROL['roles'])]
        planned_rows.append({'plan': {'wave_id': wave['wave_id'], 'roles': bindings,
                                      'integrator': 'integrator', 'deadline': CONTROL['deadline']},
                             'budget_digest': DIGEST, 'clock': CONTROL['clock'], 'grader_digest': GRADER_DIGEST})
    planned = assembly.freeze_plan({'version': 1, 'declaration_digest': catalogue['declaration_digest'],
                                    'waves': planned_rows})
    rows = []
    graders = {}
    for index, wave in enumerate(catalogue['waves']):
        wave_id = wave['wave_id']
        row = copy.deepcopy(planned_rows[index])
        captures: list[dict[str, Any]] = []
        row.update(observation=None, roles=captures, wake=None, final=None)
        bindings = row['plan']['roles']
        common = {'version': 1, 'wave_id': wave_id, 'budget_digest': DIGEST, 'clock': CONTROL['clock']}
        for number, role in enumerate(CONTROL['roles']):
            binding = bindings[number]
            session = binding['session_id']
            capture: dict[str, Any] = {'role': role, 'startup': None, 'observation': None,
                                       'transcript': None, 'protocol': None, 'artifacts': None}
            captures.append(capture)
            if index:
                continue  # A real planned nonstart slot; never invented captures.
            startup = f'OpenAI Codex v0.157.1\n--------\nsession id: {session}\n--------\n'.encode()
            assert controller_turns.session_id_from_header(startup) == session
            capture['startup'] = record(wave, role, 'stderr', 'startup', startup)
            observed = {**common, 'role': role, 'attempt_id': binding['attempt_id'], 'session_id': session,
                        'started': True, 'stopped': True, 'cleanup_confirmed': True, 'capture_complete': True,
                        'stop_reason': 'exited', 'exit_code': 0, 'stop_elapsed': 5, 'tokens': None, 'wall_seconds': None}
            capture['observation'] = record(wave, role, 'role-report', 'observation', raw_json(observed))
            transcript = raw_json({'type': 'session_meta', 'payload': {'id': session}}) + b'\n'
            capture['transcript'] = record(wave, role, 'transcript', 'transcript', transcript)
            events = [{**{k: binding[k] for k in ('role', 'attempt_id', 'session_id', 'task', 'generation', 'revision', 'nonce')},
                       'wave_id': wave_id, 'op': op, 'elapsed': elapsed} for op, elapsed in CONTROL['events'][role]]
            capture['protocol'] = record(wave, role, 'protocol', 'protocol', b''.join(raw_json(e) + b'\n' for e in events))
            result = {'worker': CONTROL['worker_result']} if role == 'integrator' else CONTROL['worker_result']
            capture['artifacts'] = {'output.json': record(wave, role, 'artifact', 'artifact', raw_json(result))}
        if not index:
            observed_wave = {**common, 'status': 'UNKNOWN', 'completion_elapsed': CONTROL['completion_elapsed'],
                             'cleanup_confirmed': True, 'infrastructure_failed_at': None,
                             'deadline_witnessed_at': None, 'abandonment': False}
            row['observation'] = record(wave, None, 'wave-report', 'wave-observation', raw_json(observed_wave))
            capture_root = next(r['path'] for r in wave['records'] if r['role'] == 'integrator' and r['kind'] == 'capture')
            wake_root = capture_root + '/wake'
            wake_policy = replace(policy(), max_pokes=1)
            context = wave_wake_capture.Context(wave_id, catalogue['declaration_digest'], wake_policy.digest,
                                                tuple(CONTROL['roles']), DIGEST, CONTROL['clock'])
            count_capture = wave_wake_capture.Capture(source / wake_root, context, 0)
            state = wave_wake.WakeState(wake_policy, context.roles)
            def journal(event: Mapping[str, Any], retained: wave_wake_capture.Capture = count_capture) -> None:
                retained.append(dict(event))
            state.journal = journal
            for binding in bindings:
                role, session = binding['role'], binding['session_id']
                state.ended(role, session, ExecuteResult('exited', 0), BASE, 0)
            for binding in bindings:
                role, session = binding['role'], binding['session_id']
                poke = state.offer(role, FILE, 1)
                assert poke is not None
                assert state.dispatch(poke, FILE, current_role=role, current_session=session, idle=True, live=True, now=1)
            for binding in bindings:
                role, session = binding['role'], binding['session_id']
                state.ended(role, session, ExecuteResult('exited', 0), FILE, 5)
            reference = count_capture.seal('STOPPED', [{'role': r['role'], 'session_id': r['session_id']} for r in bindings])
            # Explicit known writes, not a production scan that could go blind.
            directory(wake_root, 0o700)
            directory(wake_root + '/objects', 0o700)
            object_path = wake_root + '/objects/' + reference.digest[7:]
            object_bytes = (source / object_path).read_bytes()
            entries[object_path] = {'kind': 'file', 'mode': 0o400, 'bytes': len(object_bytes),
                                    'sha256': exported.sha(object_bytes)}
            row['wake'] = {'root': wake_root, 'reference': asdict(reference), 'context': asdict(context)}
            final_root = capture_root + '/final'
            for surface in wave_capture.SURFACES:
                directory(final_root + '/' + surface)
                write(final_root + '/' + surface + '/opaque', b'authored controller final bytes')
            manifest = raw_json(wave_capture.manifest(source / final_root, {}))
            write(final_root + '/' + wave_capture.MANIFEST, manifest)
            row['final'] = {'root': final_root, 'sha256': exported.sha(manifest)}
        rows.append(row)
        graders[wave_id] = assembly.Grader(GRADER_DIGEST, DIGEST, CONTROL['clock'], graded)
    raw = {'version': 1, 'declaration_digest': catalogue['declaration_digest'], 'waves': rows}
    if alter is not None:
        alter(source, catalogue, raw)
    sealed = tmp_path / 'sealed'
    held_export = exported.we.freeze(source, declaration, exported.we.ControllerCatalogue.from_controller(catalogue), sealed)
    arrival = tmp_path / 'arrival'
    arrival.mkdir(mode=0o700)
    shutil.copy2(sealed / exported.we.MANIFEST, arrival / exported.we.MANIFEST)
    shutil.copytree(source, arrival / 'payload')
    return arrival, assembly.freeze(raw, held_export, planned), graders, raw


def replace_capture(source: Path, catalogue: dict[str, Any], reference: dict[str, Any], data: bytes) -> None:
    """Authored controller inventory change before sealing, never a replay repair."""
    (source / reference['path']).write_bytes(data)
    digest = exported.sha(data)
    catalogue['entries'][reference['path']].update(bytes=len(data), sha256=digest)
    reference.update(size=len(data), sha256=digest)


def edit_metadata(source: Path, catalogue: dict[str, Any], reference: dict[str, Any], patch: dict[str, Any]) -> None:
    value = json.loads((source / reference['path']).read_bytes())
    value.update(patch)
    replace_capture(source, catalogue, reference, raw_json(value))


def test_authored_protocol_and_real_sealed_counts_assemble_healthy_wave_and_nonstart(tmp_path: Path) -> None:
    arrival, expected, graders, _raw = fixture(tmp_path)
    result = assembly.report(arrival, expected, graders)
    assert result['primary'] == {'unit': 'wave', 'planned': 2, 'completed': 1, 'pass': 1, 'fail': 0, 'unknown': 1}
    assert result['waves'][0]['roles']['worker']['pokes'] == 1
    assert result['waves'][0]['metrics']['tokens'] is None
    assert result['waves'][0]['metrics']['handoff_timings'] is None
    assert result['coverage']['live_authority'] is False


@pytest.mark.parametrize('field', ['observation', 'wake', 'final'])
def test_required_wave_source_absence_is_unknown(tmp_path: Path, field: str) -> None:
    arrival, expected, graders, raw = fixture(tmp_path)
    raw['waves'][0][field] = None
    result = assembly.report(arrival, assembly.freeze(raw, expected.exported, expected.planned), graders)
    assert result['primary']['planned'] == 2 and result['primary']['unknown'] == 2


@pytest.mark.parametrize('field', ['startup', 'observation', 'transcript', 'protocol', 'artifacts'])
def test_required_role_source_absence_is_unknown(tmp_path: Path, field: str) -> None:
    arrival, expected, graders, raw = fixture(tmp_path)
    raw['waves'][0]['roles'][0][field] = None
    result = assembly.report(arrival, assembly.freeze(raw, expected.exported, expected.planned), graders)
    assert result['primary']['planned'] == 2 and result['primary']['unknown'] == 2


def alteration(case: dict[str, Any]) -> Callable[[Path, dict[str, Any], dict[str, Any]], None]:
    def change(source: Path, catalogue: dict[str, Any], raw: dict[str, Any]) -> None:
        row, wave = raw['waves'][0], catalogue['waves'][0]
        role = row['roles'][0]
        kind = case['kind']
        if kind == 'none':
            return
        if kind == 'missing-wave':
            row[case['field']] = None
        elif kind == 'missing-role':
            role[case['field']] = None
        elif kind == 'role-metadata':
            edit_metadata(source, catalogue, role['observation'], case['patch'])
        elif kind == 'wave-metadata':
            edit_metadata(source, catalogue, row['observation'], case['patch'])
        elif kind in ('alternative', 'wrong-role', 'duplicate', 'unfinished', 'positive-missing'):
            ref = role['protocol']
            events = [json.loads(line) for line in (source / ref['path']).read_bytes().splitlines()]
            if kind == 'alternative':
                events[0]['elapsed'] = 1.5
            elif kind in ('wrong-role', 'positive-missing'):
                events[0]['role'] = 'worker'
            elif kind == 'duplicate':
                events.append(copy.deepcopy(events[-1]))
            else:
                events = events[:1]
            replace_capture(source, catalogue, ref, b''.join(raw_json(e) + b'\n' for e in events))
            if kind == 'positive-missing':
                row['roles'][1]['transcript'] = None
        elif kind in ('bad-artifact', 'infra-artifact'):
            replace_capture(source, catalogue, role['artifacts']['output.json'], b'{}')
            if kind == 'infra-artifact':
                edit_metadata(source, catalogue, row['observation'], {'infrastructure_failed_at': 3})
                for captured in row['roles']:
                    edit_metadata(source, catalogue, captured['observation'], {'stop_reason': 'infrastructure-cancelled'})
        elif kind in ('swap', 'swap-valid'):
            path = row['wake']['root'] + '/objects/' + row['wake']['reference']['digest'][7:]
            target = source / path
            original = target.read_bytes()
            if kind == 'swap-valid':
                events = [json.loads(line) for line in original.splitlines()]
                nonce = next(e['nonce'] for e in events if e['event'] == 'poke-attempt')
                replacement = 'f' * 32 if nonce != 'f' * 32 else 'e' * 32
                for event in events:
                    if event.get('nonce') == nonce:
                        event['nonce'] = replacement
                previous = wave_wake_capture.ZERO
                lines = []
                for seq, event in enumerate(events, 1):
                    event.update(seq=seq, prev_hash=previous)
                    if event['event'] == 'capture-seal':
                        event['last_hash'] = previous
                    line = raw_json(event) + b'\n'
                    lines.append(line)
                    previous = hashlib.sha256(line).hexdigest()
                swapped = b''.join(lines)
                assert len(swapped) == len(original)
                ref = wave_wake_capture.parse_reference(row['wake']['reference'])
                context = wave_wake_capture.parse_context(row['wake']['context'])
                valid_alternate = wave_wake_capture._decode(swapped, replace(ref, digest=exported.sha(swapped)), context)
                assert valid_alternate['status'] == 'CAPTURED' and valid_alternate['complete'] is True
            else:
                swapped = original.replace(b'"poke":1', b'"poke":2', 1)
            assert original != swapped and len(original) == len(swapped)
            target.chmod(0o600)
            target.write_bytes(swapped)
            target.chmod(0o400)
            catalogue['entries'][path]['sha256'] = exported.sha(swapped)
            # Keep the independently held INNER receipt: outer integrity alone is insufficient.
        elif kind == 'wake-ref':
            row['wake']['reference']['digest'] = 'sha256:' + '00' * 32
        elif kind == 'forged':
            role['protocol'] = None
            edit_metadata(source, catalogue, row['observation'], {'status': 'PASS'})
            wave['task_status'] = 'PASS'  # Captured projection is a lie, not grader evidence.
        else:
            raise AssertionError('unknown committed assembly control')
    return change


@pytest.mark.parametrize('case', CASES, ids=lambda row: row['name'])
def test_committed_new_instrument_controls(tmp_path: Path, case: dict[str, Any]) -> None:
    arrival, expected, graders, _raw = fixture(tmp_path, alter=alteration(case))
    result = assembly.report(arrival, expected, graders)
    assert result['primary']['planned'] == 2
    assert result['waves'][0]['status'] == case['expected'], result
    assert result['waves'][1]['status'] == 'UNKNOWN'


def _blind_protocol(plan: live_wave.WavePlan, binding: live_wave.RoleBinding) -> live_wave.Blob:
    rows = [{**asdict(binding), 'wave_id': plan.wave_id, 'op': op, 'elapsed': elapsed}
            for op, elapsed in [('ack', 1), ('complete', 2)]]
    for row in rows:
        del row['required_artifacts']
    data = b''.join(raw_json(row) + b'\n' for row in rows)
    return live_wave.Blob(data, hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize('mutant', MUTANTS, ids=lambda row: row['name'])
def test_actual_blind_assembler_variants_lose_committed_witness(tmp_path: Path, mutant: dict[str, str]) -> None:
    case = next(row for row in CASES if row['name'] == mutant['witness'])
    arrival, expected, graders, raw = fixture(tmp_path, alter=alteration(case))
    original = assembly.report(arrival, expected, graders)
    assert original['primary']['planned'] == 2 and original['waves'][0]['status'] == case['expected']
    source = inspect.getsource(assembly._assemble) + '\n' + inspect.getsource(assembly.report)
    assert source.count(mutant['before']) == 1
    namespace = {**vars(assembly), '_blind_protocol': _blind_protocol,
                 '_blind_counts': lambda *_a: tuple(live_wave.PokeCount(r['role'], r['session_id'], 999)
                                                  for r in raw['waves'][0]['plan']['roles'])}
    exec(compile(source.replace(mutant['before'], mutant['after']), '<blind-assembler>', 'exec'), namespace)  # noqa: S102
    result = namespace['report'](arrival, expected, graders)
    with pytest.raises(AssertionError):
        assert result['primary']['planned'] == 2 and result['waves'][0]['status'] == case['expected']


@pytest.mark.parametrize('fault', ['missing', 'digest', 'budget', 'clock', 'noncallable', 'raises', 'late', 'untimed'],
                         ids=['missing', 'digest', 'budget', 'clock', 'noncallable', 'raises', 'late', 'untimed'])
def test_grader_and_common_clock_do_not_come_from_a_projection(tmp_path: Path, fault: str) -> None:
    arrival, expected, graders, _raw = fixture(tmp_path)
    key = 'synthetic-wave-1'
    current = graders[key]
    if fault == 'missing':
        del graders[key]
    elif fault in ('digest', 'budget'):
        graders[key] = (replace(current, digest='sha256:' + 'ff' * 32) if fault == 'digest'
                        else replace(current, budget_digest='sha256:' + 'ff' * 32))
    elif fault == 'clock':
        graders[key] = replace(current, clock='monotonic')
    elif fault == 'noncallable':
        graders[key] = replace(current, grade=None)  # type: ignore[arg-type]
    elif fault == 'raises':
        def unavailable(*_args: Any) -> Any:
            raise KeyError('private-marker must not become public diagnostics')
        graders[key] = replace(current, grade=unavailable)
    else:
        graders[key] = replace(current, grade=lambda p, a: live_wave.DeliveryGrade('PASS', 11 if fault == 'late' else None))
    result = assembly.report(arrival, expected, graders)
    assert result['waves'][0]['status'] == ('FAIL' if fault == 'late' else 'UNKNOWN')
    assert result['primary']['planned'] == 2 and 'private-marker' not in json.dumps(result)


def test_grader_failure_does_not_erase_independently_observed_protocol_violation(tmp_path: Path) -> None:
    case = next(r for r in CASES if r['name'] == 'wrong-role')
    arrival, expected, graders, _raw = fixture(tmp_path, alter=alteration(case))
    def unavailable(*_args: Any) -> Any:
        raise KeyError('synthetic grading unavailable')
    graders['synthetic-wave-1'] = replace(graders['synthetic-wave-1'], grade=unavailable)
    result = assembly.report(arrival, expected, graders)
    assert result['waves'][0]['status'] == 'FAIL' and result['waves'][0]['unknown']


def test_missing_arrival_cannot_shrink_original_planned_denominator(tmp_path: Path) -> None:
    arrival, expected, graders, _raw = fixture(tmp_path)
    (arrival / exported.we.MANIFEST).unlink()
    result = assembly.report(arrival, expected, graders)
    assert result['primary'] == {'unit': 'wave', 'planned': 2, 'completed': 0, 'pass': 0, 'fail': 0, 'unknown': 2}


def test_public_result_does_not_echo_private_roots_or_captured_content(tmp_path: Path) -> None:
    base = tmp_path / 'owner-private-marker'
    base.mkdir()
    arrival, expected, graders, _raw = fixture(base)
    # Mutable reports outside the independently retained bundle have no input role.
    (base / 'wake-report.json').write_text('{"status":"PASS","pokes":999,"tokens":999}')
    result = assembly.report(arrival, expected, graders)
    public = json.dumps(result)
    assert result['waves'][0]['status'] == 'PASS'
    assert 'owner-private-marker' not in public and str(base) not in public
    assert 'owner-private-marker' in json.dumps({**result, 'private_root': str(base)})


def test_valid_zero_attempts_are_derived_from_a_real_sealed_population(tmp_path: Path) -> None:
    def zero(source: Path, catalogue: dict[str, Any], raw: dict[str, Any]) -> None:
        row = raw['waves'][0]
        zero_policy = replace(policy(), max_pokes=0)
        context = wave_wake_capture.parse_context({**row['wake']['context'], 'policy_digest': zero_policy.digest})
        root = row['wake']['root'] + '-zero'
        capture = wave_wake_capture.Capture(source / root, context, 0)
        state = wave_wake.WakeState(zero_policy, context.roles)
        state.journal = lambda event: capture.append(dict(event))
        for role in row['plan']['roles']:
            state.ended(role['role'], role['session_id'], ExecuteResult('exited', 0), BASE, 0)
        ref = capture.seal('STOPPED', [{'role': r['role'], 'session_id': r['session_id']} for r in row['plan']['roles']])
        for path in (root, root + '/objects'):
            catalogue['entries'][path] = {'kind': 'directory', 'mode': 0o700}
        path = root + '/objects/' + ref.digest[7:]
        data = (source / path).read_bytes()
        catalogue['entries'][path] = {'kind': 'file', 'mode': 0o400, 'bytes': len(data), 'sha256': exported.sha(data)}
        row['wake'] = {'root': root, 'reference': asdict(ref), 'context': asdict(context)}
    arrival, expected, graders, _raw = fixture(tmp_path, alter=zero)
    result = assembly.report(arrival, expected, graders)
    assert result['waves'][0]['status'] == 'PASS'
    assert {r['pokes'] for r in result['waves'][0]['roles'].values()} == {0}


def test_capture_drift_during_grading_never_earns_a_pass(tmp_path: Path) -> None:
    arrival, expected, graders, raw = fixture(tmp_path)
    path = arrival / 'payload' / raw['waves'][0]['roles'][0]['artifacts']['output.json']['path']
    def drift(plan: live_wave.WavePlan, artifacts: Any) -> live_wave.DeliveryGrade:
        judgement = graded(plan, artifacts)
        path.write_bytes(b'changed after verified read')
        return judgement
    graders['synthetic-wave-1'] = replace(graders['synthetic-wave-1'], grade=drift)
    result = assembly.report(arrival, expected, graders)
    assert result['waves'][0]['status'] == 'UNKNOWN'
    assert 'export-custody-unavailable' in result['waves'][0]['unknown']


@pytest.mark.parametrize('damage', ['missing', 'linked', 'directory', 'fifo', 'final-parent-link'])
def test_capture_file_types_cannot_be_observed_as_complete(tmp_path: Path, damage: str) -> None:
    arrival, expected, graders, raw = fixture(tmp_path)
    if damage == 'final-parent-link':
        path = arrival / 'payload' / raw['waves'][0]['final']['root']
        other = tmp_path / 'held-final-copy'
        shutil.move(path, other)
        path.symlink_to(other, target_is_directory=True)
    else:
        path = arrival / 'payload' / raw['waves'][0]['roles'][0]['transcript']['path']
        path.unlink()
        if damage == 'linked':
            path.symlink_to(tmp_path / 'absent-private-marker')
        elif damage == 'directory':
            path.mkdir()
        elif damage == 'fifo':
            import os
            os.mkfifo(path)
    result = assembly.report(arrival, expected, graders)
    assert result['primary']['planned'] == 2 and result['waves'][0]['status'] == 'UNKNOWN'


@pytest.mark.parametrize('field,value', [('deadline', 11), ('integrator', 'worker')], ids=['deadline', 'integrator'])
def test_later_capture_contract_cannot_reselect_the_original_plan(tmp_path: Path, field: str, value: Any) -> None:
    _arrival, expected, _graders, raw = fixture(tmp_path)
    original = expected.planned.data
    raw['waves'][0]['plan'][field] = value
    with pytest.raises(assembly.AssemblyRefused, match='original plan'):
        assembly.freeze(raw, expected.exported, expected.planned)
    assert expected.planned.data == original


def test_input_aliases_cannot_mutate_frozen_capture_or_original_plan(tmp_path: Path) -> None:
    arrival, expected, graders, raw = fixture(tmp_path)
    original = (expected.data, expected.planned.data)
    raw['waves'].clear()
    assert assembly.report(arrival, expected, graders)['primary']['planned'] == 2
    assert (expected.data, expected.planned.data) == original
