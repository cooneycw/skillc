"""Model-free physical wave qualification through the existing real-Docker CI lane.

No manual/host Docker run is authorized. No model turn is started. The only
Codex commands are the existing offline sandbox/--version guard controls.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT
from test_codex_guard_live import SANDBOX, _trial_image

from skillc import docker_wave as dw
from skillc import egress, leak
from skillc.backend import Limits

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'tests/fixtures/profile-cpp-codex-flow-auto-87ecb097/codex/skills/flow-wave/scripts'
ROLES = ('orchestrator', 'worker-a', 'worker-b')
pytestmark = [pytest.mark.real_docker,
              pytest.mark.skipif(shutil.which('docker') is None, reason='real-Docker CI lane only'),
              pytest.mark.timeout(1800)]


@pytest.fixture(scope='module')
def image() -> Iterator[str]:
    tag, built = _trial_image()
    try:
        yield tag
    finally:
        if built:
            subprocess.run(['docker', 'image', 'rm', '-f', tag], capture_output=True, timeout=30, check=False)


def command(backend: Any, handle: object, argv: list[str], timeout: float = 30) -> Any:
    return backend.exec_in_attempt(handle, ['sh', '-c', 'exec "$@"', 'sh', *argv], Limits(timeout))


def output(backend: Any, handle: object, argv: list[str]) -> bytes:
    result = command(backend, handle, argv)
    assert result.reason == 'exited' and result.exit_code == 0, 'role-shell probe did not complete'
    assert result.stdout is not None and not result.stdout_truncated and not result.stdout_incomplete
    return result.stdout


def fixture(root: Path) -> Path:
    root.mkdir()
    actor = ROOT / 'tests/fixtures/docker-wave-live/wave_role_actor.py'
    shutil.copyfile(actor, root / actor.name)
    for name in ('flow-wave-registry.sh', 'flow-wave-mailbox.sh', 'flow-wave-lexicon.sh'):
        shutil.copyfile(PROFILE / name, root / name)
    for argv in (['git', 'init', '-b', 'main'], ['git', 'add', '.'],
                 ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                  'commit', '-m', 'scripted wave fixture']):
        subprocess.run(argv, cwd=root, check=True, capture_output=True, timeout=20)
    return root


_LISTENER = '''import socket
s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('0.0.0.0',43219));s.listen()
while True:
 c,_=s.accept();c.sendall(b'wave-listener');c.close()
'''
_LOCAL = '''import socket
with socket.create_connection(('127.0.0.1',43219),timeout=1) as s:
 print('ready' if s.recv(32)==b'wave-listener' else 'wrong-listener')
'''
_CONNECT = '''import errno,socket,sys
try:
 s=socket.create_connection((sys.argv[1],43219),timeout=1);s.close();print('connected')
except OSError as e:
 blocked=isinstance(e,TimeoutError) or e.errno in (errno.ENETUNREACH,errno.EHOSTUNREACH,errno.ETIMEDOUT)
 print('refused' if blocked else 'probe-error')
'''
_EGRESS = '''import json,os,socket,urllib.parse
u=urllib.parse.urlsplit(os.environ['HTTPS_PROXY'])
with socket.create_connection((u.hostname,u.port),timeout=5) as s:
 s.sendall(b'CONNECT github.com:443 HTTP/1.1\\r\\nHost: github.com:443\\r\\n\\r\\n')
 response=s.recv(1024)
print(json.dumps({'denied':response.startswith(b'HTTP/1.1 403')}))
'''


def peer_legs(wave: dw.DockerWave) -> dict[str, str]:
    addresses: dict[str, str] = {}
    for name, state in wave.states.items():
        wave._call(['exec', '-d', '--', wave._name(state.handle), 'sh', '-c', 'exec "$@"',
                    'sh', 'python3', '-c', _LISTENER])
        address = wave._call(egress.proxy_address_argv((), wave.network, wave._name(state.handle)))
        addresses[name] = address.decode().strip()
        end = time.monotonic() + 10
        while True:
            ready = command(state.backend, state.handle, ['python3', '-c', _LOCAL])
            if ready.exit_code == 0 and ready.stdout == b'ready\n':
                break
            assert time.monotonic() < end, 'listener never became ready'
            time.sleep(.02)
    verdicts = {}
    for source, state in wave.states.items():
        for target, peer in wave.states.items():
            if source == target:
                continue
            before = output(peer.backend, peer.handle, ['python3', '-c', _LOCAL]).decode().strip()
            observed = output(state.backend, state.handle, ['python3', '-c', _CONNECT,
                                                          addresses[target]]).decode().strip()
            after = output(peer.backend, peer.handle, ['python3', '-c', _LOCAL]).decode().strip()
            leg = {'listener_before': before, 'connect': observed, 'listener_after': after}
            verdicts[source + '-to-' + target] = dw.isolation_verdict(leg)
            wave._write('physical-peer/' + source + '-to-' + target + '.json', {
                'observation': leg, 'status': verdicts[source + '-to-' + target], 'origin': 'role-shells'})
    return verdicts


def protections(wave: dw.DockerWave) -> dict[str, str]:
    namespaces = {}
    for name, state in wave.states.items():
        assert output(state.backend, state.handle, ['id', '-u']).strip() == str(dw.CANDIDATE_UID).encode()
        namespaces[name] = output(state.backend, state.handle, ['readlink', '/proc/self/ns/pid']).decode().strip()
        # A returned 403 proves this role shell actually reached the proxy.
        denied = json.loads(output(state.backend, state.handle, ['python3', '-c', _EGRESS]))
        assert denied == {'denied': True}
        direct = output(state.backend, state.handle, ['python3', '-c', _CONNECT, '1.1.1.1']).strip()
        assert direct == b'refused', 'provider-only direct-route protection failed'
        # Two guard verdicts from this SAME role: allowed version, then a
        # forbidden nested version launched under a real offline Codex ancestor.
        before = len(state.guard.decisions)
        allowed = command(state.backend, state.handle, ['codex', '--version'])
        assert allowed.exit_code == 0 and (allowed.stdout or b'').startswith(b'codex-cli ')
        nested = command(state.backend, state.handle, [*SANDBOX, 'sh', '-c', 'codex --version'])
        assert nested.exit_code == 3 and b'CODEX_REVIEW: unavailable' in (nested.stderr or b'')
        assert [x['decision'] for x in state.guard.decisions[before:]] == [
            'passed-top-level', 'passed-top-level', 'refused-nested']
        # Synthetic credential bytes enter only through the real copy-in seam.
        # A wrong-role value is the committed red input for the same shell read.
        credential = json.dumps({'fixture_role': name}).encode()
        state.backend.deliver_home_file(state.handle, '.codex/auth.json', credential)
        source = ('import json,pathlib,sys; actual=json.loads((pathlib.Path.home()/".codex/auth.json").read_text()); '
                  'print(json.dumps({"matches":actual=={"fixture_role":sys.argv[1]}}))')
        for expected in ('wrong-role', name):
            read = json.loads(output(state.backend, state.handle, ['python3', '-c', source, expected]))
            assert read == {'matches': expected == name}
        wave._write(name + '/physical-protections.json', {'namespace': namespaces[name],
            'nonprovider_proxy': 'denied', 'direct_route': 'blocked', 'nested_version': 'refused',
            'synthetic_credential': 'own-role-only', 'wrong-role-control': 'refused'})
    assert len(set(namespaces.values())) == len(ROLES), 'PID namespaces were shared'
    # Re-read AFTER all copy-ins, so a mistakenly shared home cannot pass by
    # observing each sequential write just before the next role overwrites it.
    for name, state in wave.states.items():
        read = json.loads(output(state.backend, state.handle, ['python3', '-c', source, name]))
        assert read == {'matches': True}
    return namespaces


@pytest.mark.parametrize('mode', ['intact', 'peer-open', 'omit-mail', 'timeout', 'cancel'])
def test_physical_wave_transport_protections_and_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, image: str, mode: str,
) -> None:
    actors = [dw.Role(name, ('python3', 'wave_role_actor.py', name,
                             'omit-mail' if mode == 'omit-mail' and name == 'worker-a' else
                             'hang' if mode == 'timeout' and name == 'worker-a' else 'intact'),
                      'start', 30 if mode == 'timeout' and name == 'worker-a' else 75,
                      ('continue',)) for name in ROLES]
    wave = dw.DockerWave(attempt_id='wave-' + uuid.uuid4().hex[:12], image=image,
        root=tmp_path / 'evidence', fixture=fixture(tmp_path / 'fixture'), roles=actors,
        seconds=420, daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT)
    if mode == 'peer-open':
        original = wave._call

        def open_peer(argv: Any, **kwargs: Any) -> bytes:
            return original([x.replace('enable_icc=false', 'enable_icc=true') for x in argv], **kwargs)

        monkeypatch.setattr(wave, '_call', open_peer)
    try:
        wave.prepare()
        protections(wave)
        legs = peer_legs(wave)
        # Same physical assay, intact bridge versus committed bad ICC setting.
        assert len(legs) == 6
        assert set(legs.values()) == ({'FAIL'} if mode == 'peer-open' else {'PASS'}), legs
        if mode == 'cancel':
            cancelled = wave.turn('worker-a', cancel=lambda: True)
            assert cancelled.reason == 'operator-cancelled'
            # This separate control cancels only one role; sibling shells stay live.
            for name in ('orchestrator', 'worker-b'):
                state = wave.states[name]
                assert output(state.backend, state.handle, ['true']) == b''
            report = wave.close()
        else:
            report = wave.run_scripted()
    finally:
        report = wave.close()
    assert report['completion']['cleanup_confirmed'], report
    assert report['completion']['on_time'], report
    assert all(x['stop'] == x['absent'] == 'confirmed' for x in report['roles'].values())
    if mode in ('intact', 'peer-open'):
        assert all(x['exit_codes'] == [0, 0] for x in report['roles'].values()), report
        assert len({x['session_id'] for x in report['roles'].values()}) == 3
        for name in ROLES:
            artifacts = wave.root / name / 'artifacts'
            assert json.loads((artifacts / 'delivery.json').read_text())['status'] == 'delivered'
            assert json.loads((artifacts / 'git-delivery.json').read_text()) == {'status': 'delivered'}
            peers = json.loads((artifacts / 'cpp-peers.stdout').read_text())
            assert set(ROLES) <= peers.keys()
            assert all('liveness' in peers[peer] and 'liveness_basis' in peers[peer] for peer in ROLES)
            assert 'git://skillc-fixture/repo.git' in (artifacts / '.git/config').read_text()
            transcripts = list((wave.root / name).glob('transcript-*.jsonl'))
            assert transcripts and len(transcripts[0].read_text().splitlines()) == 2
    if mode == 'omit-mail':
        assert all(x['exit_codes'] == [7] for x in report['roles'].values()), report
    if mode == 'timeout':
        assert report['roles']['worker-a']['reasons'] == ['timeout']
        assert report['roles']['orchestrator']['exit_codes'] == report['roles']['worker-b']['exit_codes'] == [0, 0]
    # No credential directory is exported, even while captured transcripts exist.
    assert not list(wave.root.glob('*/artifacts/.codex/auth.json'))
    scan = leak.scan_path(wave.root, frozenset(), host_paths=leak.default_host_paths())
    assert not scan.findings, 'captured role evidence contains a machine identity or credential'
