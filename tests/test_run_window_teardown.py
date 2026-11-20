"""Contract A part 2 (#797 A-2): teardown boundary, facts 2, 2b and 3.

These qualify NEW instruments; none claims a red run on the parent. A fake
/proc (`FakeProc`) drives the boundary logic: per-task views, a container root
view, and hidden or chrooted tables. Every case therefore runs as root or not.
Fact 2 also runs against REAL child processes, gated on the kernel actually
granting the access it needs; production turns a denial into
OBSERVATION_FAILED. Each case a blind checker could pass is paired with that
checker (`blind_*`), which must give a different verdict.
"""
from __future__ import annotations

import fcntl
import importlib.util
import os
import stat
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from skillc import run_window_absence as ra
from skillc import run_window_teardown as rt

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux') or not hasattr(os, 'O_PATH'),
                                reason='Contract A requires Linux O_PATH and /proc')

NEG, SURV, FAIL = ra.NEG, ra.SURV, ra.FAIL
CID = 'a' * 64
HOST_NS = {k: f'{k}:[1000{i}]' for i, k in enumerate(rt.NAMESPACES)}
CONTAINER_NS = {k: f'{k}:[2000{i}]' for i, k in enumerate(rt.NAMESPACES)}
CGROUP = '/system.slice/docker-' + CID + '.scope'
ROOT_ROW = '1 0 254:4091 / / rw - ext4 /dev/fake-root rw'
BIND_ROW = '80 1 0:1 / /work/run rw - ext4 /dev/sdb1 rw'
PROC_ROW = '2 1 0:4093 / /proc rw - proc proc rw'
SOCK = stat.S_IFSOCK | 0o600
DIR = stat.S_IFDIR | 0o755
REG = stat.S_IFREG | 0o644
LNK = stat.S_IFLNK | 0o777


def stat_line(pid: str, start: str = '12345', state: str = 'S', comm: str = 'sleep') -> bytes:
    return f'{pid} ({comm}) {state} '.encode() + ' '.join(['0'] * 18 + [start]).encode()


def table(*rows: str) -> bytes:
    return ('\n'.join(rows) + '\n').encode()


def proc_entry(pid: str, *, cgroup: str = '/user.slice', ns: Mapping[str, str] = HOST_NS,
               start: str = '12345', mountinfo: bytes | None = None, fd: dict[str, Any] | None = None,
               map_files: dict[str, Any] | None = None, root_view: dict[str, Any] | None = None,
               tasks: dict[str, dict[str, Any]] | None = None, chrooted: bool = False) -> dict[str, Any]:
    return {'stat': stat_line(pid, start), 'cgroup': f'0::{cgroup}\n'.encode('utf-8', 'surrogateescape'),
            'ns': dict(ns), 'mountinfo': table(ROOT_ROW, PROC_ROW) if mountinfo is None else mountinfo,
            'fd': fd or {}, 'map_files': map_files or {}, 'root_view': root_view or {'/': DIR},
            'tasks': tasks or {}, 'chrooted': chrooted}


def fake_stat(mode: int, *, dev: int = 1, ino: int = 1) -> os.stat_result:
    return os.stat_result((mode, ino, dev, 1, 0, 0, 0, 0, 0, 0))


class FakeProc:
    """A /proc tree from dicts. A node is a pid or 'pid/task/tid'; a task
    uses its own dict where one is given, otherwise its process's. 'self' is
    the controller. `errors[(node, what)]` raises there; `vanish` hides a pid
    from later listings once it fails."""

    def __init__(self, procs: dict[str, dict[str, Any]], self_ns: str = HOST_NS['pid']) -> None:
        self.procs = procs
        self.self_ns = self_ns
        self.self_mountinfo = table(ROOT_ROW, PROC_ROW)
        self.errors: dict[tuple[str, str], OSError] = {}
        self.vanish: set[str] = set()
        self.listing_fails = False
        self.hidden: set[str] = set()

    def _entry(self, node: str) -> dict[str, Any]:
        pid, _, rest = node.partition('/task/')
        entry = self.procs[pid]
        if rest and rest in entry['tasks']:
            return {**entry, **entry['tasks'][rest]}
        return entry

    def _check(self, node: str, what: str) -> None:
        if (node, what) in self.errors:
            if node.partition('/task/')[0] in self.vanish:
                self.hidden.add(node.partition('/task/')[0])
            raise self.errors[(node, what)]

    def pids(self) -> list[str]:
        if self.listing_fails:
            raise rt._sanitised()
        return [p for p in self.procs if p not in self.hidden]

    def tasks(self, pid: str) -> list[str]:
        self._check(pid, 'task')
        names = list(self.procs[pid]['tasks']) or [pid]
        return [f'{pid}/task/{t}' for t in names]

    def read(self, node: str, name: str) -> bytes:
        if node == 'self' and name == 'mountinfo':
            return self.self_mountinfo
        self._check(node, name)
        value: bytes = self._entry(node)[name]
        return value

    def readlink(self, node: str, name: str) -> str:
        if node == 'self' and name == 'ns/pid':
            return self.self_ns
        self._check(node, name)
        kind, _, rest = name.partition('/')
        if kind == 'ns':
            value: str = self._entry(node)['ns'][rest]
            return value
        target = self._entry(node)['fd'][rest]
        return target if isinstance(target, str) else 'anon_inode:[x]'

    def listdir(self, node: str, sub: str) -> list[str]:
        self._check(node, sub)
        return list(self._entry(node)[sub])

    def stat_entry(self, node: str, sub: str, name: str) -> os.stat_result:
        self._check(node, f'{sub}/{name}')
        value = self._entry(node)[sub][name]
        if isinstance(value, os.stat_result):
            return value
        raise rt._sanitised()

    def lstat_under_root(self, pid: str, path: str) -> os.stat_result:
        self._check(pid, f'root{path}')
        view = self.procs[pid]['root_view']
        if path not in view:
            raise rt._sanitised()
        return fake_stat(view[path])

    def root_is_ns_root(self, node: str) -> bool:
        self._check(node, 'root')
        return not self._entry(node)['chrooted']

    def listdir_under_root(self, pid: str, path: str) -> list[str]:
        view = self.procs[pid]['root_view']
        prefix = path.rstrip('/') + '/'
        return sorted({p[len(prefix):].split('/')[0] for p in view if p.startswith(prefix) and p != path})


