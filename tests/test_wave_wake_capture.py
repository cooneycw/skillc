"""New-instrument custody qualification; no absent-API baseline reds claimed."""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from test_wave_wake import BASE, FILE, SID, ScriptedWave, policy

from skillc import wave_wake as ww
from skillc import wave_wake_capture as wc
from skillc.backend import ExecuteResult

SID_B = SID[:-1] + '2'
FINAL = [{'role': 'worker-a', 'session_id': SID}, {'role': 'worker-b', 'session_id': SID_B}]


def context() -> wc.Context:
    return wc.Context('model-wave', BASE.identity, policy().digest, ('worker-a', 'worker-b'),
                      BASE.identity, 'injected-policy-only')


def authored(root: Path) -> tuple[wc.Reference, bytes]:
    capture = wc.Capture(root, context(), 0)
    state = ww.WakeState(policy(), context().roles)
    state.journal = lambda event: capture.append(dict(event))
    state.ended('worker-a', SID, ExecuteResult('exited', 0), BASE, 0)
    state.ended('worker-b', SID_B, ExecuteResult('exited', 7), BASE, 0)
    poke = state.offer('worker-a', FILE, 1)
    assert poke is not None
    assert state.dispatch(poke, FILE, current_role='worker-a', current_session=SID, idle=True, live=True, now=1)
    state.ended('worker-a', SID, ExecuteResult('exited', 0), FILE, 2)
    ref = capture.seal('STOPPED', copy.deepcopy(FINAL))
    raw = (root / 'objects' / ref.digest[7:]).read_bytes()
    return ref, raw


def retain(root: Path, raw: bytes) -> wc.Reference:
    """Synthetic trusted-store input, independently naming even malformed bytes."""
    ref = wc.Reference(1, context().digest, 'sha256:' + hashlib.sha256(raw).hexdigest(), len(raw))
    path = root / 'objects' / ref.digest[7:]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(raw)
    return ref


def rechain(rows: list[dict[str, Any]]) -> bytes:
    previous = wc.ZERO
    lines = []
    for index, row in enumerate(rows, 1):
        row['seq'], row['prev_hash'] = index, previous
        if row.get('event') == 'capture-seal':
            row['last_hash'] = previous
        line = json.dumps(row, sort_keys=True).encode() + b'\n'
        lines.append(line)
        previous = hashlib.sha256(line).hexdigest()
    return b''.join(lines)


def test_counts_come_from_retained_stream_and_independently_held_reference(tmp_path: Path) -> None:
    root = tmp_path / 'capture'
    ref, raw = authored(root)
    value = wc.verify(root, ref, context())
    assert value['status'] == 'CAPTURED' and value['complete'] is True and value['poke_count'] == 1
    assert value['poke_counts'] == [{**FINAL[0], 'pokes': 1}, {**FINAL[1], 'pokes': 0}]
    (root / 'forged-report.json').write_text(json.dumps({'status': 'CAPTURED', 'complete': True,
        'poke_counts': [{**FINAL[0], 'pokes': 999}, {**FINAL[1], 'pokes': 999}]}))
    assert [row.pokes for row in wc.poke_counts(root, ref, context())] == [1, 0]
    assert raw.endswith(b'\n') and len(raw) == ref.size
    assert (root / 'objects' / ref.digest[7:]).stat().st_mode & 0o777 == 0o400
    assert not (root / 'events.tmp').exists()


@pytest.mark.parametrize('damage', ['missing', 'changed', 'same-size-valid-swap', 'truncated', 'append',
                                   'symlink', 'directory', 'fifo', 'objects-link', 'root-link'])
