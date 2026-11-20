"""Contract A part 2 (#797 A-2): teardown boundary, facts 2, 2b and 3.

These qualify NEW instruments; none claims a red run on the parent. Fake
`/proc` and Docker readers drive the boundary logic (A5, A6, A7, A10, A21),
so every case runs as root or not. Fact 2 also runs against REAL child
processes: one holding a descriptor, and one holding only a mapping whose
descriptor it closed. Each case a blind checker could pass is paired with
that checker (`blind_*`), and the blind one must give a different verdict.
"""
from __future__ import annotations

import errno
import fcntl
import os
import socket
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
HOST_NS = {k: f'{k}:[1000]' for k in rt.NAMESPACES}
CONTAINER_NS = {k: f'{k}:[2000]' for k in rt.NAMESPACES}
CGROUP = '/system.slice/docker-' + CID + '.scope'


def stat_line(pid: str, start: str = '12345', state: str = 'S', comm: str = 'sleep') -> bytes:
    return f'{pid} ({comm}) {state} '.encode() + ' '.join(['0'] * 18 + [start]).encode()


def proc_entry(pid: str, *, cgroup: str = '/user.slice', ns: Mapping[str, str] = HOST_NS,
               start: str = '12345', mountinfo: bytes = b'', fd: dict[str, Any] | None = None,
               map_files: dict[str, Any] | None = None) -> dict[str, Any]:
    return {'stat': stat_line(pid, start), 'cgroup': f'0::{cgroup}\n'.encode('utf-8', 'surrogateescape'),
            'ns': dict(ns),
            'mountinfo': mountinfo or b'1 0 8:1 / / rw - ext4 /dev/sda1 rw\n',
            'fd': fd or {}, 'map_files': map_files or {}}


class FakeProc:
    """A /proc tree from dicts. `errors[(pid, what)]` raises OSError there;
    `vanish` makes a pid disappear from later listings once it is read."""

    def __init__(self, procs: dict[str, dict[str, Any]]) -> None:
        self.procs = procs
        self.errors: dict[tuple[str, str], OSError] = {}
        self.vanish: set[str] = set()
        self.listing_fails = False
        self.hidden: set[str] = set()

    def pids(self) -> list[str]:
        if self.listing_fails:
            raise OSError(errno.EIO, 'io')
        return [p for p in self.procs if p not in self.hidden]

    def _check(self, pid: str, what: str) -> None:
        if (pid, what) in self.errors:
            if pid in self.vanish:
                self.hidden.add(pid)
            raise self.errors[(pid, what)]

    def read(self, pid: str, name: str) -> bytes:
        self._check(pid, name)
        value: bytes = self.procs[pid][name]
        return value

    def readlink(self, pid: str, name: str) -> str:
        self._check(pid, name)
        kind, _, rest = name.partition('/')
        if kind == 'ns':
            value: str = self.procs[pid]['ns'][rest]
            return value
        target = self.procs[pid]['fd'][rest]
        return target if isinstance(target, str) else 'anon_inode:[x]'

    def listdir(self, pid: str, sub: str) -> list[str]:
        self._check(pid, sub)
        return list(self.procs[pid][sub])

    def stat_entry(self, pid: str, sub: str, name: str) -> os.stat_result:
        self._check(pid, f'{sub}/{name}')
        value = self.procs[pid][sub][name]
        if isinstance(value, os.stat_result):
            return value
        raise OSError(errno.ENOENT, 'not a file')


class ScopedProc(rt.RealProc):
    """The REAL /proc, limited to the named pids that still exist. Kernel
    reads are real; the population is bounded so an unprivileged run is not
    failed by other users' processes (the full census is what root CI and the
    VM run)."""

    def __init__(self, pids: list[int]) -> None:
        super().__init__()
        self._only = {str(p) for p in pids}

    def pids(self) -> list[str]:
        return [p for p in super().pids() if p in self._only]


class FakeDocker:
    def __init__(self, info: Mapping[str, Any] | None = None, present: bool | None = False) -> None:
        self.info = info if info is not None else {
            'Id': CID, 'State': {'Pid': 4242, 'Running': True}, 'Mounts': []}
        self._present = present
        self.verbs: list[str] = []

    def inspect(self, container: str) -> Mapping[str, Any]:
        self.verbs.append('inspect')
        if isinstance(self.info, Exception):
            raise self.info
        return self.info

    def present(self, container_id: str) -> bool | None:
        self.verbs.append('ps')
        return self._present


def container_proc() -> FakeProc:
    return FakeProc({'1': proc_entry('1'), '4242': proc_entry('4242', cgroup=CGROUP, ns=CONTAINER_NS,
                                                              fd={'0': 'pipe:[1]', '1': 'pipe:[2]'})})


