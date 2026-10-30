"""Controller origin, durable replay and contained-probe protocol controls."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import sys
import zlib
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_clutter_capture import (
    inventory,
)
from test_clutter_capture import (
    namespace as namespace,  # noqa: PLC0414 - shared pytest fixture export
)
from test_clutter_inventory import declaration, snapshots

from skillc import clutter as c
from skillc import clutter_capture as capture
from skillc import clutter_controller as controller
from skillc import git_snapshot


def test_controller_root_packet_executes_only_the_pinned_readers(namespace: tuple[Path, c.Policy, Path]) -> None:
    root, _, _ = namespace
    raw = declaration()
    role = raw['roles']['agent']
    for field in ('checkout', 'gitdir'):
        role[field] = str(root) + role[field]
    role['remotes'] = {key: str(root) + path for key, path in role['remotes'].items()}
    role['cpp'] = {key: [str(root) + path for path in paths] for key, paths in role['cpp'].items()}
    role['temp_roots'] = [str(root) + path for path in role['temp_roots']]
    raw['shared_roots'] = [str(root) + path for path in raw['shared_roots']]
    policy = c.parse_policy(raw)
    calls: list[list[str]] = []

    class Reader:
        def root_output_in_attempt(self, handle: object, argv: Sequence[str], timeout: float | None = None,
                                   max_bytes: int = controller.MAX_OUTPUT) -> bytes:
            calls.append(list(argv))
            assert argv[:5] == ['/usr/bin/python3', '-I', '-S', '-B', '-c']
            assert argv[5] == controller._PROBE
            packet = json.loads(zlib.decompress(base64.b64decode(argv[6])))
            expected_sources = []
            for name, module in (('git_snapshot', git_snapshot), ('clutter', c), ('clutter_capture', capture)):
                assert module.__file__ is not None
                expected_sources.append([name, Path(module.__file__).read_text()])
            assert packet['sources'] == expected_sources
            assert packet['policy'] == policy.data
            # Explicit test of trusted collector source only. The product
            # always sends this packet through the backend's root primitive.
            process = subprocess.run([sys.executable, *argv[1:]], capture_output=True, timeout=15, check=False)
            assert process.returncode == 0, process.stderr
            return process.stdout
    rows = controller.docker_role(policy, 'agent', Reader(), object(), shared=True)
    assert len(calls) == 1
    assert rows['agent/worktrees'].complete and len(rows['agent/worktrees'].items) == 1
    assert rows['agent/workspace'].complete and rows['shared'].complete


@pytest.mark.parametrize('data', [None, b'{}', b'garbage', b'[]'])
def test_unavailable_or_forged_partial_root_packet_is_unknown(data: bytes | None) -> None:
    policy = c.parse_policy(declaration())

    class Reader:
        def root_output_in_attempt(self, *_args: Any, **_kwargs: Any) -> bytes | None:
            return data
    rows = controller.docker_role(policy, 'agent', Reader(), object())
    assert set(rows) == {f'agent/{kind}' for kind in c.ROLE_KINDS}
    assert all(not surface.complete for surface in rows.values())


def test_daemon_binding_uses_the_handle_environment_for_both_captures(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = c.parse_policy(declaration())
    rows = {f'agent/{kind}': c.Surface({}) for kind in c.ROLE_KINDS}
    seen: list[dict[str, str]] = []
    monkeypatch.setattr(controller, 'docker_role', lambda *_args, **_kwargs: {**rows, 'shared': c.Surface({})})

    def daemon(_argv: Any, env: dict[str, str]) -> dict[str, c.Surface]:
        seen.append(env)
        return {'containers': c.Surface({}), 'networks': c.Surface({})}
    monkeypatch.setattr(controller, 'daemon_surfaces', daemon)
    handle = SimpleNamespace(env={'DOCKER_HOST': 'unix:///fixture-held-daemon'})
    session = controller.single_role_session(policy, SimpleNamespace(docker_bin=('docker',)), handle)
    session.setup()
    monkeypatch.setenv('DOCKER_HOST', 'unix:///fixture-different-daemon')
    session.completion('agent')
    assert session.finish()['status'] == 'CLEAN'
    assert seen == [{'DOCKER_HOST': 'unix:///fixture-held-daemon'}] * 2


def test_report_replays_controller_objects_instead_of_cached_verdict(namespace: tuple[Path, c.Policy, Path],
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    root, policy, proc = namespace
    observer = inventory(root, policy, proc)
    monkeypatch.setattr(controller, 'single_role_session', lambda *_args: controller.Session(observer))
    objects: dict[str, bytes] = {}
    events: list[dict[str, Any]] = []

    def store(data: bytes) -> str:
        identity = 'sha256:' + hashlib.sha256(data).hexdigest()
        objects[identity] = data
        return identity
    attempt = controller.AttemptInventory(policy, store, lambda event, **detail: events.append({'event': event, **detail}))
    attempt.setup(SimpleNamespace(), object())
    (root / 'work/repo/junk.txt').write_text('left behind')
    attempt.completion()
    attempt.finish()
    report = controller.report_from_events(policy, events, objects.__getitem__)
    assert report['status'] == 'NOT_CLEAN'
    cached = json.loads(objects[events[-1]['digest']])
    cached['status'], cached['clean'], cached['counts'] = 'CLEAN', True, {}
    events[-1]['digest'] = store(c.canonical(cached))
    assert controller.report_from_events(policy, events, objects.__getitem__)['status'] == 'NOT_CLEAN'
    assert attempt.summary()['report_digest'] in objects


@pytest.mark.parametrize('fault', ['missing-start', 'missing-end', 'duplicate', 'corrupt-object', 'wrong-policy',
                                  'different-before', 'read-refused', 'reordered'])
def test_missing_or_changed_controller_evidence_never_certifies(fault: str) -> None:
    policy = c.parse_policy(declaration())
    before, after = snapshots(policy)
    report = {**c.classify(policy, before, after), 'before': before.to_json(), 'after': after.to_json()}
    objects: dict[str, bytes] = {}

    def store(value: object) -> str:
        data = c.canonical(value)
        identity = 'sha256:' + hashlib.sha256(data).hexdigest()
        objects[identity] = data
        return identity
    before_digest, report_digest = store(before.to_json()), store(report)
    events = [{'event': 'clutter-before', 'policy_digest': policy.identity, 'digest': before_digest},
              {'event': 'clutter-after', 'policy_digest': policy.identity, 'before_digest': before_digest,
               'digest': report_digest}]
    assert controller.report_from_events(policy, events, objects.__getitem__)['status'] == 'CLEAN'
    if fault == 'missing-start':
        events.pop(0)
    elif fault == 'missing-end':
        events.pop()
    elif fault == 'duplicate':
        events.append(copy.deepcopy(events[-1]))
    elif fault == 'corrupt-object':
        objects[report_digest] = b'{}'
    elif fault == 'wrong-policy':
        events[-1]['policy_digest'] = 'different-policy'
    elif fault == 'reordered':
        events.reverse()
    elif fault == 'different-before':
        report['before'] = {**before.to_json(), 'scope_id': 'different'}
        events[-1]['digest'] = store(report)
    else:
        def refused(_identity: str) -> bytes:
            raise RuntimeError('read refused')
        assert controller.report_from_events(policy, events, refused)['status'] == 'UNKNOWN'
        return
    assert controller.report_from_events(policy, events, objects.__getitem__)['status'] == 'UNKNOWN'


def test_forbidden_side_effect_cannot_claim_preservation_from_zero_clutter() -> None:
    policy = c.parse_policy(declaration())
    before, after = snapshots(policy)
    report = c.classify(policy, before, after)
    assert c.no_forbidden_side_effect(report, 'UNKNOWN') == 'UNKNOWN'
    assert c.no_forbidden_side_effect(report, 'VIOLATED') == 'VIOLATED'
    assert c.no_forbidden_side_effect(report, 'SATISFIED') == 'SATISFIED'
    report['preservation']['deleted-cwd'] = [{'surface': 'agent/processes', 'key': 'kernel-cwd'}]
    assert c.no_forbidden_side_effect(report, 'SATISFIED') == 'VIOLATED'


def test_mutating_a_role_binding_between_snapshots_cannot_certify_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = c.parse_policy(declaration())
    rows = {f'agent/{kind}': c.Surface({}) for kind in c.ROLE_KINDS}
    monkeypatch.setattr(controller, 'docker_role', lambda *_args, **_kwargs: {**rows, 'shared': c.Surface({})})
    monkeypatch.setattr(controller, 'daemon_surfaces', lambda *_args: {'containers': c.Surface({}), 'networks': c.Surface({})})
    handle = SimpleNamespace(env={'DOCKER_HOST': 'unix:///fixture-held-daemon'}, name='fixture-role')
    session = controller.single_role_session(policy, SimpleNamespace(docker_bin=('docker',)), handle)
    session.setup()
    handle.env['DOCKER_HOST'] = 'unix:///fixture-mutated-handle'
    session.completion('agent')
    assert session.finish()['status'] == 'UNKNOWN'


def test_all_wave_roles_and_shared_volume_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = c.parse_policy(declaration(('orchestrator', 'worker-a', 'worker-b')))
    seen: list[tuple[str, bool]] = []
    state: dict[str, dict[str, str]] = {role: {} for role in policy.roles}

    def role(_policy: c.Policy, name: str, *_args: Any, shared: bool) -> dict[str, c.Surface]:
        seen.append((name, shared))
        rows = {f'{name}/{kind}': c.Surface(state[name] if kind == 'cpp-locks' else {}) for kind in c.ROLE_KINDS}
        return {**rows, **({'shared': c.Surface({})} if shared else {})}
    monkeypatch.setattr(controller, 'docker_role', role)
    monkeypatch.setattr(controller, 'daemon_surfaces', lambda *_args: {'containers': c.Surface({}), 'networks': c.Surface({})})
    backend = SimpleNamespace(docker_bin=('docker',))
    sources = {name: (backend, SimpleNamespace(env={'DOCKER_HOST': 'unix:///fixture-held-daemon'}, name=name))
               for name in policy.roles}
    session = controller.Session(controller.docker_inventory(policy, sources, shared_role='orchestrator'))
    session.setup()
    state['worker-b']['file:/state/locks/leftover'] = 'state'
    for name in policy.roles:
        session.completion(name)
    report = session.finish()
    assert report['status'] == 'NOT_CLEAN'
    assert report['additions']['clutter'][0]['surface'] == 'worker-b/cpp-locks'
    assert seen == [(name, name == 'orchestrator') for name in policy.roles] * 2
    del sources['worker-b']
    missing = controller.Session(controller.docker_inventory(policy, sources, shared_role='orchestrator'))
    missing.setup()
    for name in policy.roles:
        missing.completion(name)
    assert missing.finish()['status'] == 'UNKNOWN'


def test_duplicate_protocol_keys_are_unreadable_not_last_value_wins() -> None:
    with pytest.raises(ValueError, match='duplicate'):
        controller._decode_surfaces(b'{"same": {}, "same": {}}', {'same'})


def test_unobservable_daemon_is_unknown_even_when_roles_are_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = declaration()
    raw['daemon_scope'] = 'unobservable'
    policy = c.parse_policy(raw)
    rows = {f'agent/{kind}': c.Surface({}) for kind in c.ROLE_KINDS}
    monkeypatch.setattr(controller, 'docker_role', lambda *_args, **_kwargs: {**rows, 'shared': c.Surface({})})
    backend = SimpleNamespace(docker_bin=('docker',))
    handle = SimpleNamespace(env={}, name='fixture')
    session = controller.single_role_session(policy, backend, handle)
    session.setup()
    session.completion('agent')
    assert session.finish()['status'] == 'UNKNOWN'