class FakeDocker:
    def __init__(self, info: Any = None, present: bool | None = False) -> None:
        self.info = info if info is not None else {
            'Id': CID, 'State': {'Pid': 4242, 'Running': True}, 'Mounts': []}
        self._present = present
        self.verbs: list[str] = []

    def inspect(self, container: str) -> Mapping[str, Any]:
        self.verbs.append('inspect')
        if isinstance(self.info, Exception):
            raise self.info
        info: Mapping[str, Any] = self.info
        return info

    def present(self, container_id: str) -> bool | None:
        self.verbs.append('ps')
        return self._present


def container_proc(**overrides: Any) -> FakeProc:
    entry = proc_entry('4242', cgroup=CGROUP, ns=CONTAINER_NS, fd={'0': 'pipe:[1]', '1': 'pipe:[2]'})
    entry.update(overrides)
    return FakeProc({'1': proc_entry('1'), '4242': entry})


def captured(generation: object, docker: FakeDocker | None = None,
             proc: FakeProc | None = None) -> rt.LaunchIdentity:
    return rt.capture_launch_identity('skillc-attempt', generation=generation,
                                      docker=docker or FakeDocker(), proc=proc or container_proc())


def after_teardown() -> FakeProc:
    """The container gone: only host processes remain."""
    return FakeProc({'1': proc_entry('1'), '77': proc_entry('77')})


# ------------------------------------------------------------- procfs view


def test_procfs_view_is_checked() -> None:
    assert rt.procfs_ok(after_teardown())
    other_ns = after_teardown()
    other_ns.self_ns = 'pid:[99999]'
    assert not rt.procfs_ok(other_ns)
    hidden = after_teardown()
    hidden.self_mountinfo = table(ROOT_ROW, '2 1 0:5 / /proc rw - proc proc rw,hidepid=invisible')
    assert not rt.procfs_ok(hidden)
    empty = FakeProc({})
    assert not rt.procfs_ok(empty)


# ---------------------------------------------------------------- capture


def test_capture_is_usable_and_issues_only_read_verbs() -> None:
    docker = FakeDocker()
    ident = captured(object(), docker=docker)
    assert ident.usable and set(docker.verbs) == {'inspect'}


@pytest.mark.parametrize('case', ['inspect-error', 'bad-id', 'pid-zero', 'not-running', 'cgroup-unreadable',
                                  'ns-unreadable', 'ns-malformed', 'zombie', 'bad-mounts',
                                  'unknown-mount-type', 'relative-destination'])
def test_capture_failure_is_unusable(case: str) -> None:
    docker = FakeDocker()
    proc = container_proc()
    info = dict(docker.info)
    if case == 'inspect-error':
        docker.info = rt._sanitised()
    elif case == 'bad-id':
        docker.info = {**info, 'Id': 'short'}
    elif case == 'pid-zero':
        docker.info = {**info, 'State': {'Pid': 0, 'Running': True}}
    elif case == 'not-running':
        docker.info = {**info, 'State': {'Pid': 4242, 'Running': False}}
    elif case == 'cgroup-unreadable':
        proc.errors[('4242', 'cgroup')] = rt._sanitised()
    elif case == 'ns-unreadable':
        proc.errors[('4242', 'ns/net')] = rt._sanitised()
    elif case == 'ns-malformed':
        proc.procs['4242']['ns']['net'] = ''
    elif case == 'zombie':
        proc.procs['4242']['stat'] = stat_line('4242', state='Z')
    elif case == 'bad-mounts':
        docker.info = {**info, 'Mounts': {}}
    elif case == 'unknown-mount-type':
        docker.info = {**info, 'Mounts': [{'Type': '', 'Source': '/x', 'Destination': '/y'}]}
    elif case == 'relative-destination':
        docker.info = {**info, 'Mounts': [{'Type': 'bind', 'Source': '/x', 'Destination': 'y'}]}
    assert not captured(object(), docker=docker, proc=proc).usable


