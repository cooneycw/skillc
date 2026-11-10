"""New-instrument authored assembly qualification, not a live producer/run."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
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
DIGEST = 'sha256:' + 'ab' * 32
GRADER_DIGEST = 'sha256:' + 'cd' * 32


def raw_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def graded(plan: live_wave.WavePlan, artifacts: Any) -> live_wave.DeliveryGrade:
    expected = {'worker': json.loads(artifacts['worker']['output.json'])}
    actual = json.loads(artifacts[plan.integrator]['output.json'])
    return live_wave.DeliveryGrade('PASS' if actual == expected else 'FAIL', CONTROL['grader_elapsed'])


def fixture(tmp_path: Path) -> tuple[Path, assembly.Expected, dict[str, assembly.Grader], dict[str, Any]]:
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
    rows = []
    graders = {}
    for index, wave in enumerate(catalogue['waves']):
        wave_id = wave['wave_id']
        bindings, captures = [], []
        row: dict[str, Any] = {'plan': {'wave_id': wave_id, 'roles': bindings, 'integrator': 'integrator',
                                      'deadline': CONTROL['deadline']},
                              'budget_digest': DIGEST, 'clock': CONTROL['clock'], 'grader_digest': GRADER_DIGEST,
                              'observation': None, 'roles': captures, 'wake': None, 'final': None}
        common = {'version': 1, 'wave_id': wave_id, 'budget_digest': DIGEST, 'clock': CONTROL['clock']}
        for number, role in enumerate(CONTROL['roles']):
            session = f'00000000-0000-0000-0000-{index * 10 + number + 1:012x}' if index == 0 else None
            binding = {'role': role, 'attempt_id': wave_id + '-' + role, 'session_id': session,
                       'task': role, 'generation': 0, 'revision': 1, 'nonce': 'task-nonce-' + role,
                       'required_artifacts': ['output.json']}
            bindings.append(binding)
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
            capture = wave_wake_capture.Capture(source / wake_root, context, 0)
            state = wave_wake.WakeState(wake_policy, context.roles)
            state.journal = capture.append
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
            reference = capture.seal('STOPPED', [{'role': r['role'], 'session_id': r['session_id']} for r in bindings])
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
    sealed = tmp_path / 'sealed'
    held_export = exported.we.freeze(source, declaration, exported.we.ControllerCatalogue.from_controller(catalogue), sealed)
    arrival = tmp_path / 'arrival'
    arrival.mkdir(mode=0o700)
    shutil.copy2(sealed / exported.we.MANIFEST, arrival / exported.we.MANIFEST)
    shutil.copytree(source, arrival / 'payload')
    raw = {'version': 1, 'declaration_digest': catalogue['declaration_digest'], 'waves': rows}
    return arrival, assembly.freeze(raw, held_export), graders, raw


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
    result = assembly.report(arrival, assembly.freeze(raw, expected.exported), graders)
    assert result['primary']['planned'] == 2 and result['primary']['unknown'] == 2


@pytest.mark.parametrize('field', ['startup', 'observation', 'transcript', 'protocol', 'artifacts'])
def test_required_role_source_absence_is_unknown(tmp_path: Path, field: str) -> None:
    arrival, expected, graders, raw = fixture(tmp_path)
    raw['waves'][0]['roles'][0][field] = None
    result = assembly.report(arrival, assembly.freeze(raw, expected.exported), graders)
    assert result['primary']['planned'] == 2 and result['primary']['unknown'] == 2
