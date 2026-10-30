"""Plant real trusted Git/files/process state; verify the collector sees it."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_clutter_inventory import declaration

from skillc import clutter as c
from skillc import clutter_capture as capture
from skillc.clutter_controller import Inventory, bounded_command, daemon_surfaces
from skillc.docker_backend import CANDIDATE_GID, CANDIDATE_UID


@pytest.mark.skipif(os.geteuid() != 0, reason='cross-user kernel probe requires controller root')
def test_kernel_cwd_is_readable_for_the_candidate_identity() -> None:
    child = subprocess.Popen([sys.executable, '-I', '-S', '-c', 'import time; time.sleep(30)'],
                             cwd='/tmp', user=CANDIDATE_UID, group=CANDIDATE_GID)
    try:
        observed = capture._cwd_stat(Path('/proc') / str(child.pid))
        expected = os.stat('/tmp')
        assert (observed.st_dev, observed.st_ino) == (expected.st_dev, expected.st_ino)
        assert os.geteuid() == 0
    finally:
        child.terminate()
        child.wait(timeout=5)


@pytest.mark.parametrize('refuse', [False, True])
def test_filesystem_credentials_restore_after_success_or_refusal(monkeypatch: pytest.MonkeyPatch,
                                                               refuse: bool) -> None:
    class Setter:
        def __init__(self) -> None:
            self.value = 0

        def __call__(self, value: int) -> int:
            previous = self.value
            if value != (1 << 32) - 1 and not (refuse and value == 10001):
                self.value = value
            return previous

    class Libc:
        setfsuid = Setter()
        setfsgid = Setter()

    libc = Libc()
    monkeypatch.setattr(capture.ctypes, 'CDLL', lambda *_args, **_kwargs: libc)
    if refuse:
        with (pytest.raises(PermissionError, match='transition'),
              capture._filesystem_ids(10001, 10001)):
            pytest.fail('refused credentials must not yield a readable surface')
    else:
        with capture._filesystem_ids(10001, 10001):
            assert libc.setfsuid.value == libc.setfsgid.value == 10001
    assert libc.setfsuid.value == libc.setfsgid.value == 0


def git(root: Path, *args: str) -> None:
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
                            timeout=10, check=False,
                            env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
    assert result.returncode == 0, result.stderr


@pytest.fixture
def namespace(tmp_path: Path) -> tuple[Path, c.Policy, Path]:
    root = tmp_path / 'namespace'
    repo = root / 'work/repo'
    repo.mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    git(repo, 'config', 'user.name', 'Fixture')
    git(repo, 'config', 'user.email', 'fixture@example.invalid')
    (repo / 'base.txt').write_text('initial\n')
    (repo / '.gitignore').write_text('ignored.log\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'initial')
    git(repo, 'clone', '-q', '--bare', str(repo), str(root / 'work/fixture.git'))
    raw = declaration()
    for kind in c.CPP_KINDS:
        if kind != 'registry':
            (root / 'state' / kind).mkdir(parents=True)
    (root / 'state/registry.json').write_text('{"waves": {}}\n')
    (root / 'state/mailboxes/inbox.md').write_text('')
    for name in ('shared', 'tmp', 'proc'):
        (root / name).mkdir()
    return root, c.parse_policy(raw), root / 'proc'


def inventory(root: Path, policy: c.Policy, proc: Path) -> Inventory:
    return Inventory(policy, {'agent': lambda: capture.capture_role(policy, 'agent', root,
                     proc_root=proc, namespace_root=str(root))}, lambda: capture.capture_shared(policy, root),
                     lambda: {'containers': c.Surface({}), 'networks': c.Surface({})})


@pytest.mark.parametrize('leftover', ['worktree', 'local-branch', 'remote-branch', 'stash', 'ignored-file',
                                    'lock', 'registry', 'mailbox', 'cursor', 'heartbeat', 'claim', 'temp', 'shared'])
def test_planted_real_resources_are_not_clean(namespace: tuple[Path, c.Policy, Path], leftover: str) -> None:
    root, policy, proc = namespace
    repo = root / 'work/repo'
    observer = inventory(root, policy, proc)
    before = observer.capture('before')
    assert all(row.complete for row in before.surfaces.values()), before
    if leftover == 'worktree':
        git(repo, 'worktree', 'add', '-qb', 'task-leftover', str(root / 'work/leftover'))
    elif leftover == 'local-branch':
        git(repo, 'branch', 'task-leftover')
    elif leftover == 'remote-branch':
        git(root / 'work/fixture.git', 'branch', 'task-leftover', 'main')
    elif leftover == 'stash':
        (repo / 'base.txt').write_text('saved work\n')
        git(repo, 'stash', 'push', '-qm', 'task-leftover')
    elif leftover == 'ignored-file':
        (repo / 'ignored.log').write_text('leftover\n')
    elif leftover == 'registry':
        (root / 'state/registry.json').write_text('{"waves": {"task": {"role": "worker"}}}\n')
    elif leftover == 'mailbox':
        (root / 'state/mailboxes/inbox.md').write_text(
            '<!-- cc-flow-wave-msg rev=1 from=worker to=orchestrator ts=0 -->\nleftover\n')
    elif leftover == 'temp':
        (root / 'tmp/task-leftover').mkdir()
    elif leftover == 'shared':
        (root / 'shared/task-leftover').write_text('state')
    else:
        family = {'lock': 'locks', 'cursor': 'cursors', 'heartbeat': 'heartbeats', 'claim': 'claims'}[leftover]
        (root / 'state' / family / 'task-leftover').write_text('state')
    after = observer.capture('after')
    report = c.classify(policy, before, after)
    assert report['status'] == 'NOT_CLEAN', report
    assert report['counts']['clutter'] > 0
    if leftover in ('registry', 'mailbox'):
        expected = 'entry:' if leftover == 'registry' else 'message:'
        assert any(row['key'].startswith(expected) for row in report['additions']['clutter'])
        assert report['preservation']['changed']  # pre-existing storage file changed, entry was ADDED


@pytest.mark.parametrize('alternative', [False, True])
def test_real_cleanup_and_alternative_order_leave_no_clutter(namespace: tuple[Path, c.Policy, Path], alternative: bool) -> None:
    root, policy, proc = namespace
    repo = root / 'work/repo'
    observer = inventory(root, policy, proc)
    before = observer.capture('before')
    git(repo, 'worktree', 'add', '-qb', 'task-leftover', str(root / 'work/leftover'))
    (repo / 'base.txt').write_text('saved work\n')
    git(repo, 'stash', 'push', '-qm', 'temporary')
    operations = [lambda: git(repo, 'worktree', 'remove', str(root / 'work/leftover')),
                  lambda: git(repo, 'stash', 'drop', '-q')]
    if alternative:
        operations.reverse()
    for operation in operations:
        operation()
    git(repo, 'branch', '-D', 'task-leftover')
    (repo / 'result.txt').write_text('delivered\n')
    report = c.classify(policy, before, observer.capture('after'))
    assert report['status'] == 'CLEAN', report
    assert report['counts'] == {'delivered': 1, 'declared-allowed': 0, 'clutter': 0}


@pytest.mark.parametrize('name', ['watch', 'supervise'])
def test_actual_orphan_process_is_seen_from_its_kernel_identity(namespace: tuple[Path, c.Policy, Path], name: str) -> None:
    root, policy, proc = namespace
    observer = inventory(root, policy, proc)
    before = observer.capture('before')
    # Fixed trusted sleeping client only. The proc view exposes exactly this
    # owned test child; no external processes or arbitrary subject code run.
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', name],
                             cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        (proc / str(child.pid)).symlink_to(Path('/proc') / str(child.pid), target_is_directory=True)
        after = observer.capture('after')
        report = c.classify(policy, before, after)
        assert report['status'] == 'NOT_CLEAN', report
        assert any(row['surface'] == 'agent/processes' for row in report['additions']['clutter'])
    finally:
        child.terminate()
        child.wait(timeout=5)


@pytest.mark.parametrize('recreate', [False, True])
def test_deleted_kernel_cwd_is_reported_even_after_path_recreation(namespace: tuple[Path, c.Policy, Path], recreate: bool) -> None:
    root, policy, proc = namespace
    cwd = root / 'tmp/cwd'
    cwd.mkdir()
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], cwd=cwd,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        (proc / str(child.pid)).symlink_to(Path('/proc') / str(child.pid), target_is_directory=True)
        observer = inventory(root, policy, proc)
        before = observer.capture('before')
        cwd.rmdir()
        if recreate:
            cwd.mkdir()
        report = c.classify(policy, before, observer.capture('after'))
        assert report['counts']['clutter'] == 0, report
        assert report['preservation']['deleted-cwd']
    finally:
        child.terminate()
        child.wait(timeout=5)


@pytest.mark.parametrize('fault', ['unreachable', 'malformed', 'missing', 'duplicate', 'foreign'])
def test_daemon_membership_failure_never_certifies_clean(fault: str) -> None:
    identity = 'a' * 64

    def read(argv: list[str], **_: Any) -> bytes:
        if 'inspect' not in argv:
            if fault == 'unreachable':
                raise OSError('unreachable')
            return (identity + '\n').encode()
        if fault == 'malformed':
            return b'not JSON'
        if fault == 'missing':
            return b'[]'
        row = {'Id': 'b' * 64 if fault == 'foreign' else identity,
               'Name': 'fixture', 'State': {'Status': 'running'}}
        return json.dumps([row, row] if fault == 'duplicate' else [row]).encode()
    result = daemon_surfaces(('docker',), {}, read=read)
    assert all(not row.complete for row in result.values())


def test_complete_daemon_population_and_an_explicit_empty_census_are_distinct_from_failure() -> None:
    identity = 'a' * 64
    calls: list[list[str]] = []

    def read(argv: list[str], **_: Any) -> bytes:
        calls.append(argv)
        if 'inspect' not in argv:
            return (identity + '\n').encode()
        return json.dumps([{'Id': identity, 'Name': 'fixture', 'State': {'Status': 'running'}}]).encode()
    result = daemon_surfaces(('docker',), {}, read=read)
    assert all(row.complete and set(row.items) == {identity} for row in result.values())
    assert len(calls) == 4
    empty = daemon_surfaces(('docker',), {}, read=lambda *_args, **_kwargs: b'')
    assert all(row.complete and not row.items for row in empty.values())


@pytest.mark.parametrize(('program', 'problem'), [
    ('import time; time.sleep(20)', 'timeout'),
    ('import sys; sys.stdout.write("x"*65536)', 'output bound'),
])
def test_inventory_transport_refuses_hang_and_flood(program: str, problem: str) -> None:
    with pytest.raises(ValueError, match=problem):
        bounded_command([sys.executable, '-c', program], env=None, timeout=.2, limit=1024)


def test_pid_reuse_during_a_census_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = tmp_path / 'proc'
    process = proc / '7'
    process.mkdir(parents=True)
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    (process / 'cwd').symlink_to(cwd, target_is_directory=True)
    (process / 'comm').write_text('watch\n')
    uid, gid = os.getuid(), os.getgid()
    (process / 'status').write_text(f'Uid:\t{uid} {uid} {uid} {uid}\nGid:\t{gid} {gid} {gid} {gid}\n')
    target = process / 'stat'
    target.write_text('unused')
    original = Path.read_text
    counter = [100]

    def read(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == target:
            counter[0] += 1
            fields = ['S', *(['0'] * 18), str(counter[0])]
            return '7 (watch) ' + ' '.join(fields)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    assert capture.processes(proc).complete is False


def test_export_reads_do_not_run_subject_git_configuration(namespace: tuple[Path, c.Policy, Path],
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    root, policy, proc = namespace
    with (root / 'work/repo/.git/config').open('a') as stream:
        stream.write('\n[alias]\n  status = !exit 99\n')
    def refused(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError('subject Git must never execute on the controller')
    monkeypatch.setattr(subprocess, 'run', refused)
    rows = capture.capture_role(policy, 'agent', root, proc_root=proc, namespace_root=str(root))
    assert rows['agent/local-branches'].complete
    assert 'refs/heads/main' in rows['agent/local-branches'].items


def test_unreadable_scope_special_file_and_read_budget_never_certify(namespace: tuple[Path, c.Policy, Path],
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    root, policy, proc = namespace
    reader = inventory(root, policy, proc)
    assert all(row.complete for row in reader.capture('before').surfaces.values())
    source = root / 'state/registry.json'
    source.unlink()
    os.mkfifo(source)
    report = c.classify(policy, reader.capture('before'), reader.capture('after'))
    assert report['status'] == 'UNKNOWN'
    source.unlink()
    source.write_text('{"waves": {}}')
    monkeypatch.setattr(capture, 'MAX_BYTES', 1)
    bounded = reader.capture('before')
    assert not bounded.surfaces['agent/local-branches'].complete
    assert c.classify(policy, bounded, reader.capture('after'))['status'] == 'UNKNOWN'


def test_missing_shared_volume_is_unknown_not_an_empty_volume(namespace: tuple[Path, c.Policy, Path]) -> None:
    root, policy, proc = namespace
    reader = inventory(root, policy, proc)
    before = reader.capture('before')
    (root / 'shared').rmdir()
    report = c.classify(policy, before, reader.capture('after'))
    assert report['status'] == 'UNKNOWN'
    assert any(row['surface'] == 'shared' for row in report['unknown'])