def captured(generation: object, docker: FakeDocker | None = None,
             proc: FakeProc | None = None) -> rt.LaunchIdentity:
    return rt.capture_launch_identity('skillc-attempt', generation=generation,
                                      docker=docker or FakeDocker(), proc=proc or container_proc())


def after_teardown() -> FakeProc:
    """The container gone: only host processes remain."""
    return FakeProc({'1': proc_entry('1'), '77': proc_entry('77')})


# ---------------------------------------------------------------- capture


def test_capture_is_usable_and_issues_only_read_verbs() -> None:
    docker = FakeDocker()
    ident = captured(object(), docker=docker)
    assert ident.usable and set(docker.verbs) == {'inspect'}


@pytest.mark.parametrize('case', ['inspect-error', 'bad-id', 'pid-zero', 'not-running', 'cgroup-unreadable',
                                  'ns-unreadable', 'zombie', 'bad-mounts', 'unknown-mount-type'])
def test_capture_failure_is_unusable(case: str) -> None:
    docker = FakeDocker()
    proc = container_proc()
    info = dict(docker.info)
    if case == 'inspect-error':
        docker.info = OSError(errno.EIO, 'io')  # type: ignore[assignment]
    elif case == 'bad-id':
        docker.info = {**info, 'Id': 'short'}
    elif case == 'pid-zero':
        docker.info = {**info, 'State': {'Pid': 0, 'Running': True}}
    elif case == 'not-running':
        docker.info = {**info, 'State': {'Pid': 4242, 'Running': False}}
    elif case == 'cgroup-unreadable':
        proc.errors[('4242', 'cgroup')] = OSError(errno.EACCES, 'denied')
    elif case == 'ns-unreadable':
        proc.errors[('4242', 'ns/net')] = OSError(errno.EACCES, 'denied')
    elif case == 'zombie':
        proc.procs['4242']['stat'] = stat_line('4242', state='Z')
    elif case == 'bad-mounts':
        docker.info = {**info, 'Mounts': {}}
    elif case == 'unknown-mount-type':
        docker.info = {**info, 'Mounts': [{'Type': '', 'Source': '/x', 'Destination': '/y'}]}
    assert not captured(object(), docker=docker, proc=proc).usable


def test_capture_detects_pid_reuse_while_reading() -> None:
    proc = container_proc()
    reads = []
    real_read = proc.read

    def changing(pid: str, name: str) -> bytes:
        reads.append(name)
        if name == 'stat' and pid == '4242' and reads.count('stat') > 1:
            return stat_line('4242', start='99999')
        return real_read(pid, name)

    proc.read = changing  # type: ignore[method-assign]
    assert not captured(object(), proc=proc).usable


def test_capture_counts_socket_binds_and_sockets_inside_bound_dirs(tmp_path: Path) -> None:
    tmp = tmp_path.resolve()
    (tmp / 'dir').mkdir()
    for path in (tmp / 'host.sock', tmp / 'dir' / 'inner.sock'):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(path))
        sock.close()
    docker = FakeDocker()
    docker.info = {**docker.info, 'Mounts': [
        {'Type': 'bind', 'Source': str(tmp / 'host.sock'), 'Destination': '/probe-host.sock'},
        {'Type': 'bind', 'Source': str(tmp / 'dir'), 'Destination': '/probe-dir'}]}
    ident = captured(object(), docker=docker)
    assert ident.usable and ident._bind_sockets == 2
    assert rt.fact_channel_isolated([ident]) == rt.ScopedObservation(SURV, rt.LAUNCH_ONLY)


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
    gen = object()
    ident = captured(gen)
    proc = after_teardown()
    proc.procs['88'] = proc_entry('88', cgroup=CGROUP + '/child')
    docker = FakeDocker(present=False)
    assert blind_docker_only(ident, docker) is NEG
    assert rt.confirm_teardown([ident], docker=docker, proc=proc) is SURV


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


# A6: a clean fd census cannot rescue a domain that is not empty.
def test_census_cannot_rescue_a_nonempty_domain(tmp_path: Path) -> None:
    ident = captured(object())
    proc = after_teardown()
    proc.procs['90'] = proc_entry('90', cgroup=CGROUP)
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=proc) is SURV
    root = tmp_path.resolve() / 'r'
    root.mkdir()
    (root / 'f').write_bytes(b'x')
    with ra.take_census(root, generation=object(), max_entries=8) as census:
        assert rt.fact_no_holder(census, proc=proc) is NEG  # The corroboration alone says clean.


# A7: an unreadable read whose pid is still listed is never absence.
@pytest.mark.parametrize('what', ['stat', 'cgroup', 'ns/mnt'])
def test_failed_proc_read_is_never_absence(what: str) -> None:
    ident = captured(object())
    proc = after_teardown()
    proc.errors[('77', what)] = OSError(errno.EACCES, 'denied')
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=proc) is FAIL