def test_pid_reused_before_the_first_read_is_unusable() -> None:
    # Docker says pid 4242, but that pid is now another host process: its
    # cgroup does not name the container id.
    proc = FakeProc({'1': proc_entry('1'), '4242': proc_entry('4242', ns=CONTAINER_NS)})
    assert not captured(object(), proc=proc).usable


def test_pid_from_another_daemon_host_is_unusable() -> None:
    # A remote daemon's pid that happens to exist locally: same story.
    proc = FakeProc({'1': proc_entry('1'), '4242': proc_entry('4242', cgroup='/docker/' + 'b' * 64)})
    assert not captured(object(), proc=proc).usable


def test_cgroup_that_merely_contains_the_id_is_unusable() -> None:
    proc = FakeProc({'1': proc_entry('1'), '4242': proc_entry('4242', cgroup=f'/user/{CID}-decoy/x')})
    assert not captured(object(), proc=proc).usable


@pytest.mark.parametrize('line', ['4:cpu,,memory:/x', '4::/x', '0:cpu:/x', 'x:cpu:/x', '4:cpu:x'])
def test_malformed_cgroup_record_is_unusable(line: str) -> None:
    proc = container_proc()
    proc.procs['4242']['cgroup'] = f'{line}\n0::{CGROUP}\n'.encode()
    assert not captured(object(), proc=proc).usable


def test_capture_detects_pid_reuse_or_container_change_during_reads() -> None:
    proc = container_proc()
    calls: list[str] = []
    real = proc.read

    def changing(node: str, name: str) -> bytes:
        calls.append(name)
        if name == 'stat' and node == '4242' and calls.count('stat') > 1:
            return stat_line('4242', start='99999')
        return real(node, name)

    proc.read = changing  # type: ignore[method-assign]
    assert not captured(object(), proc=proc).usable

    class Flipping(FakeDocker):
        def inspect(self, container: str) -> Mapping[str, Any]:
            first = super().inspect(container)
            if self.verbs.count('inspect') > 1:
                return {**first, 'State': {'Pid': 4343, 'Running': True}}
            return first

    assert not captured(object(), docker=Flipping()).usable


def test_bind_sockets_are_counted_at_the_destination_not_the_source() -> None:
    # The host source was replaced by an empty directory, but the container's
    # view of the destination still holds a socket.
    docker = FakeDocker()
    docker.info = {**docker.info, 'Mounts': [
        {'Type': 'bind', 'Source': '/host/replaced-empty', 'Destination': '/work/run'}]}
    proc = container_proc(root_view={'/': DIR, '/work': DIR, '/work/run': DIR, '/work/run/agent.sock': SOCK},
                          mountinfo=table(ROOT_ROW, PROC_ROW, BIND_ROW))
    ident = captured(object(), docker=docker, proc=proc)
    assert ident.usable and ident._bind_sockets == 1
    assert rt.fact_channel_isolated([ident]) == rt.ScopedObservation(SURV, rt.LAUNCH_ONLY)


@pytest.mark.parametrize('case', ['no-mount-record', 'device-mismatch', 'tree-changes', 'inode-replaced',
                                  'fd-table-changes'])
def test_bind_and_fd_observations_must_be_the_effective_stable_view(case: str) -> None:
    docker = FakeDocker()
    docker.info = {**docker.info, 'Mounts': [{'Type': 'bind', 'Source': '/x', 'Destination': '/work/run'}]}
    rows = [ROOT_ROW, PROC_ROW, BIND_ROW]
    if case == 'no-mount-record':
        rows = rows[:2]
    elif case == 'device-mismatch':
        rows = [ROOT_ROW, PROC_ROW, BIND_ROW.replace(' 0:1 ', ' 9:9 ')]
    proc = container_proc(root_view={'/': DIR, '/work': DIR, '/work/run': DIR}, mountinfo=table(*rows))
    if case == 'tree-changes':
        real = proc.listdir_under_root
        calls: list[str] = []

        def growing(pid: str, path: str) -> list[str]:
            calls.append(path)
            names = real(pid, path)
            if path == '/work/run' and calls.count('/work/run') > 1:
                proc.procs['4242']['root_view']['/work/run/late.sock'] = SOCK
                return names + ['late.sock']
            return names

        proc.listdir_under_root = growing  # type: ignore[method-assign]
    if case == 'inode-replaced':
        proc.procs['4242']['root_view']['/work/run/f'] = REG
        real_lstat = proc.lstat_under_root
        hits: list[int] = []

        def swapped(pid: str, path: str) -> os.stat_result:
            info = real_lstat(pid, path)
            if path == '/work/run/f':
                hits.append(1)
                return fake_stat(REG, ino=2 if len(hits) > 1 else 1)
            return info

        proc.lstat_under_root = swapped  # type: ignore[method-assign]
    if case == 'fd-table-changes':
        real_read = proc.readlink
        seen: list[int] = []

        def swapping(node: str, name: str) -> str:
            if name == 'fd/1':
                seen.append(1)
                return 'socket:[5]' if len(seen) > 1 else 'pipe:[2]'
            return real_read(node, name)

        proc.readlink = swapping  # type: ignore[method-assign]
    assert not captured(object(), docker=docker, proc=proc).usable


