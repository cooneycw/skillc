"""Sealed custody qualification; scripted Python peer only, no client/model."""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from skillc import codex_goal as g
from skillc import codex_goal_capture as c

CASES = json.loads((Path(__file__).parents[1] / 'controls/codex-goal-custody/cases.json').read_text())
SESSIONS = [{'session': 'worker', 'role': 'worker', 'token_budget': 300}]
PEER = Path(__file__).parent / 'fixtures/codex-goal/peer.py'


def context() -> c.Context:
    return c.Context('attempt-1', 'sha256:' + 'a' * 64, g.CLIENT_VERSION,
                     'scripted-model', 'Deliver the public goal', 300)


def fixture_capture(root: Path) -> tuple[c.Reference, c.Context]:
    ctx = context()
    capture = c.Capture(root, ctx)
    capture.bind_transport()
    capture.bind_session(client_version=ctx.client_version, model=ctx.model,
                         objective=ctx.objective, budget=ctx.recorded_token_budget)
    capture.event({'seq': 1, 'kind': 'request', 'method': 'initialize', 'params': {}})
    capture.frame('sent', b'{"id":1}\n')
    capture.frame('received', b'{"id":1,"result":{}}\n')
    capture.event({'seq': 2, 'kind': 'response', 'method': 'initialize', 'result': {}})
    return capture.seal(), ctx


def exercise(root: Path, operation: str, verifier: Any = c.verify) -> str:
    ref, ctx = fixture_capture(root)
    path = root / 'objects' / ref.digest[7:]
    raw = path.read_bytes()
    if operation == 'misbinding':
        ctx = replace(ctx, attempt_id='attempt-2')
    elif operation != 'healthy':
        path.chmod(0o600)
        if operation == 'tamper':
            raw = raw.replace(b'initialize', b'INITIALIZE', 1)
        elif operation == 'truncation':
            raw = b''.join(raw.splitlines(keepends=True)[:-1])
        elif operation == 'reorder':
            lines = raw.splitlines(keepends=True)
            lines[3], lines[4] = lines[4], lines[3]
            raw = b''.join(lines)
        else:
            raise AssertionError(operation)
        path.write_bytes(raw)
    return str(verifier(root, ref, ctx)['status'])


@pytest.mark.parametrize('case', CASES, ids=[row['id'] for row in CASES])
def test_committed_custody_cases(tmp_path: Path, case: dict[str, str]) -> None:
    assert exercise(tmp_path / 'capture', case['id']) == case['status']


