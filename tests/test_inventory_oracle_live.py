"""#640 real-daemon qualification; no model calls or host candidate execution.

The certifying real-Docker runner must execute this file. A local skip is
absence of evidence. The weakened read-only launch is a committed negative
control for the same containment assertion used on the production launch.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import secrets
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import LIVE_DOCKER_DAEMON_TIMEOUT
from test_codex_guard_live import _trial_image
from test_codex_guard_live import pytestmark as _live_marks

from skillc import inventory_oracle as io
from skillc import inventory_oracle_harness as harness
from skillc.backend import Confirmation
from skillc.docker_backend import DockerBackend, _Handle

pytestmark = [*_live_marks, pytest.mark.timeout(1800)]
TASK = Path(__file__).resolve().parents[1] / 'evals/level3/change-with-regression-568'


@pytest.fixture(scope='module')
def attempt(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[DockerBackend, _Handle]]:
    tag, built = _trial_image()
    backend = DockerBackend(image=tag, base_dir=tmp_path_factory.mktemp('inventory-live'),
                            network='none', daemon_timeout=LIVE_DOCKER_DAEMON_TIMEOUT)
    try:
        handle = backend.prepare('inventory-live-' + secrets.token_hex(8))
        assert isinstance(handle, _Handle)
        try:
            assert backend.image_id(handle) is not None
            yield backend, handle
        finally:
            backend.destroy(handle)
            assert backend.confirm_absent(handle) is Confirmation.CONFIRMED
    finally:
        if built:
            subprocess.run(['docker', 'image', 'rm', '-f', tag], capture_output=True, timeout=30, check=False)


def _judge(oracle: dict[str, Any]) -> dict[str, str]:
    spec = importlib.util.spec_from_file_location('inventory_live_judge', TASK / 'grade_inventory.py')
    assert spec is not None and spec.loader is not None
    judge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(judge)
    result = judge.judge({'trusted': json.dumps({'case': 'inventory', 'gates_offered': False,
                         'git': {'base_commit': 'a' * 40, 'delivery': {
                             'status': 'read', 'commit': 'b' * 40, 'oracle': oracle}}})})
    return {r['id']: r['outcome'] for r in result['criteria']}


def _files(program: str) -> dict[str, dict[str, str]]:
    source = (TASK / ('fixture/inventory.py' if program == 'fixture' else 'candidates/reference.py')).read_bytes()
    files = {'inventory.py': source,
             'tests/test_legacy.py': (TASK / 'fixture/tests/test_legacy.py').read_bytes(),
             'tests/test_import.py': (TASK / 'candidates/test_import.py').read_bytes(),
             'tests/test_uid.py': b'import os,unittest\nclass UID(unittest.TestCase):\n def test_uid(self): self.assertEqual(os.geteuid(),65534)\n'}
    if program == 'executable':
        files['implementation.py'] = source
        files['helper_cli'] = b'#!/usr/bin/env python3\n' + source
        files['inventory.py'] = (b'from implementation import *\nif __name__ == "__main__":\n'
                                 b' import subprocess,sys; raise SystemExit(subprocess.call(["./helper_cli", *sys.argv[1:]]))\n')
    return {path: {'mode': '100755' if path == 'helper_cli' else '100644',
                   'data_b64': base64.b64encode(data).decode()} for path, data in files.items()}


@pytest.mark.parametrize('program', ['reference', 'fixture', 'executable'])
def test_captured_program_outcomes_from_the_real_oracle(attempt: tuple[DockerBackend, _Handle], program: str) -> None:
    backend, handle = attempt
    oracle = io.run(_files(program), backend, handle, task_root=TASK)
    assert oracle['status'] == 'ran', oracle  # Includes real-daemon cleanup confirmation.
    verdict = _judge(oracle)
    assert verdict['delivered-main'] == 'SATISFIED'
    assert verdict['legacy-preserved'] == verdict['tests-protect'] == 'SATISFIED', oracle
    assert verdict['feature-correct'] == ('VIOLATED' if program == 'fixture' else 'SATISFIED'), oracle
    assert verdict['gate-ran'] == 'UNKNOWN'


# Controller-owned probe reuses the ACTUAL harness execute/sweep functions.
# Its fixed child forks an escaped session; no arbitrary subject runs on host.
_PROBE = r'''
import ctypes,errno,json,os,pathlib,subprocess,sys,tempfile,time
namespace={'__name__':'trusted_probe'}
exec(compile(HARNESS,'trusted_probe','exec'),namespace)
assert namespace['container_parent']()
assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
readonly=[]
for path in ('/inventory-readonly-control','/dev/mqueue/inventory-readonly-control'):
 try:
  with open(path,'x') as f: f.write('control')
 except OSError as exc:
  readonly.append(exc.errno==errno.EROFS)
 else:
  pathlib.Path(path).unlink()
  readonly.append(False)
child="import os,pathlib,time;os.setsid();pathlib.Path('escaped.pid').write_text(str(os.getpid()));time.sleep(20)"
parent="import os,pathlib,subprocess,sys,time;assert os.geteuid()==65534 and os.getegid()==65534;subprocess.Popen([sys.executable,'-c',"+repr(child)+"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);end=time.monotonic()+2\nwhile not pathlib.Path('escaped.pid').exists() and time.monotonic()<end: time.sleep(.01)\nassert pathlib.Path('escaped.pid').exists();print('candidate-privileges-dropped')"
class Budget:
 deadline=time.monotonic()+15; capacity=1024*1024; used=0; processes=0
 def check(self): pass
with tempfile.TemporaryDirectory() as temp:
 root=pathlib.Path(temp)
 code,out,err=namespace['execute']([sys.executable,'-c',parent],root,Budget())
 assert code==0 and out.strip()=='candidate-privileges-dropped',(code,out,err)
 pid=int((root/'escaped.pid').read_text())
 p=pathlib.Path('/proc')/str(pid)/'stat'
 alive=p.exists() and p.read_text().rsplit(')',1)[1].split()[0] not in ('Z','X')
 print(json.dumps({'readonly':readonly,'uid':65534,'swept':not alive}))
'''


def _assert_contained(result: dict[str, Any]) -> None:
    assert result == {'readonly': [True, True], 'uid': 65534, 'swept': True}, result


def test_real_parent_containment_and_weakened_flag_negative_control(attempt: tuple[DockerBackend, _Handle]) -> None:
    backend, handle = attempt
    image = backend.image_id(handle)
    assert isinstance(image, str)
    # Same assertion, intact launch then known-bad launch. The latter MUST
    # raise, so a probe that stops detecting writable rootfs turns this red.
    for weak in (False, True):
        name = 'skillc-inventory-control-' + secrets.token_hex(8)
        argv = io.container_argv(backend.docker_bin, image, name)
        if weak:
            argv.remove('--read-only')
        argv[-1] = 'HARNESS=' + repr(Path(harness.__file__).read_text()) + '\n' + _PROBE
        env = handle.env
        try:
            code, out, problem = io._bounded(argv, '', timeout=30, limit=65536, env=env)
        finally:
            subprocess.run([*backend.docker_bin, 'rm', '-f', name], capture_output=True,
                           timeout=30, check=False, env=env)
            absent = subprocess.run([*backend.docker_bin, 'inspect', name], capture_output=True,
                                    text=True, timeout=30, check=False, env=env)
            assert absent.returncode != 0 and name in absent.stderr.lower()
            assert 'no such object' in absent.stderr.lower() or 'no such container' in absent.stderr.lower()
        assert problem is None and code == 0, (code, problem, out)
        result = json.loads(out)
        if weak:
            assert result['readonly'] == [False, True], result
            with pytest.raises(AssertionError):
                _assert_contained(result)
        else:
            _assert_contained(result)