def test_bind_destination_through_a_link_is_unusable() -> None:
    docker = FakeDocker()
    docker.info = {**docker.info, 'Mounts': [{'Type': 'bind', 'Source': '/x', 'Destination': '/work/run'}]}
    proc = container_proc(root_view={'/': DIR, '/work': LNK, '/work/run': DIR})
    assert not captured(object(), docker=docker, proc=proc).usable


def test_capture_needs_a_generation() -> None:
    with pytest.raises(ra.CensusRefused):
        rt.capture_launch_identity('x', generation=None, docker=FakeDocker(), proc=container_proc())


# ---------------------------------------------------------- teardown boundary


def blind_docker_only(ident: rt.LaunchIdentity, docker: FakeDocker) -> ra.Observation:
    return NEG if docker.present(ident._id) is False else SURV


def test_empty_domain_is_confirmed_negative() -> None:
    gen = object()
    ident = captured(gen)
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=after_teardown(),
                               generation=gen) is NEG


# A5: Docker says gone, but a process is still in the container's cgroup.
def test_surviving_container_process_blocks_teardown() -> None:
    ident = captured(object())
    proc = after_teardown()
    proc.procs['88'] = proc_entry('88', cgroup=CGROUP + '/child')
    docker = FakeDocker(present=False)
    assert blind_docker_only(ident, docker) is NEG
    assert rt.confirm_teardown([ident], docker=docker, proc=proc) is SURV


def test_a_worker_task_alone_in_the_cgroup_blocks_teardown() -> None:
    ident = captured(object())
    proc = after_teardown()
    proc.procs['88'] = proc_entry('88', tasks={'88': {}, '89': {
        'cgroup': f'0::{CGROUP}\n'.encode()}})
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=proc) is SURV


def test_same_path_in_another_v1_hierarchy_is_not_a_survivor() -> None:
    proc = container_proc()
    proc.procs['4242']['cgroup'] = f'4:memory:{CGROUP}\n'.encode()
    ident = captured(object(), proc=proc)
    assert ident.usable
    after = after_teardown()
    after.procs['90'] = proc_entry('90')
    after.procs['90']['cgroup'] = f'5:cpu:{CGROUP}\n'.encode()
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=after) is NEG


def test_process_sharing_a_captured_namespace_blocks_teardown() -> None:
    ident = captured(object())
    proc = after_teardown()
    proc.procs['89'] = proc_entry('89', ns={**HOST_NS, 'net': CONTAINER_NS['net']})
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=proc) is SURV


def test_container_still_known_to_docker_blocks_teardown() -> None:
    ident = captured(object())
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=True), proc=after_teardown()) is SURV


def test_teardown_requires_docker_to_answer_absent() -> None:
    ident = captured(object())
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=None), proc=after_teardown()) is FAIL

    class Raising(FakeDocker):
        def present(self, container_id: str) -> bool | None:
            raise RuntimeError('reader broke')

    assert rt.confirm_teardown([ident], docker=Raising(), proc=after_teardown()) is FAIL


# A6: a clean fd census cannot rescue a domain that is not empty. The two are
# independent observations here; their composition is A-3's (spec, A-2).
def test_nonempty_domain_is_a_survivor_whatever_the_fd_census(tmp_path: Path) -> None:
    ident = captured(object())
    proc = after_teardown()
    proc.procs['90'] = proc_entry('90', cgroup=CGROUP)
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=proc) is SURV


# A7: an unreadable read whose pid is still listed is never absence.
@pytest.mark.parametrize('what', ['stat', 'cgroup', 'ns/mnt'])
def test_failed_proc_read_is_never_absence(what: str) -> None:
    ident = captured(object())
    proc = after_teardown()
    proc.errors[('77/task/77', what)] = rt._sanitised()
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=proc) is FAIL


def test_vanished_pid_is_skipped_only_when_relisting_omits_it() -> None:
    ident = captured(object())
    proc = after_teardown()
    proc.errors[('77/task/77', 'cgroup')] = rt._sanitised()
    proc.vanish.add('77')
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=proc) is NEG


@pytest.mark.parametrize('case', ['listing-fails', 'listing-empty', 'tasks-unreadable'])
def test_failed_or_empty_population_is_failed(case: str) -> None:
    ident = captured(object())
    proc = after_teardown()
    if case == 'listing-fails':
        proc.listing_fails = True
    elif case == 'listing-empty':
        proc.procs.clear()
    else:
        proc.errors[('77', 'task')] = rt._sanitised()
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=proc) is FAIL


class EqualToEverything:
    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = None  # type: ignore[assignment]  # Unhashable on purpose.


@pytest.mark.parametrize('case', ['empty', 'unusable', 'mixed-generations', 'wrong-generation',
                                  'equal-but-distinct'])
def test_teardown_refuses_unusable_identity_sets(case: str) -> None:
    gen: object = EqualToEverything() if case == 'equal-but-distinct' else object()
    good = captured(gen)
    other: object | None = None
    if case == 'empty':
        idents: list[rt.LaunchIdentity] = []
    elif case == 'unusable':
        idents = [good, captured(gen, docker=FakeDocker(info=rt._sanitised()))]
    elif case in ('mixed-generations', 'equal-but-distinct'):
        idents = [good, captured(EqualToEverything() if case == 'equal-but-distinct' else object())]
    else:
        idents = [good]
        other = object()
    assert rt.confirm_teardown(idents, docker=FakeDocker(present=False), proc=after_teardown(),
                               generation=other) is FAIL