@pytest.mark.parametrize('verdict', ['CAPTURED', 'UNKNOWN'])
def test_compiled_blind_instruments_fail_committed_cases(tmp_path: Path, verdict: str) -> None:
    # Deliberately compiled production-code variants, not failures of an absent API.
    source = inspect.getsource(c)
    needle = 'return _decode(_read(root, reference), reference, expected)'
    assert source.count(needle) == 1
    path = tmp_path / 'blind.py'
    path.write_text(source.replace(needle, "return {'status': '" + verdict + "'}"))
    spec = importlib.util.spec_from_file_location('goal_capture_blind', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        def verifier(root: Path, ref: c.Reference, ctx: c.Context) -> dict[str, Any]:
            return module.verify(root, module.Reference(**asdict(ref)), module.Context(**asdict(ctx)))
        rejected = [case['id'] for case in CASES
                    if exercise(tmp_path / case['id'], case['id'], verifier) != case['status']]
        assert rejected == (['tamper', 'truncation', 'reorder', 'misbinding']
                            if verdict == 'CAPTURED' else ['healthy'])
    finally:
        del sys.modules[spec.name]


@pytest.mark.parametrize('mode', ['healthy', 'peer-disappears', 'malformed-goal', 'usage-limit', 'model-change'])
def test_custody_covers_actual_scripted_peer(tmp_path: Path, mode: str) -> None:
    ctx = context()
    capture = c.Capture(tmp_path / 'capture', ctx)
    proc = subprocess.Popen([sys.executable, '-u', str(PEER), mode], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    try:
        assert proc.stdout is not None and proc.stdin is not None
        transport = g.JsonLineTransport(proc.stdout, proc.stdin, wire=lambda *_: None,
                                         timeout=2, capture=capture)
        driver = g.GoalSession(transport, objective=ctx.objective, model=ctx.model,
                               comparison_sessions=SESSIONS, capture=capture)
        try:
            driver.start(cwd='/work')
            driver.poll()
            if mode == 'model-change':
                driver.poll()
        except g.GoalRefused:
            assert mode in ('peer-disappears', 'malformed-goal')
        report = driver.report()
    finally:
        proc.terminate()
        proc.communicate(timeout=3)
    ref = capture.seal()
    retained = c.verify(capture.root, ref, ctx)
    assert retained['status'] == 'CAPTURED'
    assert retained['events'] == report['events']
    frames = retained['frames']
    assert {row['direction'] for row in frames} == {'sent', 'received'}
    assert json.loads(frames[0]['raw'])['method'] == 'initialize'
    assert report['recorded_token_budget'] == 300 and report['budget_enforced'] is False
    if mode in ('peer-disappears', 'malformed-goal'):
        assert report['outcome'] == 'infrastructure-protocol-error'
        assert report['pool_eligible'] is False
    if mode == 'malformed-goal':
        assert any(b'"status": []' in row['raw'] for row in frames)


def test_fsync_precedes_frame_callback_and_goal_state_exposure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = context()
    capture = c.Capture(tmp_path / 'capture', ctx)
    read_fd, write_fd = os.pipe()
    synced: list[int] = []
    original = os.fsync
    def sync(fd: int) -> None:
        original(fd)
        synced.append(fd)
    monkeypatch.setattr(os, 'fsync', sync)
    with os.fdopen(read_fd, 'rb', buffering=0) as reader, os.fdopen(write_fd, 'wb', buffering=0) as writer:
        def observed(direction: str, raw: bytes) -> None:
            assert synced == [capture.stream.fileno()]
        transport = g.JsonLineTransport(reader, writer, wire=observed, capture=capture)
        driver = g.GoalSession(transport, objective=ctx.objective, model=ctx.model,
                               comparison_sessions=SESSIONS, capture=capture)
        synced.clear()
        transport.send({'id': 1})
        assert synced == [capture.stream.fileno()]
        def fail(fd: int) -> None:
            raise OSError('fsync failed')
        monkeypatch.setattr(os, 'fsync', fail)
        goal = {'threadId': 'thread-1', 'status': 'active', 'objective': ctx.objective,
                'tokenBudget': None, 'tokensUsed': 0, 'timeUsedSeconds': 0, 'createdAt': 1, 'updatedAt': 1}
        driver.thread_id = 'thread-1'
        with pytest.raises(g.GoalRefused, match='custody failed'):
            driver._goal(goal, 'thread/goal/set')
        assert driver.goal is None and not driver.events
        rollout = (json.dumps({'type': 'session_meta', 'payload': {
            'id': 'thread-1', 'cli_version': g.CLIENT_VERSION}}) + '\n' + json.dumps({
            'type': 'turn_context', 'payload': {'model': ctx.model}}) + '\n').encode()
        assert driver.report(rollout)['pool_eligible'] is False
        with pytest.raises(c.CaptureUnavailable):
            capture.seal()
    capture.close()


def test_unsealed_or_failed_capture_never_verifies(tmp_path: Path) -> None:
    capture = c.Capture(tmp_path / 'capture', context())
    try:
        assert c.verify(capture.root, None, context())['status'] == 'UNKNOWN'
        with pytest.raises(c.CaptureUnavailable):
            capture.seal()
    finally:
        capture.close()


def test_sealed_capture_is_closed_and_reference_round_trips(tmp_path: Path) -> None:
    ref, ctx = fixture_capture(tmp_path / 'capture')
    assert c.parse_reference(asdict(ref)) == ref
    assert c.parse_context(asdict(ctx)) == ctx
    assert not (tmp_path / 'capture/events.tmp').exists()
    path = tmp_path / 'capture/objects' / ref.digest[7:]
    assert path.stat().st_mode & 0o777 == 0o400
    path.unlink()
    path.symlink_to(tmp_path / 'missing')
    assert c.verify(tmp_path / 'capture', ref, ctx)['status'] == 'UNKNOWN'
