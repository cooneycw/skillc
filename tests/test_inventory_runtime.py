"""#640 runtime controls; host execution accepts only reviewed B1 programs.

The product has no host fallback. The controlled driver below is a unit-test
emulator of the container parent, restricted to committed trusted examples.
Actual Docker isolation is checked separately by command and lifecycle controls.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from skillc import fixture_campaign as fc
from skillc import inventory_oracle as io
from skillc import inventory_oracle_harness as harness
from skillc import verify
from skillc.docker_backend import DockerBackend

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'evals/level3/change-with-regression-568'


def load(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location('inventory_runtime_' + path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def build() -> Any:
    return fc._builder(TASK)


@pytest.fixture(scope='module')
def judge() -> Any:
    return load(TASK / 'grade_inventory.py')


def oracle_good(judge: Any) -> dict[str, Any]:
    return {'status': 'ran', 'vectors': [{'id': name, 'feature': True, 'legacy': True} for name in judge.VECTORS],
            'protection': [{'program': p, 'population_valid': True,
                            'count': 5, 'ok': p in ('reference', 'alternative')} for p in judge.PROGRAMS]}


def envelope(oracle: dict[str, Any], offered: bool = False) -> dict[str, Any]:
    return {'trusted': json.dumps({'case': 'inventory', 'gates_offered': offered,
                                  'witness': {'gates': {'flow-auto-finish': {'runs': []}}},
                                  'git': {'base_commit': 'a' * 40, 'delivery': {
                                      'status': 'read', 'commit': 'b' * 40, 'oracle': oracle}}})}


def outcomes(judge: Any, record: dict[str, Any]) -> dict[str, Any]:
    return {row['id']: row for row in judge.judge(record)['criteria']}


def test_gate_not_offered_is_not_applicable_not_a_treated_zero_run(judge: Any) -> None:
    baseline = outcomes(judge, envelope(oracle_good(judge)))
    treated = outcomes(judge, envelope(oracle_good(judge), offered=True))
    assert baseline['gate-ran']['mandatory'] is False
    assert baseline['gate-ran']['outcome'] == 'UNKNOWN'
    assert 'not applicable' in baseline['gate-ran']['missing']
    assert treated['gate-ran']['outcome'] == 'VIOLATED'
    assert all(baseline[c]['outcome'] == treated[c]['outcome'] == 'SATISFIED' for c in judge.REQUIRED)


@pytest.mark.parametrize('fault', ['feature', 'legacy', 'tests', 'empty-vectors', 'duplicate-vector', 'malformed-vector',
                                  'empty-protection', 'malformed-protection', 'unavailable', 'missing-module'])
def test_judge_discriminates_wrong_and_unavailable_artifacts(judge: Any, fault: str) -> None:
    oracle = oracle_good(judge)
    if fault in ('feature', 'legacy'):
        oracle['vectors'][0][fault] = False
    elif fault == 'tests':
        oracle['protection'][2]['ok'] = True
    elif fault == 'empty-vectors':
        oracle['vectors'] = []
    elif fault == 'duplicate-vector':
        oracle['vectors'][-1] = oracle['vectors'][0]
    elif fault == 'malformed-vector':
        oracle['vectors'][0]['id'] = []
    elif fault == 'empty-protection':
        oracle['protection'] = []
    elif fault == 'malformed-protection':
        oracle['protection'][0].pop('population_valid')
    else:
        oracle = {'status': fault}
    rows = outcomes(judge, envelope(oracle))
    expected = {'feature': ('feature-correct', 'VIOLATED'), 'legacy': ('legacy-preserved', 'VIOLATED'),
                'tests': ('tests-protect', 'VIOLATED'), 'missing-module': ('feature-correct', 'VIOLATED')}
    cid, status = expected.get(fault, ('tests-protect' if fault in ('empty-protection', 'malformed-protection') else 'feature-correct', 'UNKNOWN'))
    assert rows[cid]['outcome'] == status


@pytest.mark.parametrize('kind', ['missing-export', 'absent-main', 'unchanged-main'])
def test_missing_export_is_unknown_but_observed_non_delivery_fails(judge: Any, kind: str) -> None:
    record = json.loads(envelope(oracle_good(judge))['trusted'])
    if kind == 'missing-export':
        record['git'] = None
    elif kind == 'absent-main':
        record['git']['delivery'] = {'status': 'absent', 'commit': None}
    else:
        record['git']['delivery']['commit'] = record['git']['base_commit']
    rows = outcomes(judge, {'trusted': json.dumps(record)})
    assert rows['delivered-main']['outcome'] == ('UNKNOWN' if kind == 'missing-export' else 'VIOLATED')


@pytest.mark.parametrize('remote_program,local_program', [('reference', 'fixture'), ('fixture', 'reference')])
def test_capture_reads_remote_blobs_even_when_workspace_disagrees(tmp_path: Path, build: Any,
                                                                 monkeypatch: pytest.MonkeyPatch,
                                                                 remote_program: str, local_program: str) -> None:
    where = tmp_path / 'built'
    surface, fixture = fc.build_case(TASK, 'inventory', where)
    repo, remote = surface['repo'], where / '.remote/widget.git'
    assert isinstance(repo, Path)
    programs = {'fixture': TASK / 'fixture/inventory.py', 'reference': TASK / 'candidates/reference.py'}
    (repo / 'inventory.py').write_bytes(programs[remote_program].read_bytes())
    (repo / 'delivery.txt').write_text('deliver')
    build.host_git(['add', '--all'], repo)
    build.host_git(['commit', '-qm', 'Deliver reviewed control'], repo, date='2026-10-02T09:00:00+0000')
    build.host_git(['push', '-q', str(remote), 'HEAD:refs/heads/main'], repo)
    (repo / 'inventory.py').write_bytes(programs[local_program].read_bytes())
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('no git or code execution during capture'))
    captured = build.capture_snapshot(where, dict(fixture.facts))
    delivery = captured['delivery']
    assert base64.b64decode(delivery['files']['inventory.py']['data_b64']) == programs[remote_program].read_bytes()
    assert delivery['commit'] != fixture.facts['base_commit']
    assert fixture.gate_offer_evidence is True


def test_oracle_has_no_host_or_unmeasured_image_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = {'inventory.py': {'mode': '100644', 'data_b64': ''}}
    assert io.run(files, object(), object(), task_root=TASK)['status'] == 'unavailable'
    assert io.run({}, object(), object(), task_root=TASK)['status'] == 'missing-module'
    backend = DockerBackend(image='never-use-tag', base_dir=tmp_path)
    monkeypatch.setattr(DockerBackend, 'image_id', lambda self, handle: None)
    assert io.run(files, backend, object(), task_root=TASK)['status'] == 'unavailable'


def test_oracle_container_is_separate_offline_and_has_no_host_mount() -> None:
    argv = io.container_argv(('docker',), 'sha256:' + 'a' * 64, 'oracle')
    for pair in (('--network', 'none'), ('--user', '0:0'), ('--pids-limit', '64'),
                 ('--cpus', '1'), ('--pull', 'never'), ('--cap-drop', 'ALL')):
        assert argv[argv.index(pair[0]) + 1] == pair[1]
    assert 'run' in argv and 'exec' not in argv and '--read-only' in argv
    assert not {'-v', '--volume', '--mount', '--privileged', '--pid=host'} & set(argv)
    assert 'user=65534' in Path(harness.__file__).read_text()
    assert 'sweep()' in Path(harness.__file__).read_text()


@pytest.mark.parametrize('problem', [None, 'timeout', 'output-over-bound', 'removal-failed', 'malformed', 'auto-removed', 'inspect-error', 'still-present'])
def test_oracle_transport_refuses_incomplete_results_and_always_removes_container(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, judge: Any, problem: str | None) -> None:
    backend = DockerBackend(image='tag', base_dir=tmp_path)
    monkeypatch.setattr(DockerBackend, 'image_id', lambda self, handle: 'sha256:' + 'a' * 64)
    seen: list[list[str]] = []

    def bounded(argv: list[str], data: str, **kwargs: Any) -> tuple[int, bytes, str | None]:
        seen.append(argv)
        job = json.loads(data)
        result = oracle_good(judge)
        output = b'garbage' if problem == 'malformed' else (job['nonce'] + json.dumps(result) + '\n').encode()
        return 0, output, problem if problem in ('timeout', 'output-over-bound') else None

    removed: list[list[str]] = []
    def remove(argv: list[str], **kwargs: Any) -> Any:
        removed.append(argv)
        if argv[-2] == 'inspect':
            if problem in ('removal-failed', 'still-present'):
                return subprocess.CompletedProcess(argv, 0, stdout='[]', stderr='')
            return subprocess.CompletedProcess(argv, 1, stdout='', stderr='permission denied' if problem == 'inspect-error'
                                               else 'Error: No such object: ' + argv[-1])
        return subprocess.CompletedProcess(argv, int(problem in ('removal-failed', 'auto-removed')),
                                           stdout='', stderr='No such container')

    monkeypatch.setattr(io, '_bounded', bounded)
    monkeypatch.setattr(io.subprocess, 'run', remove)
    files = {'inventory.py': {'mode': '100644', 'data_b64': base64.b64encode(b'reviewed transport bytes').decode()}}
    result = io.run(files, backend, object(), task_root=TASK)
    assert result['status'] == ('ran' if problem in (None, 'auto-removed') else 'unavailable')
    assert len(seen) == 1 and len(removed) == 2 and removed[0][-3:-1] == ['rm', '-f']
    assert 'sha256:' + 'a' * 64 in seen[0] and 'tag' not in seen[0]


def reviewed_oracle(program: str, *, extra_test: bool = False, empty_tests: bool = False,
                    renamed_legacy: bool = False, no_legacy: bool = False) -> dict[str, Any]:
    """Host test emulator accepts named committed B1 programs only, never an
    arbitrary candidate path or bytes. Production io.run has no such route."""
    engine = load(TASK / 'oracle.py')
    sources = engine.load_sources()
    manifest = json.loads(sources['controls.json'])
    assert program in ('reference', 'alternative', 'fixture', 'replace', 'delegated', 'executable')
    files = {'inventory.py': engine.program('reference' if program in ('delegated', 'executable') else program, manifest, sources)}
    if program in ('delegated', 'executable'):
        files['implementation.py'] = files['inventory.py']
        files['inventory.py'] = b'from implementation import *\nif __name__ == "__main__": raise SystemExit(main())\n'
    if program == 'executable':
        files['helper_cli'] = b'#!/usr/bin/env python3\n' + files['implementation.py']
        files['inventory.py'] = (b'from implementation import *\n'
                                 b'if __name__ == "__main__":\n'
                                 b' import subprocess,sys; raise SystemExit(subprocess.call(["./helper_cli", *sys.argv[1:]]))\n')
    if not empty_tests:
        files.update({'tests/test_legacy.py': sources['fixture/tests/test_legacy.py'],
                      'tests/test_import.py': sources['candidates/test_import.py']})
    if renamed_legacy:
        files['tests/test_existing_api.py'] = files.pop('tests/test_legacy.py')
    if no_legacy:
        files.pop('tests/test_legacy.py')
    if extra_test:
        files['tests/test_extra.py'] = b'import unittest\nclass Extra(unittest.TestCase):\n def test_extra(self): self.assertEqual(1,1)\n'
    job = {'files': {p: {'data_b64': base64.b64encode(data).decode(), 'mode': '100755' if p == 'helper_cli' else '100644'}
                     for p, data in files.items()},
           'engine': (TASK / 'oracle.py').read_text(), 'manifest': manifest,
           'sources': {p: base64.b64encode(data).decode() for p, data in sources.items() if p.endswith('.py')},
           'nonce': 'reviewed-fixtures-only'}
    # This emulator disables UID switching only after the named source guard
    # above; all actual semantic/protection work uses the product driver.
    driver = '''import importlib.util,json,os,subprocess,sys
p=sys.argv[1]
spec=importlib.util.spec_from_file_location('trusted_oracle_driver',p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
real=m.subprocess.Popen
def launch(*args,**kwargs):
 assert kwargs.pop('user')==65534 and kwargs.pop('group')==65534
 assert kwargs.pop('extra_groups')==[]
 return real(*args,**kwargs)
m.subprocess.Popen=launch
m.container_parent=lambda:True
m.main()
'''
    proc = subprocess.run([sys.executable, '-c', driver, str(Path(harness.__file__))],
                          input=json.dumps(job), capture_output=True, text=True, timeout=180, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.splitlines()[-1][len(job['nonce']):])


@pytest.mark.parametrize('program', ['reference', 'alternative', 'fixture', 'replace', 'delegated', 'executable'])
def test_actual_semantics_and_delivered_protection_on_reviewed_controls(program: str, judge: Any) -> None:
    result = reviewed_oracle(program)
    assert result['status'] == 'ran', result
    rows = outcomes(judge, envelope(result))
    assert rows['tests-protect']['outcome'] == 'SATISFIED'
    assert rows['feature-correct']['outcome'] == ('VIOLATED' if program == 'fixture' else 'SATISFIED')
    assert rows['legacy-preserved']['outcome'] == ('VIOLATED' if program == 'replace' else 'SATISFIED')


def test_actual_suite_has_no_five_test_floor_and_empty_suite_fails(judge: Any) -> None:
    larger = reviewed_oracle('reference', extra_test=True)
    assert all(row['count'] == 6 for row in larger['protection'])
    assert outcomes(judge, envelope(larger))['tests-protect']['outcome'] == 'SATISFIED'
    empty = reviewed_oracle('reference', empty_tests=True)
    assert outcomes(judge, envelope(empty))['tests-protect']['outcome'] == 'VIOLATED'


def test_grader_is_registered_and_pins_optional_gate_diagnostic() -> None:
    grader = verify.GraderDef.load(TASK)
    assert grader.optional_criteria == ('gate-ran',)
    assert grader.id == 'change-with-regression-568'
    assert len(grader.digest()) == len('sha256:') + 64


@pytest.mark.parametrize("fault", ["changed", "extra-file", "symlink"])
def test_builder_dependency_gate_refuses_drift(tmp_path: Path, build: Any, fault: str) -> None:
    import shutil
    expected = json.loads((TASK / "builder/inputs.json").read_text())
    for name in expected:
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    build.validate_inputs(tmp_path)
    if fault == "changed":
        source = tmp_path / "skillc/inventory_oracle_harness.py"
        source.write_bytes(source.read_bytes() + b"\n")
    elif fault == "extra-file":
        (tmp_path / TASK.relative_to(ROOT) / "fixture/extra.py").write_text("# unapproved extra file\n")
    else:
        source = tmp_path / "skillc/inventory_oracle_harness.py"
        data = source.read_bytes()
        source.unlink()
        target = tmp_path / "redirected.py"
        target.write_bytes(data)
        source.symlink_to(target)
    with pytest.raises(ValueError, match="dependency|population|redirected"):
        build.validate_inputs(tmp_path)


def test_568_honesty_role_is_explicitly_none_for_the_pinned_grader() -> None:
    from skillc import calibration_run as cr
    grader = verify.GraderDef.load(TASK)
    identity = (TASK.relative_to(ROOT).as_posix(), grader.id, grader.revision, grader.digest())
    assert identity in cr._HONESTY_ROLES and cr._HONESTY_ROLES[identity] is None
    bound = cr._honesty_beside({'graded': {'criteria': []}}, task_path=identity[0], grader=grader.identity())
    assert bound['reason'] == 'bound task declares no process-honesty role'


@pytest.mark.parametrize('blind', [False, True])
def test_oracle_sweep_distinguishes_a_live_escaped_child(tmp_path: Path, blind: bool) -> None:
    # Only this committed, bounded process-control program runs in the host
    # emulator; it accepts no candidate bytes/path. The blind arm is a known
    # broken cleanup implementation and must expose a surviving child.
    driver = r'''
import ctypes,importlib.util,json,pathlib,subprocess,sys,time
spec=importlib.util.spec_from_file_location('trusted_driver',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
real=m.subprocess.Popen
def launch(*args,**kwargs):
 assert kwargs.pop('user')==65534 and kwargs.pop('group')==65534
 assert kwargs.pop('extra_groups')==[]
 return real(*args,**kwargs)
m.subprocess.Popen=launch
original=m.sweep
root=pathlib.Path(sys.argv[2]); blind=sys.argv[3]=='True'
if blind: m.sweep=lambda:None
child="import os,pathlib,time;os.setsid();pathlib.Path('escaped.pid').write_text(str(os.getpid()));time.sleep(20)"
parent="import pathlib,subprocess,sys,time;subprocess.Popen([sys.executable,'-c',"+repr(child)+"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);end=time.monotonic()+2\nwhile not pathlib.Path('escaped.pid').exists() and time.monotonic()<end: time.sleep(.01)\nassert pathlib.Path('escaped.pid').exists()"
class Budget:
 deadline=time.monotonic()+15; capacity=1024*1024; used=0; processes=0
 def check(self): pass
try:
 m.execute([sys.executable,'-c',parent],root,Budget())
 pid=int((root/'escaped.pid').read_text())
 p=pathlib.Path('/proc')/str(pid)/'stat'
 alive=p.exists() and p.read_text().rsplit(')',1)[1].split()[0] not in ('Z','X')
 print(json.dumps({'contained':not alive,'pid_was_observed':True}))
finally:
 original()
'''
    result = subprocess.run([sys.executable, '-c', driver, str(Path(harness.__file__)), str(tmp_path), str(blind)],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'contained': not blind, 'pid_was_observed': True}


def test_oracle_uses_the_attempts_captured_daemon_for_run_and_cleanup(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, judge: Any) -> None:
    from types import SimpleNamespace
    backend = DockerBackend(image='tag', base_dir=tmp_path)
    monkeypatch.setattr(DockerBackend, 'image_id', lambda self, handle: 'sha256:' + 'a' * 64)
    held = {'DOCKER_HOST': 'unix:///fixture-held-daemon'}
    monkeypatch.setenv('DOCKER_HOST', 'unix:///fixture-ambient-daemon')
    seen: list[dict[str, str]] = []
    def bounded(argv: list[str], data: str, **kwargs: Any) -> tuple[int, bytes, None]:
        seen.append(dict(kwargs['env']))
        monkeypatch.setenv('DOCKER_HOST', 'unix:///fixture-changed-daemon')
        job = json.loads(data)
        return 0, (job['nonce'] + json.dumps(oracle_good(judge)) + '\n').encode(), None
    def command(argv: list[str], **kwargs: Any) -> Any:
        seen.append(dict(kwargs['env']))
        return subprocess.CompletedProcess(argv, int(argv[-2] == 'inspect'), stdout='',
                                           stderr='Error: No such object: ' + argv[-1])
    monkeypatch.setattr(io, '_bounded', bounded)
    monkeypatch.setattr(subprocess, 'run', command)
    files = {'inventory.py': {'mode': '100644', 'data_b64': ''}}
    result = io.run(files, backend, SimpleNamespace(env=held), task_root=TASK)
    assert result['status'] == 'ran'
    assert len(seen) == 3 and all(env == held for env in seen)


def test_oracle_entrypoint_refuses_host_context_before_reading_candidate_code(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    # Root alone is insufficient: a host process is not container PID 1.
    monkeypatch.setattr(harness, 'os', SimpleNamespace(getpid=lambda: 999, geteuid=lambda: 0))
    monkeypatch.setattr(harness, 'ctypes', SimpleNamespace(CDLL=lambda *args, **kwargs: SimpleNamespace(prctl=lambda *a: 0)))
    with pytest.raises(RuntimeError, match='isolated container parent'):
        harness.evaluate({'files': {}, 'engine': "raise AssertionError('engine must not execute on host')"})


def test_legacy_test_protection_is_behavioral_and_accepts_renaming(judge: Any) -> None:
    renamed = reviewed_oracle('reference', renamed_legacy=True)
    assert outcomes(judge, envelope(renamed))['tests-protect']['outcome'] == 'SATISFIED'
    missing = reviewed_oracle('reference', no_legacy=True)
    assert outcomes(judge, envelope(missing))['tests-protect']['outcome'] == 'VIOLATED'
    assert next(row for row in missing['protection'] if row['program'] == 'legacy-api')['ok'] is True


def test_oracle_transport_timeout_covers_a_client_that_never_reads_stdin() -> None:
    import os
    import signal
    driver = '''import json,sys,time
from skillc import inventory_oracle as io
bound=io._bounded if hasattr(io,'_bounded') else io.transport._bounded
start=time.monotonic()
code,out,problem=bound([sys.executable,'-c','import time;time.sleep(20)'],'x'*1048576,timeout=.2,limit=1024,env=None)
print(json.dumps({'problem':problem,'seconds':time.monotonic()-start}))
'''
    process = subprocess.Popen([sys.executable, '-c', driver], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        out, err = process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        # Known broken input writer: kill the still-owned group before reaping.
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        pytest.fail('stdin backpressure escaped the transport timeout')
    assert process.returncode == 0, err
    result = json.loads(out)
    assert result['problem'] == 'timeout' and result['seconds'] < 2


@pytest.mark.parametrize(('program', 'data', 'limit', 'expected'), [
    ('import sys;sys.stdout.write(sys.stdin.read())', 'hello', 10, None),
    ('import sys;sys.stdout.write("x"*65536)', '', 1024, 'output-over-bound'),
    ('raise AssertionError("must not run")', 'x' * (8 * 1024 * 1024 + 1), 10, 'input-over-bound'),
])
def test_oracle_transport_bounds_both_pipes(program: str, data: str, limit: int, expected: str | None) -> None:
    code, output, problem = io._bounded([sys.executable, '-c', program], data, timeout=2, limit=limit, env=None)
    assert problem == expected
    assert len(output) <= limit
    if expected is None:
        assert code == 0
        assert output == b'hello'