# ------------------------------------------------------------------ fact 2


@pytest.fixture
def held_tree(tmp_path: Path) -> Iterator[tuple[Path, ra.Census]]:
    root = tmp_path.resolve() / 'removed-root'
    root.mkdir()
    (root / 'secret').write_bytes(b'\0' * 4096)
    census = ra.take_census(root, generation=object(), max_entries=8)
    assert census.complete
    yield root, census
    census.close()


def test_every_census_open_requests_close_on_exec(tmp_path: Path) -> None:
    root = tmp_path.resolve() / 'declared' / 'removed-root'
    root.mkdir(parents=True)
    gen = object()
    flags_seen: list[int] = []

    def recording(name: str, flags: int, *args: Any, **kwargs: Any) -> int:
        flags_seen.append(flags)
        return os.open(name, flags, *args, **kwargs)

    m0 = ra.record_mountpoint(root, generation=gen, opener=recording)
    assert m0 is not None
    (root / 'd').mkdir()
    (root / 'd' / 'f').write_bytes(b'x')
    with m0, ra.take_census(root, generation=gen, max_entries=8, opener=recording) as census:
        assert census.complete
        for item in [*census._ancestors, *census._entries]:
            assert fcntl.fcntl(item.fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
        os.unlink(root / 'd' / 'f')
        os.rmdir(root / 'd')
        census.release_entries()
        assert ra.fact_reresolved(census, m0, opener=recording).observation is NEG
    assert flags_seen and all(f & os.O_CLOEXEC for f in flags_seen)


#: The real procfs precondition is root in the initial PID namespace (spec,
#: A-2): as another user, reading /proc/1/ns/pid is denied and every fact
#: correctly refuses. Real-kernel fact tests therefore run as root only (root
#: CI and the VM's root probes); the fake-reader twins below run everywhere.
needs_root = pytest.mark.skipif(os.geteuid() != 0, reason='real procfs facts need root (A-2 precondition 1)')


def test_real_procfs_precondition_fails_closed_without_root() -> None:
    reader = rt.RealProc()
    if os.geteuid() == 0:
        assert rt.procfs_ok(reader)
    else:
        assert not rt.procfs_ok(reader)  # Refused, never a partial clean view.


class ScopedProc(rt.RealProc):
    """The REAL /proc, limited to the named pids that still exist."""

    def __init__(self, pids: list[int]) -> None:
        super().__init__()
        self._only = {str(p) for p in pids}

    def pids(self) -> list[str]:
        return [p for p in super().pids() if p in self._only]


def kernel_grants_map_files(pid: int) -> bool:
    """Production stats EVERY mapping, so the gate does too."""
    try:
        names = os.listdir(f'/proc/{pid}/map_files')
        for name in names:
            os.stat(f'/proc/{pid}/map_files/{name}')
    except OSError:
        return False
    return bool(names)


def wait_ready(path: Path) -> None:
    for _ in range(100):
        if path.exists():
            return
        time.sleep(0.05)  # timing: cadence - polls for the holder's ready file; 100 polls then AssertionError bound the wait
    raise AssertionError('holder not ready')


@needs_root
def test_real_fd_holder_is_seen(held_tree: tuple[Path, ra.Census]) -> None:
    root, census = held_tree
    fd = os.open(root / 'secret', os.O_RDONLY)
    os.set_inheritable(fd, True)
    child = subprocess.Popen(['sleep', '30'], pass_fds=(fd,))
    os.close(fd)
    try:
        if not kernel_grants_map_files(child.pid):
            pytest.skip('this kernel/runner denies map_files; the VM probe P2 qualifies it')
        scope = ScopedProc([child.pid, os.getpid()])
        assert rt.fact_no_holder(census, proc=scope) is SURV
    finally:
        child.kill()
        child.wait()
    assert rt.fact_no_holder(census, proc=ScopedProc([os.getpid()])) is NEG


MAP_HOLDER = '''
import ctypes, os, sys, time
libc = ctypes.CDLL(None, use_errno=True)
libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
fd = os.open(sys.argv[1], os.O_RDONLY)
addr = libc.mmap(None, 4096, 1, 1, fd, 0)
if addr is None or addr == ctypes.c_void_p(-1).value:
    sys.exit(3)
os.close(fd)
open(sys.argv[2], "w").close()
time.sleep(30)
'''


@needs_root
def test_real_mapping_only_holder_is_seen(held_tree: tuple[Path, ra.Census], tmp_path: Path) -> None:
    root, census = held_tree
    ready = tmp_path.resolve() / 'ready'
    child = subprocess.Popen([sys.executable, '-I', '-c', MAP_HOLDER, str(root / 'secret'), str(ready)])
    try:
        wait_ready(ready)
        if not kernel_grants_map_files(child.pid):
            pytest.skip('this kernel/runner denies map_files; the VM probe P2 qualifies it')
        assert not any(os.path.realpath(f'/proc/{child.pid}/fd/{n}') == str(root / 'secret')
                       for n in os.listdir(f'/proc/{child.pid}/fd'))
        assert rt.fact_no_holder(census, proc=ScopedProc([child.pid, os.getpid()])) is SURV
    finally:
        child.kill()
        child.wait()


def blind_counts_self(census: ra.Census) -> ra.Observation:
    """Fact 2 without self-exclusion: the controller's own census fds count."""
    targets = {i.identity for i in census._entries}
    for name in os.listdir('/proc/self/fd'):
        try:
            if ra.Identity(os.stat(f'/proc/self/fd/{name}')) in targets:
                return SURV
        except OSError:
            continue
    return NEG


def test_controller_pid_is_excluded_but_its_children_are_not(held_tree: tuple[Path, ra.Census]) -> None:
    # The fake reader twin of the self-exclusion rule, so it runs as any user.
    _, census = held_tree
    assert census._root is not None
    root_stat = os.fstat(census._root.fd)
    me = str(os.getpid())
    own = FakeProc({'1': proc_entry('1'), me: proc_entry(me, fd={'5': root_stat})})
    assert rt.fact_no_holder(census, proc=own) is NEG
    child = FakeProc({'1': proc_entry('1'), me: proc_entry(me, fd={'5': root_stat}),
                      '99991': proc_entry('99991', fd={'5': root_stat})})
    assert rt.fact_no_holder(census, proc=child) is SURV


@needs_root
def test_controller_own_census_fds_are_not_holders(held_tree: tuple[Path, ra.Census]) -> None:
    _, census = held_tree
    assert blind_counts_self(census) is SURV
    assert rt.fact_no_holder(census, proc=ScopedProc([os.getpid()])) is NEG


def fake_holder(census: ra.Census, where: str) -> FakeProc:
    """A fake process 91 holding the census root's object in its fd table
    ('process') or only in a worker task's own fd table ('worker')."""
    root_stat = os.fstat(census._root.fd) if census._root else None
    assert root_stat is not None
    if where == 'process':
        return FakeProc({'1': proc_entry('1'), '91': proc_entry('91', fd={'5': root_stat})})
    return FakeProc({'1': proc_entry('1'), '91': proc_entry('91', tasks={
        '91': {}, '92': {'fd': {'5': root_stat}}})})


def test_mapping_only_holder_is_seen_with_the_fake_reader(held_tree: tuple[Path, ra.Census]) -> None:
    # The unconditional mapping positive: runs where the real probe is skipped.
    root, census = held_tree
    mapped = os.stat(root / 'secret')
    proc = FakeProc({'1': proc_entry('1'), '96': proc_entry('96', map_files={'7f00-7f01': mapped})})
    assert rt.fact_no_holder(census, proc=proc) is SURV


def test_fd_holder_of_a_census_file_is_seen_with_the_fake_reader(
        held_tree: tuple[Path, ra.Census]) -> None:
    # The unconditional regular-file fd positive: the other fake fd holders
    # hold the census root (a directory), and the real fd-holder test runs only
    # where map_files is readable, so without this a scan that skipped
    # regular-file descriptors would pass everywhere else.
    root, census = held_tree
    held = os.stat(root / 'secret')
    proc = FakeProc({'1': proc_entry('1'), '97': proc_entry('97', fd={'5': held})})
    assert rt.fact_no_holder(census, proc=proc) is SURV


@pytest.mark.parametrize('where', ['process', 'worker'])
def test_holder_of_the_root_is_seen_even_in_a_worker_task(held_tree: tuple[Path, ra.Census],
                                                           where: str) -> None:
    _, census = held_tree
    assert rt.fact_no_holder(census, proc=fake_holder(census, where)) is SURV


def test_task_replaced_during_the_census_is_failed(held_tree: tuple[Path, ra.Census]) -> None:
    _, census = held_tree
    proc = FakeProc({'1': proc_entry('1'), '95': proc_entry('95')})
    reads: list[int] = []
    real = proc.read

    def replacing(node: str, name: str) -> bytes:
        if node == '95/task/95' and name == 'stat':
            reads.append(1)
            if len(reads) == 2:
                return stat_line('95', start='77777')
        return real(node, name)

    proc.read = replacing  # type: ignore[method-assign]
    assert rt.fact_no_holder(census, proc=proc) is FAIL


@pytest.mark.parametrize('case', ['listing', 'entry'])
def test_unreadable_holder_census_is_failed(held_tree: tuple[Path, ra.Census], case: str) -> None:
    _, census = held_tree
    proc = FakeProc({'1': proc_entry('1'), '92': proc_entry('92', fd={'3': 'x'})})
    proc.errors[('92/task/92', 'fd' if case == 'listing' else 'fd/3')] = rt._sanitised()
    assert rt.fact_no_holder(census, proc=proc) is FAIL


def test_fact2_requires_held_entries_and_a_population(held_tree: tuple[Path, ra.Census]) -> None:
    _, census = held_tree
    assert rt.fact_no_holder(census, proc=FakeProc({})) is FAIL
    census.release_entries()
    assert rt.fact_no_holder(census) is FAIL


# ----------------------------------------------------------------- fact 2b


def test_isolated_capture_is_negative_and_launch_scoped() -> None:
    assert rt.fact_channel_isolated([captured(object())]) == rt.ScopedObservation(NEG, rt.LAUNCH_ONLY)


@pytest.mark.parametrize('case', ['shared-net', 'shared-ipc', 'init-socket-fd'])
def test_channel_isolation_breach_is_a_survivor(case: str) -> None:
    proc = container_proc()
    if case == 'shared-net':
        proc.procs['4242']['ns']['net'] = HOST_NS['net']
    elif case == 'shared-ipc':
        proc.procs['4242']['ns']['ipc'] = HOST_NS['ipc']
    else:
        proc.procs['4242']['fd']['3'] = 'socket:[777]'
    assert rt.fact_channel_isolated([captured(object(), proc=proc)]).observation is SURV


def test_channel_isolation_unknown_is_failed_and_still_scoped() -> None:
    result = rt.fact_channel_isolated([captured(object(), docker=FakeDocker(info=rt._sanitised()))])
    assert result == rt.ScopedObservation(FAIL, rt.LAUNCH_ONLY)
    assert rt.fact_channel_isolated([]) == rt.ScopedObservation(FAIL, rt.LAUNCH_ONLY)


#: Every Contract A input A-3 composes, each at its passing value except the one
#: under test. A-3 must expose `removed_surface_verdict(**SUFFICIENT)` (spec,
#: A-2) or adapt these guards to its real entry point; never delete them.
SUFFICIENT: dict[str, Any] = {
    'census_complete': True, 'unlinked': NEG, 'reresolved': NEG, 'teardown': NEG, 'no_holder': NEG,
    'superblock_gone': NEG, 'tmpfs': True, 'isolation': rt.ScopedObservation(NEG, 'lifetime'),
}


def a3_compose() -> Any:
    if importlib.util.find_spec('skillc.run_window_compose') is None:
        pytest.skip('A-3 composition not implemented yet')
    return importlib.import_module('skillc.run_window_compose')


def test_a3_composition_reaches_absent_with_sufficient_evidence() -> None:
    assert a3_compose().removed_surface_verdict(**SUFFICIENT) == 'ABSENT'


@pytest.mark.parametrize('override', [
    {'isolation': rt.ScopedObservation(NEG, rt.LAUNCH_ONLY)},  # launch-only 2b never suffices
    {'teardown': SURV},  # a non-empty domain vetoes, whatever fact 2 says
    {'no_holder': SURV},  # a holder vetoes
], ids=['launch-only-isolation', 'domain-veto', 'holder-veto'])
def test_a3_composition_refuses_absent_when_one_input_fails(override: dict[str, Any]) -> None:
    assert a3_compose().removed_surface_verdict(**{**SUFFICIENT, **override}) != 'ABSENT'


# ------------------------------------------------------------------ fact 3


def majmin_of(root: Path) -> str:
    dev = os.stat(root).st_dev
    return f'{os.major(dev)}:{os.minor(dev)}'


@pytest.fixture
def released(held_tree: tuple[Path, ra.Census]) -> tuple[Path, ra.Census]:
    root, census = held_tree
    census.release_entries()
    return root, census


def test_superblock_in_no_table_is_negative(released: tuple[Path, ra.Census]) -> None:
    root, census = released
    # The fake tables must not carry the real census device, or this case is
    # testing a collision rather than absence.
    assert majmin_of(root) not in (ROOT_ROW.split()[2], PROC_ROW.split()[2])
    assert rt.fact_superblock_gone(census, proc=after_teardown()) is NEG


def blind_mount_id_only(data: bytes, mount_id: str) -> ra.Observation:
    return SURV if any(line.split()[0] == mount_id for line in data.decode().splitlines() if line) else NEG


# A10: the original mount id is gone, but a bind alias of the same superblock remains.
def test_superblock_alias_is_listed(released: tuple[Path, ra.Census]) -> None:
    root, census = released
    alias = table(ROOT_ROW, PROC_ROW, f'57 1 {majmin_of(root)} / /elsewhere rw - tmpfs tmpfs rw')
    proc = FakeProc({'1': proc_entry('1', mountinfo=alias)})
    assert blind_mount_id_only(alias, '42') is NEG  # The original mount id 42 is gone.
    assert rt.fact_superblock_gone(census, proc=proc) is SURV


def test_superblock_listed_only_in_another_namespace_is_seen(released: tuple[Path, ra.Census]) -> None:
    root, census = released
    proc = after_teardown()
    proc.procs['93'] = proc_entry('93', ns={**HOST_NS, 'mnt': 'mnt:[30003]'}, mountinfo=table(
        ROOT_ROW, f'60 1 {majmin_of(root)} / /in-container rw - tmpfs t rw'))
    assert rt.fact_superblock_gone(census, proc=proc) is SURV


@pytest.mark.parametrize('record', ['70 1 8:1 /jail / rw - ext4 /dev/sda1 rw',
                                    '71 1 9:2 / / rw - ext4 /dev/sdc1 rw'])
def test_namespace_seen_only_through_a_chrooted_task_is_failed(released: tuple[Path, ra.Census],
                                                               record: str) -> None:
    # The only task in mount namespace 30004 is chrooted - into a directory,
    # or onto the ROOT of a nested filesystem, whose record reads '/ /' just
    # like a namespace root. Its table omits mounts outside the chroot.
    _, census = released
    proc = after_teardown()
    proc.procs['94'] = proc_entry('94', ns={**HOST_NS, 'mnt': 'mnt:[30004]'}, mountinfo=table(record),
                                  chrooted=True)
    assert rt.fact_superblock_gone(census, proc=proc) is FAIL


CHROOTED = '''
import os, sys, time
try:
    os.chroot(sys.argv[1])
except PermissionError:
    open(sys.argv[1] + '/denied', 'w').close()
    sys.exit(0)
os.chdir('/')
open('/ready', 'w').close()
time.sleep(30)
'''


@pytest.mark.skipif(os.geteuid() != 0, reason='chroot needs root; root CI runs it')
def test_real_predicate_tells_a_chrooted_task_from_a_namespace_root(tmp_path: Path) -> None:
    jail = tmp_path.resolve() / 'jail'
    jail.mkdir()
    child = subprocess.Popen([sys.executable, '-I', '-S', '-c', CHROOTED, str(jail)])
    try:
        for _ in range(100):
            if (jail / 'ready').exists() or (jail / 'denied').exists():
                break
            time.sleep(0.05)  # timing: cadence - polls for the child's ready/denied file; 100 polls then wait_ready bound it
        if (jail / 'denied').exists():
            pytest.skip('this root runner lacks CAP_SYS_CHROOT')
        wait_ready(jail / 'ready')
        reader = rt.RealProc()
        assert reader.root_is_ns_root(f'{os.getpid()}/task/{os.getpid()}')
        assert not reader.root_is_ns_root(f'{child.pid}/task/{child.pid}')
    finally:
        child.kill()
        child.wait()


@pytest.mark.parametrize('bad', ['garbage', '1 0 8:1 / / rw tmpfs t rw', 'x y 8:1 / / rw - tmpfs t rw',
                                 '1 0 8:1 / / rw - tmpfs t', '1 0 8:1 / / rw - tmpfs t rw extra',
                                 '1 0 8:1 / /  - tmpfs t rw', 'NO-NEWLINE', ''])
def test_unusable_mount_table_is_failed(released: tuple[Path, ra.Census], bad: str) -> None:
    _, census = released
    proc = after_teardown()
    proc.procs['77']['mountinfo'] = (ROOT_ROW.encode() if bad == 'NO-NEWLINE' else bad.encode() + b'\n')
    assert rt.fact_superblock_gone(census, proc=proc) is FAIL


def test_unreadable_mount_table_is_failed(released: tuple[Path, ra.Census]) -> None:
    _, census = released
    proc = after_teardown()
    proc.errors[('77/task/77', 'mountinfo')] = rt._sanitised()
    assert rt.fact_superblock_gone(census, proc=proc) is FAIL


def test_fact3_requires_released_entries(held_tree: tuple[Path, ra.Census]) -> None:
    _, census = held_tree
    assert rt.fact_superblock_gone(census, proc=after_teardown()) is FAIL


@needs_root
def test_real_mount_table_lists_a_live_filesystem(released: tuple[Path, ra.Census]) -> None:
    # The tree lives on a mounted filesystem, so the real reader must say
    # SURVIVOR: it is not blind.
    _, census = released
    assert rt.fact_superblock_gone(census, proc=ScopedProc([os.getpid()])) is SURV


# ------------------------------------------------------- reader sanitising


def test_real_proc_errors_carry_no_path_or_context(tmp_path: Path) -> None:
    reader = rt.RealProc(str(tmp_path.resolve() / 'marker-proc-root'))
    for call in (reader.pids, lambda: reader.read('9', 'marker-name'), lambda: reader.readlink('9', 'x'),
                 lambda: reader.listdir('9', 'fd'), lambda: reader.stat_entry('9', 'fd', 'marker-name')):
        with pytest.raises(OSError) as caught:
            call()
        exc = caught.value
        assert exc.filename is None and exc.__context__ is None and 'marker' not in str(exc)


def test_real_docker_reader_is_sanitised_and_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = iter(['not json marker-payload', 'garbage-line\n', '  \n', ''])

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout=next(outputs), stderr='')

    monkeypatch.setattr(rt.subprocess, 'run', fake_run)
    reader = rt.RealDocker(['docker'], env={})
    with pytest.raises(OSError) as caught:
        reader.inspect('marker-container')
    assert 'marker' not in str(caught.value) and caught.value.__context__ is None
    assert reader.present(CID) is None  # Malformed nonempty output is no answer.
    assert reader.present(CID) is None  # Whitespace is not an empty answer.
    assert reader.present(CID) is False

    def undecodable(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise UnicodeDecodeError('utf-8', b'marker-bytes\xff', 12, 13, 'invalid')

    monkeypatch.setattr(rt.subprocess, 'run', undecodable)
    with pytest.raises(OSError) as caught:
        reader.inspect('marker-container')
    assert 'marker' not in str(caught.value) and caught.value.__context__ is None

    def timing_out(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, 30)

    monkeypatch.setattr(rt.subprocess, 'run', timing_out)
    with pytest.raises(OSError) as caught:
        reader.inspect('marker-container')
    assert 'marker' not in str(caught.value) and caught.value.__context__ is None
