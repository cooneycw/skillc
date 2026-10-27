"""#576 opt-in controls. Offline process evidence, never physical certification."""
from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ci import check_real_docker_ran as c
from ci import real_docker_trigger as t


@pytest.mark.parametrize("enabled", [False, True])
def test_actual_gated_node_is_distinct_from_file_floor(tmp_path: Path, enabled: bool) -> None:
    """A real skipped node beside a passing sibling exposes the old floor limit."""
    module = tmp_path / "tests" / "test_profile_flow_auto_87ecb097_cold.py"
    module.parent.mkdir()
    module.write_text(
        "import os,pytest\npytestmark=pytest.mark.real_docker\n"
        "@pytest.mark.skipif(os.environ.get('SKILLC_FLOW_AUTO_COLD') != '1',reason='opt-in')\n"
        "def test_actual_cold_profile(): pass\n"
        "def test_sibling(): pass\n")
    report = tmp_path / "report.xml"
    env = dict(os.environ)
    env.pop("SKILLC_FLOW_AUTO_COLD", None)
    if enabled:
        env["SKILLC_FLOW_AUTO_COLD"] = "1"
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", str(module),
                             f"--junitxml={report}", "-m", "real_docker", "-o", "addopts="],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    cases = list(ET.parse(report).iter("testcase"))
    wanted = next(case for case in cases if case.get("name") == "test_actual_cold_profile")
    assert (wanted.find("skipped") is None) == enabled
    assert c.verdict(str(report), declared_files=("tests.test_profile_flow_auto_87ecb097_cold",)).status == c.SUCCESS
    from ci import real_docker_optin as o
    assert o.population(report.read_bytes(), o.FLOW_AUTO_COLD) == (
        ("SUCCESS", 1) if enabled else ("ERROR", 0))
    # Retained input proves the ordinary per-file floor cannot certify this node.
    assert sum(case.find("skipped") is None for case in cases) == (2 if enabled else 1)


def test_nonowner_and_seen_optin_inputs_are_invariants() -> None:
    command = f"/run-real-docker {'a' * 40} --opt-in flow-auto-cold"
    comments: list[dict[str, object]] = [{"id": 1, "user": {"login": "other"}, "body": command}]
    first = t.select_requested_shas(comments, owner_login="owner", processed_ids=frozenset())
    assert not first.requests and first.newly_seen_ids == (1,)
    comments[0]["user"] = {"login": "owner"}
    again = t.select_requested_shas(comments, owner_login="owner", processed_ids=frozenset({1}))
    assert not again.requests and not again.newly_seen_ids


@pytest.mark.parametrize(("cases", "status", "count"), [
    ('<testcase classname="tests.test_profile_flow_auto_87ecb097_cold" name="test_actual_cold_profile"/>', "SUCCESS", 1),
    ('<testcase classname="tests.test_profile_flow_auto_87ecb097_cold" name="test_actual_cold_profile"><skipped/></testcase>', "ERROR", 0),
    ('', "ERROR", 0),
    ('<testcase classname="other" name="test_actual_cold_profile"/>', "ERROR", 0),
])
def test_exact_population_controls(cases: str, status: str, count: int) -> None:
    from ci import real_docker_optin as o
    assert o.population(f'<testsuite>{cases}</testsuite>'.encode(), o.FLOW_AUTO_COLD) == (status, count)
    if status == 'SUCCESS':
        assert o.population(f'<testsuite>{cases}{cases}</testsuite>'.encode(), o.FLOW_AUTO_COLD) == ('ERROR', 0)


@pytest.mark.parametrize("fault", ["bytes", "inodes", "unreadable", "none"])
@pytest.mark.parametrize("bad_index", [1, 2])
def test_headroom_checks_both_filesystems(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, bad_index: int) -> None:
    from types import SimpleNamespace

    from ci import real_docker_optin as o
    calls: list[Path] = []
    policy = o.FLOW_AUTO_COLD
    def stats(path: Path) -> SimpleNamespace:
        calls.append(path)
        bad = len(calls) == bad_index
        if bad and fault == 'unreadable':
            raise OSError('controlled')
        return SimpleNamespace(f_bavail=policy.free_bytes - int(bad and fault == 'bytes'), f_frsize=1,
                               f_favail=policy.free_inodes - int(bad and fault == 'inodes'))
    monkeypatch.setattr(o.os, 'statvfs', stats)
    paths = (tmp_path, tmp_path)
    if fault == 'none':
        o.headroom(paths, policy)
    else:
        with pytest.raises((ValueError, OSError)):
            o.headroom(paths, policy)
    assert len(calls) == (2 if fault == "none" else bad_index)