def test_custody_loss_cannot_promote_a_forged_count(tmp_path: Path, damage: str) -> None:
    root = tmp_path / 'capture'
    ref, raw = authored(root)
    assert wc.verify(root, ref, context())['status'] == 'CAPTURED'
    path = root / 'objects' / ref.digest[7:]
    if damage == 'objects-link':
        (root / 'objects').rename(root / 'moved')
        (root / 'objects').symlink_to(root / 'moved', target_is_directory=True)
    elif damage == 'root-link':
        moved = tmp_path / 'moved-root'
        root.rename(moved)
        root.symlink_to(moved, target_is_directory=True)
    else:
        path.unlink()
        if damage == 'missing':
            pass
        elif damage == 'symlink':
            other = tmp_path / 'other'
            other.write_bytes(raw)
            path.symlink_to(other)
        elif damage == 'directory':
            path.mkdir()
        elif damage == 'fifo':
            import os
            os.mkfifo(path)
        else:
            swapped = authored(tmp_path / 'other-capture')[1] if damage == 'same-size-valid-swap' else None
            if swapped is not None:
                assert len(swapped) == len(raw) and swapped != raw
            replacement = {'changed': b'changed', 'truncated': raw[:-1],
                           'append': raw + b'{}\n', 'same-size-valid-swap': swapped}[damage]
            assert isinstance(replacement, bytes)
            path.write_bytes(replacement)
    assert wc.verify(root, ref, context())['status'] == 'UNKNOWN'
    with pytest.raises(wc.CaptureUnavailable):
        wc.poke_counts(root, ref, context())


@pytest.mark.parametrize('field', ['attempt_id', 'approved_declaration_digest', 'policy_digest',
                                 'roles', 'deadline_digest', 'clock'])
def test_cross_bound_context_refuses_even_valid_bytes(tmp_path: Path, field: str) -> None:
    root = tmp_path / 'capture'
    ref, _raw = authored(root)
    changed: Any = {'attempt_id': 'other-wave', 'roles': tuple(reversed(context().roles)),
               'clock': 'monotonic'}.get(field, 'sha256:' + 'ef' * 32)
    expected = replace(context(), **{field: changed})
    assert wc.verify(root, ref, expected)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('damage', ['no-seal', 'duplicate-poke', 'wrong-session', 'missing-result',
                                   'duplicate-nonce', 'duplicate-key', 'bad-order', 'post-seal'])
def test_semantic_controls_are_not_masked_by_object_hash_mismatch(tmp_path: Path, damage: str) -> None:
    _reference, raw = authored(tmp_path / 'source')
    rows = [json.loads(line) for line in raw.splitlines()]
    poke = next(row for row in rows if row['event'] == 'poke-attempt')
    if damage == 'no-seal':
        rows.pop()
    elif damage == 'duplicate-poke':
        poke['poke'] += 1
    elif damage == 'wrong-session':
        poke['session'] = SID_B
    elif damage == 'missing-result':
        rows = [row for row in rows if not (row['event'] == 'turn-ended' and row['nonce'] is not None)]
        for index, row in enumerate(rows[1:-1], 1):
            row['order'] = index
        rows[-1]['events'] = len(rows) - 2
    elif damage == 'duplicate-nonce':
        copied = copy.deepcopy(poke)
        rows.insert(-1, copied)
        for index, row in enumerate(rows[1:-1], 1):
            row['order'] = index
        rows[-1]['events'] = len(rows) - 2
    elif damage == 'bad-order':
        poke['order'] += 1
    elif damage == 'post-seal':
        rows.append(copy.deepcopy(poke))
    planted = rechain(rows)
    if damage == 'duplicate-key':
        planted = planted.replace(b'"version": 1', b'"version": 1, "version": 1', 1)
    root = tmp_path / 'planted'
    reference = retain(root, planted)  # Known digest of the intentionally bad stream.
    assert wc.verify(root, reference, context())['status'] == 'UNKNOWN'


def test_writer_is_single_use_and_failed_record_cannot_be_sealed(tmp_path: Path) -> None:
    capture = wc.Capture(tmp_path / 'capture', context(), 0)
    ref = capture.seal('UNKNOWN', [{'role': row['role'], 'session_id': None} for row in FINAL])
    assert wc.verify(capture.root, ref, context())['complete'] is False
    with pytest.raises(ValueError):
        capture.append({})
    with pytest.raises(ValueError):
        capture.seal('UNKNOWN', FINAL)
    assert wc.verify(capture.root, ref, context())['status'] == 'CAPTURED'
    broken = wc.Capture(tmp_path / 'broken', context(), 0)
    with pytest.raises(ValueError):
        broken.append({'seq': 2})
    with pytest.raises(ValueError):
        broken.seal('UNKNOWN', FINAL)
    broken.close()