def test_vanished_pid_is_skipped_only_when_relisting_omits_it() -> None:
    ident = captured(object())
    proc = after_teardown()
    proc.errors[('77', 'cgroup')] = OSError(errno.ENOENT, 'gone')
    proc.vanish.add('77')
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=proc) is NEG


def test_failed_pid_listing_is_failed() -> None:
    ident = captured(object())
    proc = after_teardown()
    proc.listing_fails = True
    assert rt.confirm_teardown([ident], docker=FakeDocker(present=False), proc=proc) is FAIL


@pytest.mark.parametrize('case', ['empty', 'unusable', 'mixed-generations', 'wrong-generation'])
def test_teardown_refuses_unusable_identity_sets(case: str) -> None:
    gen = object()
    good = captured(gen)
    if case == 'empty':
        idents: list[rt.LaunchIdentity] = []
    elif case == 'unusable':
        bad = FakeDocker()
        bad.info = OSError(errno.EIO, 'io')  # type: ignore[assignment]
        idents = [good, captured(gen, docker=bad)]
    elif case == 'mixed-generations':
        idents = [good, captured(object())]
    else:
        idents = [good]
    other = object() if case == 'wrong-generation' else None
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


def test_census_descriptors_are_close_on_exec(held_tree: tuple[Path, ra.Census]) -> None:
    _, census = held_tree
    fds = [i.fd for i in census._ancestors] + [census._root.fd if census._root else -1]
    fds += [i.fd for i in census._entries]
    assert fds and all(fd >= 0 for fd in fds)
    for fd in fds:
        assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC


def wait_ready(path: Path) -> None:
    for _ in range(100):
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError('holder not ready')


def test_real_fd_holder_is_seen(held_tree: tuple[Path, ra.Census], tmp_path: Path) -> None:
    root, census = held_tree
    fd = os.open(root / 'secret', os.O_RDONLY)
    os.set_inheritable(fd, True)
    child = subprocess.Popen(['sleep', '30'], pass_fds=(fd,))
    os.close(fd)
    scope = ScopedProc([child.pid, os.getpid()])
    try:
        assert rt.fact_no_holder(census, proc=scope) is SURV
    finally:
        child.kill()
        child.wait()
    assert rt.fact_no_holder(census, proc=scope) is NEG


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


def test_real_mapping_only_holder_is_seen(held_tree: tuple[Path, ra.Census], tmp_path: Path) -> None:
    root, census = held_tree
    ready = tmp_path.resolve() / 'ready'
    child = subprocess.Popen([sys.executable, '-I', '-c', MAP_HOLDER, str(root / 'secret'), str(ready)])
    try:
        wait_ready(ready)
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


def test_controller_own_census_fds_are_not_holders(held_tree: tuple[Path, ra.Census]) -> None:
    _, census = held_tree
    assert blind_counts_self(census) is SURV
    assert rt.fact_no_holder(census, proc=ScopedProc([os.getpid()])) is NEG


@pytest.mark.skipif(os.geteuid() != 0, reason='the unbounded census reads every process; root CI runs it')
def test_full_real_census_runs_as_root(held_tree: tuple[Path, ra.Census]) -> None:
    _, census = held_tree
    assert rt.fact_no_holder(census) is NEG


def test_holder_of_the_root_alone_is_seen(held_tree: tuple[Path, ra.Census]) -> None:
    root, census = held_tree
    assert census._root is not None
    root_stat = os.stat(root)
    proc = FakeProc({'1': proc_entry('1'), '91': proc_entry('91', fd={'5': root_stat})})
    assert rt.fact_no_holder(census, proc=proc) is SURV  # e.g. a lazily detached, held tmpfs (A11)


@pytest.mark.parametrize('case', ['listing', 'entry'])
def test_unreadable_holder_census_is_failed(held_tree: tuple[Path, ra.Census], case: str) -> None:
    _, census = held_tree
    proc = FakeProc({'1': proc_entry('1'), '92': proc_entry('92', fd={'3': 'x'})})
    proc.errors[('92', 'fd' if case == 'listing' else 'fd/3')] = OSError(errno.EACCES, 'denied')
    assert rt.fact_no_holder(census, proc=proc) is FAIL


def test_fact2_requires_held_entries(held_tree: tuple[Path, ra.Census]) -> None:
    _, census = held_tree
    census.release_entries()
    assert rt.fact_no_holder(census) is FAIL


# ----------------------------------------------------------------- fact 2b