def test_execution_wall_budget_stops_own_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    command = tmp_path / 'uv'
    command.write_text(f'#!{sys.executable}\nimport pathlib,time\npathlib.Path("started").write_text("yes")\ntime.sleep(30)\n')
    command.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path))
    report = tmp_path / 'old.xml'
    report.write_text('<testsuite/>')
    code = "import dataclasses,pathlib,sys;from ci import real_docker_optin as o;sys.exit(o.execute(pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[1])/'old.xml',dataclasses.replace(o.FLOW_AUTO_COLD,seconds=1)))"
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                            cwd=Path(__file__).resolve().parents[1], timeout=10, check=False)
    assert result.returncode == 124
    assert (tmp_path / 'started').exists() and not report.exists()


def test_custody_rejects_checkout_and_preserves_missing_report(tmp_path: Path) -> None:
    import json

    from ci import real_docker_optin as o
    work = tmp_path / 'work'
    (work / 'reports').mkdir(parents=True)
    report = work / 'reports' / 'absent.xml'
    with pytest.raises(ValueError, match='outside'):
        o.publish(report, evidence=work / 'retained', name='flow-auto-cold', sha='a'*40, runner_sha='b'*40, run_code=0)
    status, _, _ = o.publish(report, evidence=tmp_path / 'retained', name='flow-auto-cold', sha='a'*40, runner_sha='b'*40, run_code=0)
    assert status == 'ERROR'
    binding = next((tmp_path / 'retained').glob('*/binding.json'))
    assert json.loads(binding.read_text())['report_sha256'] is None
    assert not binding.with_name('junit.xml').exists()


@pytest.mark.parametrize('selection', ['deselected', 'missing'])
def test_actual_unexecuted_named_node_is_error(tmp_path: Path, selection: str) -> None:
    from ci import real_docker_optin as o
    module = tmp_path / 'tests' / 'test_profile_flow_auto_87ecb097_cold.py'
    module.parent.mkdir()
    module.write_text('def test_actual_cold_profile(): pass\ndef test_sibling(): pass\n')
    report = tmp_path / 'report.xml'
    args = [str(module), '-k', 'sibling'] if selection == 'deselected' else [str(module) + '::missing_node']
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', *args, f'--junitxml={report}'],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == (0 if selection == 'deselected' else 4), result.stderr
    assert o.population(report.read_bytes(), o.FLOW_AUTO_COLD) == ('ERROR', 0)