def last_synced_record(fd: int) -> dict[str, Any] | None:
    """Inspect the owned descriptor without moving the writer's offset."""
    try:
        raw = wc.os.pread(fd, wc.MAX_CAPTURE + 1, 0)
        row = json.loads(raw.splitlines()[-1])
        return row if type(row) is dict else None
    except (OSError, ValueError, IndexError):
        return None


def test_driver_fsyncs_attempt_before_transport_and_supplies_verified_adapter(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    seen: list[ww.Poke] = []
    trace: list[tuple[str, str]] = []
    succeeded: set[str] = set()
    pending: dict[str, str] = {}
    original_fsync = wc.os.fsync
    original_init = wc.Capture.__init__
    owned: dict[int, wc.Capture] = {}

    def capture_init(capture: wc.Capture, *args: Any, **kwargs: Any) -> None:
        original_init(capture, *args, **kwargs)
        owned[capture.stream.fileno()] = capture

    def fsync(fd: int) -> None:
        capture = owned.get(fd)
        row = (last_synced_record(fd) if capture is not None and not capture.stream.closed
               and capture.stream.fileno() == fd else None)
        original_fsync(fd)  # A visible write is insufficient: record only a successful barrier.
        if row is not None and row.get('event') == 'poke-attempt':
            succeeded.add(row['nonce'])
            trace.append(('fsync', row['nonce']))

    def delivered(poke: ww.Poke) -> bool:
        assert poke.nonce in succeeded, 'poke transport preceded its successful event fsync'
        trace.append(('deliver', poke.nonce))
        pending[poke.role] = poke.nonce
        seen.append(poke)
        return True

    class QueueProof:
        def __init__(self, **kwargs: Any) -> None:
            self.pool = ThreadPoolExecutor(**kwargs)
        def submit(self, function: Any, *args: Any, **kwargs: Any) -> Any:
            if len(args) > 1:
                nonce = pending[args[0]]
                assert nonce in succeeded, 'resume queue preceded its successful event fsync'
                trace.append(('submit', nonce))
            return self.pool.submit(function, *args, **kwargs)
        def shutdown(self, **kwargs: Any) -> None:
            self.pool.shutdown(**kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wc.Capture, '__init__', capture_init)
        patch.setattr(wc.os, 'fsync', fsync)
        patch.setattr(ww, 'ThreadPoolExecutor', QueueProof)
        report = ww.drive(wave, policy(), read_revision=wave.read, deliver=delivered)
    assert len(seen) == 2 and report['wake_capture']['status'] == 'CAPTURED'
    for poke in seen:
        assert trace.index(('fsync', poke.nonce)) < trace.index(('deliver', poke.nonce))
        assert trace.index(('deliver', poke.nonce)) < trace.index(('submit', poke.nonce))
    counts = wc.poke_counts(wave.root / 'wake-capture', wave.wake_capture_reference, wave.wake_capture_context)
    assert [row.pokes for row in counts] == [1, 1]
    (wave.root / 'wake-report.json').write_text('{"poke_count":999,"poke_counts":[]}')
    assert [row.pokes for row in wc.poke_counts(wave.root / 'wake-capture', wave.wake_capture_reference,
                                              wave.wake_capture_context)] == [1, 1]


def test_durable_failure_blocks_poke_but_never_skips_owned_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    original = wc.Capture._append
    def fail(capture: wc.Capture, row: dict[str, Any]) -> None:
        if row['event'] == 'poke-attempt':
            capture.failed = True
            raise OSError('synthetic capture failure')
        original(capture, row)
    monkeypatch.setattr(wc.Capture, '_append', fail)
    with pytest.raises(OSError, match='synthetic capture failure'):
        ww.drive(wave, policy(), read_revision=wave.read)
    assert wave.closed and all(text is None for _, text, _ in wave.calls)
    assert wave.wake_capture_reference is None
    report = json.loads((wave.root / 'wake-report.json').read_text())
    assert report['outcome'] == 'UNKNOWN' and report['wake_capture']['status'] == 'UNKNOWN'
    assert report['poke_count'] == 1  # Known in-process attempt is not invented zero/null.


def compiled(function: Any, before: str, after: str, namespace: dict[str, Any]) -> None:
    source = inspect.getsource(function)
    assert source.count(before) == 1
    exec(compile(source.replace(before, after), '<blind-wake-capture>', 'exec'), namespace)  # noqa: S102


def test_always_accept_capture_mutant_loses_missing_object_witness(tmp_path: Path) -> None:
    root = tmp_path / 'capture'
    ref, _ = authored(root)
    (root / 'objects' / ref.digest[7:]).unlink()
    assert wc.verify(root, ref, context())['status'] == 'UNKNOWN'
    namespace = dict(vars(wc))
    compiled(wc.verify, 'return _decode(_read(root, reference.digest, reference.size), reference, expected)',
             "return {'status': 'CAPTURED', 'complete': True}", namespace)
    with pytest.raises(AssertionError):
        assert namespace['verify'](root, ref, context())['status'] == 'UNKNOWN'


def test_hash_blind_mutant_loses_same_size_valid_swap_witness(tmp_path: Path) -> None:
    root = tmp_path / 'capture'
    ref, raw = authored(root)
    other = authored(tmp_path / 'other')[1]
    assert len(raw) == len(other) and raw != other
    target = root / 'objects' / ref.digest[7:]
    target.chmod(0o600)
    target.write_bytes(other)
    assert wc.verify(root, ref, context())['status'] == 'UNKNOWN'
    namespace = dict(vars(wc))
    compiled(wc._read, 'if _hash(raw) != digest:', 'if False:', namespace)
    compiled(wc._decode, '_hash(raw) != ref.digest', 'False', namespace)
    compiled(wc.verify, 'return _decode(', 'return _decode(', namespace)
    with pytest.raises(AssertionError):
        assert namespace['verify'](root, ref, context())['status'] == 'UNKNOWN'


def test_trust_projection_mutant_loses_raw_count_witness(tmp_path: Path) -> None:
    root = tmp_path / 'capture'
    ref, _ = authored(root)
    forged = {'status': 'CAPTURED', 'complete': True,
              'poke_counts': [{**row, 'pokes': 999} for row in FINAL]}
    (root / 'forged-report.json').write_text(json.dumps(forged))
    assert [row.pokes for row in wc.poke_counts(root, ref, context())] == [1, 0]
    namespace = dict(vars(wc))
    compiled(wc.poke_counts, 'result = verify(root, reference, expected)',
             "result = json.loads((root / 'forged-report.json').read_text())", namespace)
    with pytest.raises(AssertionError):
        assert [row.pokes for row in namespace['poke_counts'](root, ref, context())] == [1, 0]


SHAPES = json.loads((Path(__file__).resolve().parents[1] / 'controls/wave-wake/capture-shapes.json').read_text())


def event_input(kind: str) -> dict[str, Any]:
    fields: dict[str, dict[str, Any]] = {
        'turn-ended': {'reason': 'exited', 'exit_code': 0, 'session': SID, 'binding_session': SID,
                       'revision': BASE.identity, 'files': BASE.files, 'refs': BASE.refs, 'nonce': None},
        'poke-attempt': {'revision': BASE.identity, 'files': BASE.files, 'refs': BASE.refs,
                         'session': SID, 'nonce': 'ab' * 16, 'poke': 1},
        'poke-refused': {'reason': 'stale-session', 'nonce': 'ab' * 16},
        'poke-unconfirmed': {'nonce': 'ab' * 16}, 'role-ended': {'reason': 'max-pokes'},
        'role-stop-requested': {}, 'observation-unavailable': {}, 'observation-restored': {'missed': 1},
        'driver-unavailable': {'reason': 'OSError'},
    }
    return {'event': kind, 'role': '-' if kind.startswith('observation-') or kind == 'driver-unavailable'
            else 'worker-a', 'elapsed': 0, 'order': 1, **fields[kind]}


def change(value: Any, path: list[Any], replacement: Any) -> Any:
    if not path:
        return copy.deepcopy(replacement)
    cursor = value
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = copy.deepcopy(replacement)
    return value


@pytest.mark.parametrize('case', SHAPES, ids=lambda row: row['name'])
def test_every_new_capture_input_field_has_a_controlled_wrong_type(
    tmp_path: Path, case: dict[str, Any],
) -> None:
    kind = case['kind']
    if kind in ('context', 'reference', 'event'):
        original: Any = (json.loads(json.dumps(asdict(context()))) if kind == 'context' else
                         asdict(wc.Reference(1, context().digest, BASE.identity, 100)) if kind == 'reference'
                         else event_input(case['event']))
        parse = (wc.parse_context if kind == 'context' else wc.parse_reference if kind == 'reference'
                 else lambda value: wc._event(value, context().roles))
        assert parse(original)
        for invalid in case['invalid']:
            planted = change(copy.deepcopy(original), case['path'], invalid)
            with pytest.raises(ValueError):
                parse(planted)
    else:
        _ref, raw = authored(tmp_path / 'source')
        original_rows = [json.loads(line) for line in raw.splitlines()]
        for index, invalid in enumerate(case['invalid']):
            rows = copy.deepcopy(original_rows)
            target = 0 if kind == 'start' else -1
            rows[target] = change(rows[target], case['path'], invalid)
            previous = wc.ZERO
            lines = []
            for seq, row in enumerate(rows, 1):
                if type(row) is dict:
                    row['seq'], row['prev_hash'] = seq, previous
                    if row.get('event') == 'capture-seal':
                        row['last_hash'] = previous
                line = json.dumps(row).encode() + b'\n'
                lines.append(line)
                previous = hashlib.sha256(line).hexdigest()
            # Do not let the chain rebuilder silently repair the intended mutation.
            if case['path'] in (['seq'], ['prev_hash'], ['last_hash']):
                decoded = [json.loads(line) for line in lines]
                change(decoded[target], case['path'], invalid)
                lines = [json.dumps(row).encode() + b'\n' for row in decoded]
            planted_raw = b''.join(lines)
            root = tmp_path / ('planted-' + str(index))
            ref = retain(root, planted_raw)
            assert wc.verify(root, ref, context())['status'] == 'UNKNOWN'


def test_every_closed_capture_object_refuses_missing_or_extra_fields(tmp_path: Path) -> None:
    ref, raw = authored(tmp_path / 'source')
    for name, original, parser in [
        ('context', asdict(context()), wc.parse_context), ('reference', asdict(ref), wc.parse_reference),
        *[(kind, event_input(kind), lambda value: wc._event(value, context().roles)) for kind in wc.EVENT_FIELDS],
    ]:
        for field in [*original, 'unexpected']:
            changed = copy.deepcopy(original)
            if field == 'unexpected':
                changed[field] = None
            else:
                del changed[field]
            with pytest.raises(ValueError):
                parser(changed)
    for location in (0, -1):
        original_rows = [json.loads(line) for line in raw.splitlines()]
        for number, field in enumerate([*original_rows[location], 'unexpected']):
            rows = copy.deepcopy(original_rows)
            if field == 'unexpected':
                rows[location][field] = None
            else:
                del rows[location][field]
            planted = rechain(rows)
            if field in ('seq', 'prev_hash', 'last_hash'):
                decoded = [json.loads(line) for line in planted.splitlines()]
                del decoded[location][field]
                planted = b''.join(json.dumps(row).encode() + b'\n' for row in decoded)
            root = tmp_path / ('missing-' + str(location) + '-' + str(number))
            planted_ref = retain(root, planted)
            assert wc.verify(root, planted_ref, context())['status'] == 'UNKNOWN'


@pytest.mark.parametrize('value', [None, False, 0, 1.5, [], {}, 'unbound'],
                         ids=['null', 'bool', 'int', 'float', 'list', 'dict', 'text'])
def test_reader_and_writer_boundary_types_are_closed(tmp_path: Path, value: Any) -> None:
    root = tmp_path / 'capture'
    ref, _ = authored(root)
    for args in [(value, ref, context()), (root, value, context()), (root, ref, value)]:
        assert wc.verify(*args)['status'] == 'UNKNOWN'
    with pytest.raises(ValueError):
        wc.Capture(value, context(), 0)
    with pytest.raises(ValueError):
        wc.Capture(tmp_path / 'bad-context', value, 0)


@pytest.mark.parametrize('value', [float('inf'), float('nan'), -float('inf'), 10**1000],
                         ids=['inf', 'nan', 'minus-inf', 'overflow'])
def test_new_capture_numbers_refuse_nonfinite_or_overflow(tmp_path: Path, value: Any) -> None:
    with pytest.raises(ValueError):
        wc.Capture(tmp_path / 'bad-origin', context(), value)
    row = event_input('turn-ended')
    row['elapsed'] = value
    with pytest.raises(ValueError):
        wc._event(row, context().roles)
    with pytest.raises(ValueError):
        wc.Reference(1, context().digest, BASE.identity, value)


def test_capture_shape_population_and_healthy_system_events_are_frozen() -> None:
    assert len(SHAPES) == 95 and sum(len(row['invalid']) for row in SHAPES) == 743
    assert {row['event'] for row in SHAPES if row['kind'] == 'event'} == set(wc.EVENT_FIELDS)
    for kind in wc.EVENT_FIELDS:
        assert wc._event(event_input(kind), context().roles)


def test_unobserved_binding_never_enters_the_complete_count_adapter(tmp_path: Path) -> None:
    capture = wc.Capture(tmp_path / 'capture', context(), 0)
    ref = capture.seal('UNKNOWN', [{**row, 'session_id': None} for row in FINAL])
    result = wc.verify(capture.root, ref, context())
    assert result['status'] == 'CAPTURED' and result['complete'] is False
    assert all(row['pokes'] is None for row in result['poke_counts'])
    with pytest.raises(wc.CaptureUnavailable):
        wc.poke_counts(capture.root, ref, context())


def test_private_root_diagnostic_is_absent_and_seeded_leak_is_detectable(tmp_path: Path) -> None:
    marker = 'owner-private-capture-marker'
    value = wc.verify(tmp_path / marker, wc.Reference(1, context().digest, BASE.identity, 10), context())
    assert value['status'] == 'UNKNOWN'
    assert marker not in json.dumps(value)
    assert marker in json.dumps({**value, 'private_root': marker})


def test_poke_ordinal_blind_mutant_loses_integrity_bound_semantic_witness(tmp_path: Path) -> None:
    _ref, raw = authored(tmp_path / 'source')
    rows = [json.loads(line) for line in raw.splitlines()]
    next(row for row in rows if row['event'] == 'poke-attempt')['poke'] = 2
    root = tmp_path / 'bad'
    ref = retain(root, rechain(rows))
    assert wc.verify(root, ref, context())['status'] == 'UNKNOWN'
    namespace = dict(vars(wc))
    compiled(wc._decode, "or row['poke'] != state['count'] + 1", 'or False', namespace)
    compiled(wc.verify, 'return _decode(', 'return _decode(', namespace)
    with pytest.raises(AssertionError):
        assert namespace['verify'](root, ref, context())['status'] == 'UNKNOWN'


def test_initial_binding_blind_mutant_loses_session_witness(tmp_path: Path) -> None:
    _ref, raw = authored(tmp_path / 'source')
    rows = [json.loads(line) for line in raw.splitlines()]
    next(row for row in rows if row['event'] == 'turn-ended')['binding_session'] = SID_B
    root = tmp_path / 'bad'
    ref = retain(root, rechain(rows))
    assert wc.verify(root, ref, context())['status'] == 'UNKNOWN'
    namespace = dict(vars(wc))
    compiled(wc._decode, "if row['binding_session'] != state['session']:", 'if False:', namespace)
    compiled(wc.verify, 'return _decode(', 'return _decode(', namespace)
    with pytest.raises(AssertionError):
        assert namespace['verify'](root, ref, context())['status'] == 'UNKNOWN'


def test_queue_failure_has_an_explicit_unconfirmed_attempt_after_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    class QueueFailure:
        def __init__(self, **kwargs: Any) -> None:
            self.pool = ThreadPoolExecutor(**kwargs)
        def submit(self, function: Any, *args: Any, **kwargs: Any) -> Any:
            if len(args) > 1:
                raise RuntimeError('synthetic queue refusal')
            return self.pool.submit(function, *args, **kwargs)
        def shutdown(self, **kwargs: Any) -> None:
            self.pool.shutdown(**kwargs)
    monkeypatch.setattr(ww, 'ThreadPoolExecutor', QueueFailure)
    with pytest.raises(RuntimeError, match='synthetic queue refusal'):
        ww.drive(wave, policy(), read_revision=wave.read)
    assert wave.closed and all(text is None for _, text, _ in wave.calls)
    value = wc.verify(wave.root / 'wake-capture', wave.wake_capture_reference, wave.wake_capture_context)
    assert value['status'] == 'CAPTURED' and value['outcome'] == 'UNKNOWN'
    assert value['poke_count'] == 1 and value['pokes'][0]['result'] is None
    assert value['pokes'][0]['unconfirmed']['event'] == 'poke-unconfirmed'


@pytest.mark.parametrize('raw', [b'\xff\n', b'\n', b'[' * 2000 + b'0' + b']' * 2000 + b'\n'],
                         ids=['invalid-utf8', 'empty-record', 'deep-json'])
def test_malformed_retained_json_is_unknown_without_unrelated_hash_failure(tmp_path: Path, raw: bytes) -> None:
    root = tmp_path / 'capture'
    ref = retain(root, raw)
    assert wc.verify(root, ref, context())['status'] == 'UNKNOWN'


def test_writer_byte_and_record_bounds_have_actual_refusal_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(wc, 'MAX_CAPTURE', 1)
        with pytest.raises(wc.CaptureUnavailable, match='byte bound'):
            wc.Capture(tmp_path / 'too-small', context(), 0)
    capture = wc.Capture(tmp_path / 'records', context(), 0)
    with monkeypatch.context() as patch:
        patch.setattr(wc, 'MAX_EVENTS', 0)  # No controller events fit this controlled record ceiling.
        with pytest.raises(wc.CaptureUnavailable):
            capture.append({'seq': 1, 'event': 'observation-unavailable', 'role': '-', 'time': 0})
    capture.close()


def test_retained_counts_survive_final_projection_publication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    original = wave._write
    def fail(name: str, payload: object) -> None:
        if name == 'wake-report.json':
            raise OSError('synthetic final projection failure')
        original(name, payload)
    monkeypatch.setattr(wave, '_write', fail)
    with pytest.raises(OSError, match='synthetic final projection failure'):
        ww.drive(wave, policy(), read_revision=wave.read)
    assert wave.closed and not (wave.root / 'wake-report.json').exists()
    counts = wc.poke_counts(wave.root / 'wake-capture', wave.wake_capture_reference, wave.wake_capture_context)
    assert [row.pokes for row in counts] == [1, 1]


@pytest.mark.parametrize('variant', ['omitted', 'deferred'], ids=['omitted', 'deferred'])
def test_existing_durability_witness_defeats_barrier_blind_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str,
) -> None:
    import textwrap
    source = inspect.getsource(wc.Capture._append)
    anchor = 'os.fsync(self.stream.fileno())'
    assert source.count(anchor) == 1
    replacement = ('pass' if variant == 'omitted' else
                   "if row['event'] != 'poke-attempt':\n                os.fsync(self.stream.fileno())")
    # Use actual globals: technical-bound controls must still affect the producer.
    namespace = vars(wc)
    sentinel = object()
    previous = namespace.get('_append', sentinel)
    exec(compile(textwrap.dedent(source.replace(anchor, replacement)),  # noqa: S102
                 '<barrier-blind-wake-producer>', 'exec'), namespace)
    mutant = namespace.pop('_append')
    if previous is not sentinel:
        namespace['_append'] = previous
    monkeypatch.setattr(wc.Capture, '_append', mutant)
    with pytest.raises(AssertionError):
        test_driver_fsyncs_attempt_before_transport_and_supplies_verified_adapter(tmp_path)


def test_event_fsync_error_blocks_resume_and_preserves_cleanup_and_known_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    original_fsync = wc.os.fsync
    failed: list[str] = []
    delivered: list[ww.Poke] = []
    def fsync(fd: int) -> None:
        row = last_synced_record(fd)
        if row is not None and row.get('event') == 'poke-attempt':
            failed.append(row['nonce'])
            raise OSError('synthetic event fsync failure')
        original_fsync(fd)
    def transport(poke: ww.Poke) -> bool:
        delivered.append(poke)
        return True
    monkeypatch.setattr(wc.os, 'fsync', fsync)
    with pytest.raises(OSError, match='synthetic event fsync failure'):
        ww.drive(wave, policy(), read_revision=wave.read, deliver=transport)
    assert len(failed) == 1 and not delivered
    assert wave.closed and all(text is None for _, text, _ in wave.calls)
    assert wave.wake_capture_reference is None
    report = json.loads((wave.root / 'wake-report.json').read_text())
    assert report['outcome'] == 'UNKNOWN' and report['poke_count'] == 1
    assert report['wake_capture']['status'] == 'UNKNOWN'