def test_isolated_capture_is_negative_and_launch_scoped() -> None:
    result = rt.fact_channel_isolated([captured(object())])
    assert result == rt.ScopedObservation(NEG, rt.LAUNCH_ONLY)


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
    bad = FakeDocker()
    bad.info = OSError(errno.EIO, 'io')  # type: ignore[assignment]
    result = rt.fact_channel_isolated([captured(object(), docker=bad)])
    assert result == rt.ScopedObservation(FAIL, rt.LAUNCH_ONLY)
    assert rt.fact_channel_isolated([]) == rt.ScopedObservation(FAIL, rt.LAUNCH_ONLY)


@pytest.mark.xfail(strict=True, reason='A-3 composition does not exist yet. When it lands this test must '
                   'pass, and then this marker must be removed: a launch-only 2b may never satisfy ABSENT '
                   'until PR-1 supplies a lifetime 2b (spec, A-2 section).')
def test_a3_composition_refuses_a_launch_only_isolation_for_absent() -> None:
    import importlib
    compose = importlib.import_module('skillc.run_window_compose')  # A-3
    verdict = compose.removed_surface_verdict(
        isolation=rt.ScopedObservation(NEG, rt.LAUNCH_ONLY))
    assert verdict != 'ABSENT'


# ------------------------------------------------------------------ fact 3


def table(*rows: str) -> bytes:
    return ('\n'.join(rows) + '\n').encode()


def majmin_of(root: Path) -> str:
    dev = os.stat(root).st_dev
    return f'{os.major(dev)}:{os.minor(dev)}'


@pytest.fixture
def released(held_tree: tuple[Path, ra.Census]) -> tuple[Path, ra.Census]:
    root, census = held_tree
    census.release_entries()
    return root, census


def test_superblock_in_no_table_is_negative(released: tuple[Path, ra.Census]) -> None:
    _, census = released
    proc = FakeProc({'1': proc_entry('1', mountinfo=table('1 0 999:999 / / rw - ext4 /dev/x rw'))})
    assert rt.fact_superblock_gone(census, proc=proc) is NEG


def blind_mount_id_only(data: bytes, mount_id: str) -> ra.Observation:
    return SURV if any(line.split()[0] == mount_id for line in data.decode().splitlines() if line) else NEG


# A10: the original mount id is gone, but a bind alias of the same superblock remains.
def test_superblock_alias_is_listed(released: tuple[Path, ra.Census]) -> None:
    root, census = released
    mm = majmin_of(root)
    alias = table('1 0 999:999 / / rw - ext4 /dev/x rw', f'57 1 {mm} / /elsewhere rw - tmpfs tmpfs rw')
    proc = FakeProc({'1': proc_entry('1', mountinfo=alias)})
    assert blind_mount_id_only(alias, '42') is NEG  # The original mount id 42 is gone.
    assert rt.fact_superblock_gone(census, proc=proc) is SURV


def test_superblock_listed_only_in_another_namespace_is_seen(released: tuple[Path, ra.Census]) -> None:
    root, census = released
    mm = majmin_of(root)
    proc = FakeProc({'1': proc_entry('1'),
                     '93': proc_entry('93', mountinfo=table(f'60 1 {mm} / /in-container rw - tmpfs t rw'))})
    assert rt.fact_superblock_gone(census, proc=proc) is SURV


@pytest.mark.parametrize('bad', ['garbage', '1 0 8:1 / / rw tmpfs t rw', 'x y 8:1 / / rw - tmpfs t rw',
                                 '1 0 8:1 / / rw - tmpfs t', ''])
def test_unusable_mount_table_is_failed(released: tuple[Path, ra.Census], bad: str) -> None:
    _, census = released
    proc = FakeProc({'1': proc_entry('1')})
    proc.procs['1']['mountinfo'] = bad.encode()
    assert rt.fact_superblock_gone(census, proc=proc) is FAIL


def test_unreadable_mount_table_is_failed(released: tuple[Path, ra.Census]) -> None:
    _, census = released
    proc = FakeProc({'1': proc_entry('1'), '94': proc_entry('94')})
    proc.errors[('94', 'mountinfo')] = OSError(errno.EACCES, 'denied')
    assert rt.fact_superblock_gone(census, proc=proc) is FAIL


def test_fact3_requires_released_entries(held_tree: tuple[Path, ra.Census]) -> None:
    _, census = held_tree
    assert rt.fact_superblock_gone(census, proc=FakeProc({'1': proc_entry('1')})) is FAIL


def test_real_mount_tables_do_not_list_a_plain_tree_as_gone(released: tuple[Path, ra.Census]) -> None:
    # The tree lives on the test filesystem, which IS mounted: fact 3 must say
    # SURVIVOR on the real tables, so the real reader is not blind.
    _, census = released
    assert rt.fact_superblock_gone(census, proc=ScopedProc([os.getpid()])) is SURV