@pytest.mark.parametrize('args', [
    ['--break', 'none', '--trailing', 'ignored'],
    ['--opt-in', ''],
    ['--opt-in', 'flow-auto-cold', '--break', 'trialimage:no-uv'],
    ['--opt-in', 'flow-auto-cold', '--opt-in', 'flow-auto-cold'],
])
def test_strict_parser_never_uses_certifying_route_for_invalid_optin(args: list[str]) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(['bash', str(root / 'ci/real-docker/run-real-docker'), 'a'*40, *args],
                            env={'SKILLC_REAL_DOCKER_CONFIG': '/absent/config'},
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 2 and 'usage:' in result.stderr
    assert 'config file' not in result.stderr


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux child adoption control')
def test_timeout_stops_and_reaps_owned_descendant(tmp_path: Path) -> None:
    """Adopt grandchildren inside an isolated probe so PID 1 cannot hide a red."""
    command = tmp_path / 'uv'
    command.write_text(
        f'#!{sys.executable}\nimport subprocess,sys,pathlib,time\n'
        'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\n'
        'pathlib.Path("child.pid").write_text(str(p.pid))\ntime.sleep(30)\n')
    command.chmod(0o700)
    probe = '''import ctypes,dataclasses,os,pathlib,sys
from ci import real_docker_optin as o
assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
work=pathlib.Path(sys.argv[1])
os.environ['PATH']=str(work)
assert o.execute(work,work/'report.xml',dataclasses.replace(o.FLOW_AUTO_COLD,seconds=1))==124
pid=int((work/'child.pid').read_text())
try:
 reaped,status=os.waitpid(pid,0)
 assert reaped==pid and os.WIFSIGNALED(status)
except ChildProcessError:
 assert not pathlib.Path(f'/proc/{pid}').exists()
print('owned descendant stopped and reaped')
'''
    result = subprocess.run([sys.executable, '-c', probe, str(tmp_path)],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert 'owned descendant stopped and reaped' in result.stdout


def test_report_symlink_cannot_move_checkout_custody_boundary(tmp_path: Path) -> None:
    from ci import real_docker_optin as o
    work = tmp_path / 'checkout'
    (work / 'reports').mkdir(parents=True)
    external = tmp_path / 'outside' / 'nested'
    external.mkdir(parents=True)
    source = external / 'report.xml'
    source.write_text('<testsuite/>')
    report = work / 'reports' / 'report.xml'
    report.symlink_to(source)
    with pytest.raises(ValueError, match='outside'):
        o.publish(report, name='flow-auto-cold', sha='a'*40, runner_sha='b'*40,
                  evidence=work / 'retained', run_code=0)


@pytest.mark.parametrize('phase', ['setup', 'call'])
def test_actual_pytest_setup_error_is_not_executed_call(tmp_path: Path, phase: str) -> None:
    from ci import real_docker_optin as o
    module = tmp_path / 'tests/test_profile_flow_auto_87ecb097_cold.py'
    module.parent.mkdir()
    module.write_text('import pytest\n@pytest.fixture\ndef broken(): raise RuntimeError("setup")\n'
                      + ('def test_actual_cold_profile(broken): pass\n' if phase == 'setup'
                         else 'def test_actual_cold_profile(): assert False\n'))
    report = tmp_path / 'report.xml'
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', str(module), f'--junitxml={report}'],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 1
    assert o.population(report.read_bytes(), o.FLOW_AUTO_COLD) == (
        ('ERROR', 0) if phase == 'setup' else ('FAILURE', 1))


def test_description_binds_full_report_digest_node_and_counts(tmp_path: Path) -> None:
    import hashlib

    from ci import real_docker_optin as o
    report = tmp_path / 'checkout/reports/report.xml'; report.parent.mkdir(parents=True)
    report.write_text('<testsuite><testcase classname="tests.test_profile_flow_auto_87ecb097_cold" '
                      'name="test_actual_cold_profile"/></testsuite>')
    status, description, body = o.publish(report, name='flow-auto-cold', sha='a'*40, runner_sha='b'*40,
                                          evidence=tmp_path / 'retained', run_code=0)
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    assert status == 'SUCCESS'
    assert description == f'1/1 {o.FLOW_AUTO_COLD.nodes[0]} {digest}'
    assert len(description) == 140 and digest in body and o.FLOW_AUTO_COLD.nodes[0] in body


def test_duplicate_break_none_is_rejected_before_config() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(['bash', str(root / 'ci/real-docker/run-real-docker'), 'a'*40,
                             '--break', 'none', '--break', 'channel:omit-mount'],
                            env={'SKILLC_REAL_DOCKER_CONFIG': '/absent/config'},
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 2 and 'usage:' in result.stderr
    assert 'config file' not in result.stderr


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux owned descendant control')
@pytest.mark.parametrize('scenario', ['escape-timeout', 'escape-exit', 'sigterm', 'sigint', 'sigterm-repeat'])
def test_owned_session_escape_and_helper_signal_cleanup(tmp_path: Path, scenario: str) -> None:
    command = tmp_path / 'uv'
    command.write_text(f'#!{sys.executable}\nimport pathlib,subprocess,sys,time\n'
        'marker=pathlib.Path("child.pid")\n'
        'if not marker.exists():\n'
        ' p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],start_new_session=True)\n'
        ' marker.write_text(str(p.pid))\n'
        + ('time.sleep(30)\n' if scenario != 'escape-exit' else ''))
    command.chmod(0o700)
    probe = '''import ctypes,json,os,pathlib,signal,subprocess,sys,time
assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0
work=pathlib.Path(sys.argv[1]);scenario=sys.argv[2]
sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
code="import dataclasses,pathlib,sys;from ci import real_docker_optin as o;sys.exit(o.execute(pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[1])/'report.xml',dataclasses.replace(o.FLOW_AUTO_COLD,seconds=int(sys.argv[2]))))"
env=dict(os.environ);env['PATH']=str(work)
p=subprocess.Popen([sys.executable,'-c',code,str(work),'30' if scenario.startswith('sig') else '1'],env=env,start_new_session=True)
try:
 end=time.monotonic()+5
 while not (work/'child.pid').exists() and time.monotonic()<end: time.sleep(.01)
 assert (work/'child.pid').exists(),'controlled child did not start'
 pid=int((work/'child.pid').read_text())
 if scenario.startswith('sig'):
  os.kill(p.pid,signal.SIGTERM if scenario.startswith('sigterm') else signal.SIGINT)
  if scenario=='sigterm-repeat':
   for _ in range(5):
    try:os.kill(p.pid,signal.SIGTERM)
    except ProcessLookupError:break
    time.sleep(.005)
 p.wait(timeout=5)
 stat=pathlib.Path('/proc')/str(pid)/'stat'
 alive=stat.exists() and stat.read_text().split(') ')[1].split()[0]!='Z'
 protected=sentinel.poll() is None
 print(json.dumps({'survivor':alive,'sentinel_protected':protected,'helper_exit':p.returncode}))
finally:
 sentinel.terminate();sentinel.wait()
 end=time.monotonic()+5
 while time.monotonic()<end:
  children=pathlib.Path(f'/proc/self/task/{os.getpid()}/children').read_text().split()
  if not children:break
  for child in children:
   try:os.kill(int(child),signal.SIGKILL)
   except ProcessLookupError:pass
  while True:
   try:
    found,_=os.waitpid(-1,os.WNOHANG)
    if not found:break
   except ChildProcessError:break
  time.sleep(.01)
assert protected and not alive,'owned child survived or unrelated sentinel was touched'
'''
    result = subprocess.run([sys.executable, '-c', probe, str(tmp_path), scenario],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('fault', ['unsupported', 'unreadable', 'unconfirmed', 'shared-budget', 'late', 'healthy'])
def test_owned_helper_refuses_unverified_cleanup_and_budget_reset(tmp_path: Path, fault: str) -> None:
    command = tmp_path / 'uv'
    command.write_text(f'#!{sys.executable}\nimport pathlib,sys,time\n'
        'with pathlib.Path("calls").open("a") as f:f.write(sys.argv[1]+"\\n")\n'
        + ('time.sleep(.8 if sys.argv[1]=="sync" else 1.4)\n' if fault == 'shared-budget' else ''))
    command.chmod(0o700)
    probe = '''import dataclasses,os,pathlib,sys,types
from ci import real_docker_optin as o
work=pathlib.Path(sys.argv[1]);fault=sys.argv[2];os.environ['PATH']=str(work)
if fault=='unsupported':o.ctypes.CDLL=lambda *a,**kw:types.SimpleNamespace(prctl=lambda *a:1)
if fault=='unreadable':
 def unavailable():raise OSError('controlled ownership failure')
 o.owned_children=unavailable
if fault=='unconfirmed':o.sweep=lambda:False
if fault=='late':
 import time
 original=o.sweep;count=[0]
 def late():
  count[0]+=1
  if count[0]==3:time.sleep(2.1)
  return original()
 o.sweep=late
result=o.execute(work,work/'report.xml',dataclasses.replace(o.FLOW_AUTO_COLD,seconds=2))
print(result)
'''
    result = subprocess.run([sys.executable, '-c', probe, str(tmp_path), fault],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) == (0 if fault == 'healthy' else 124 if fault in {'shared-budget', 'late'} else 2)
    calls = tmp_path / 'calls'
    if fault in {'unsupported', 'unreadable'}:
        assert not calls.exists()
    elif fault != 'unconfirmed':
        assert calls.read_text().splitlines() == ['sync', 'run']
