"""Removed-root absence evidence, part 2: teardown boundary, facts 2, 2b and 3
(#797 A-2, SECRET-PATH).

This continues docs/specs/evaluation-facility/run-window-contracts.md
section 2.2. It holds identities of the containers that held credentials (ids,
pids, cgroup paths, namespace inodes) and of the roots they wrote. It never
reads a credential's bytes.

- `capture_launch_identity` is a READ-ONLY observation, taken once per role
  or login container after `prepare()` starts it and before any dispatch. It
  binds the inspected container id to a live task in THIS host's procfs (the
  task's cgroup must name the id, and Docker must report the same pid again
  after the reads). It counts sockets at each bind's DESTINATION, as seen in
  the task's own root, rather than at the host source path, which could have
  been replaced.
- `confirm_teardown` reports whether the holder domain is empty: every
  captured container gone (Docker answered with no matching id), and no task
  left in a captured cgroup or sharing a captured PID, mount, network or IPC
  namespace.
- `fact_no_holder` (fact 2) is corroboration: a census of every surviving
  TASK's fd table (a task can own its own after unshare(CLONE_FILES)) and every
  process's mappings finds no census object or root. It runs twice and both
  passes must agree. The controller's own tasks are excluded; its census
  descriptors are O_CLOEXEC.
- `fact_channel_isolated` (fact 2b) judges the launch captures, and its
  result is scoped `launch-only`. A-3 must not treat that as sufficient.
- `fact_superblock_gone` (fact 3) reads the mount table of every task. It
  requires that every mount namespace is represented by a task whose root is
  the namespace's root (a chrooted task's table omits mounts outside its
  root), and that no table lists the census root's device.

**Preconditions, which the controller establishes and does not re-prove
here:**
- it runs as root in the initial PID namespace, with an unfiltered procfs;
  `procfs_ok` checks the visible parts and every fact refuses without it;
- the holder domain is empty, so the only processes left are the declared
  host workload. A transfer of descriptors between surviving host processes
  during a scan is outside that workload's behaviour. Fact 2's second pass
  narrows the race but cannot exclude it.

Every read is checked and every record validated. An empty population, a
malformed record or an unreadable observation is OBSERVATION_FAILED, never a
zero. Reader errors are sanitised to fixed text with no filename, payload or
context. Identities are redacted, non-copyable and bound by IDENTITY to one
generation object.
"""
from __future__ import annotations

import errno
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from . import run_window_absence as ra
from .run_window_absence import FAIL, NEG, SURV, Observation

NAMESPACES = ('pid', 'mnt', 'net', 'ipc')
LAUNCH_ONLY = 'launch-only'
_ID = re.compile(r'[0-9a-f]{64}')
_NS_LINK = re.compile(r'(pid|mnt|net|ipc):\[([0-9]+)\]')
_MAJMIN = re.compile(r'[0-9]+:[0-9]+')
_CONTROLLER = re.compile(r'[A-Za-z0-9_.=]+')
_MOUNT_TYPES = frozenset({'bind', 'volume', 'tmpfs', 'npipe', 'cluster', 'image'})
_DOCKER_TIMEOUT = 30.0
_HIDING = ('hidepid=1', 'hidepid=2', 'hidepid=invisible', 'hidepid=noaccess', 'hidepid=ptraceable',
           'subset=pid')
_T = TypeVar('_T')


def _sanitised() -> OSError:
    """A fixed-text OSError: no filename, no payload."""
    return OSError(errno.EIO, 'run_window_teardown: observation failed')


def _checked(call: Callable[[], _T]) -> _T:
    """Run one OS read; on any OSError raise a fixed-text error OUTSIDE the
    handler, so it carries neither the original filename nor its context."""
    ok = False
    value: Any = None
    try:
        value = call()
        ok = True
    except OSError:
        pass
    if not ok:
        raise _sanitised()
    result: _T = value
    return result


class ProcReader(Protocol):
    """Trusted reader of a /proc tree. `node` is a pid or `pid/task/tid`.
    Every method raises a sanitised OSError on failure."""

    def pids(self) -> list[str]: ...
    def tasks(self, pid: str) -> list[str]: ...
    def read(self, node: str, name: str) -> bytes: ...
    def readlink(self, node: str, name: str) -> str: ...
    def listdir(self, node: str, sub: str) -> list[str]: ...
    def stat_entry(self, node: str, sub: str, name: str) -> os.stat_result: ...
    def lstat_under_root(self, pid: str, path: str) -> os.stat_result: ...
    def listdir_under_root(self, pid: str, path: str) -> list[str]: ...
    def root_is_ns_root(self, node: str) -> bool: ...


class DockerReader(Protocol):
    """Trusted, read-only Docker access. `inspect` raises on any failure;
    `present` is True, False, or None when the daemon did not answer."""

    def inspect(self, container: str) -> Mapping[str, Any]: ...
    def present(self, container_id: str) -> bool | None: ...


def _read_bytes(path: str) -> bytes:
    with open(path, 'rb') as handle:
        return handle.read()


class RealProc:
    def __init__(self, root: str = '/proc') -> None:
        self._root = root

    def __repr__(self) -> str:
        return '<RealProc>'

    def _path(self, node: str, *rest: str) -> str:
        return os.path.join(self._root, node, *rest)

    def pids(self) -> list[str]:
        return [n for n in _checked(lambda: os.listdir(self._root)) if n.isdigit()]

    def tasks(self, pid: str) -> list[str]:
        return [f'{pid}/task/{t}' for t in self.listdir(pid, 'task') if t.isdigit()]

    def read(self, node: str, name: str) -> bytes:
        return _checked(lambda: _read_bytes(self._path(node, name)))

    def readlink(self, node: str, name: str) -> str:
        return _checked(lambda: os.readlink(self._path(node, name)))

    def listdir(self, node: str, sub: str) -> list[str]:
        return _checked(lambda: os.listdir(self._path(node, sub)))

    def stat_entry(self, node: str, sub: str, name: str) -> os.stat_result:
        return _checked(lambda: os.stat(self._path(node, sub, name)))

    def _under_root(self, pid: str, path: str) -> str:
        # The caller lstat()s every component first; nothing here resolves a
        # link inside the container's root.
        return os.path.join(self._root, pid, 'root', path.lstrip('/'))

    def lstat_under_root(self, pid: str, path: str) -> os.stat_result:
        return _checked(lambda: os.lstat(self._under_root(pid, path)))

    def listdir_under_root(self, pid: str, path: str) -> list[str]:
        return _checked(lambda: os.listdir(self._under_root(pid, path)))

    def root_is_ns_root(self, node: str) -> bool:
        """True only if the task's root directory is its own parent, which
        holds for a mount namespace's root and never for a chroot (even one
        onto the root of a nested filesystem): looking up '..' through
        /proc/<task>/root is not confined by the task's chroot."""
        base = self._path(node, 'root')
        here = _checked(lambda: os.stat(base))
        up = _checked(lambda: os.stat(os.path.join(base, '..')))
        return (here.st_dev, here.st_ino) == (up.st_dev, up.st_ino)


class RealDocker:
    """`docker inspect` and `docker ps` only, with the handle's own env (the
    #85 rule). No other verb exists. Failures are sanitised: no argv, no
    container name, no payload."""

    VERBS = ('inspect', 'ps')

    def __init__(self, docker_bin: Sequence[str], env: Mapping[str, str] | None = None) -> None:
        self._bin = list(docker_bin)
        self._env = dict(env) if env is not None else None

    def __repr__(self) -> str:
        return '<RealDocker>'

    def _run(self, *argv: str) -> str:
        if not argv or argv[0] not in self.VERBS:
            raise _sanitised()
        out = None
        try:
            proc = subprocess.run([*self._bin, *argv], capture_output=True, text=True, env=self._env,
                                  timeout=_DOCKER_TIMEOUT, check=False)
            if proc.returncode == 0:
                out = proc.stdout
        except (OSError, ValueError, subprocess.SubprocessError):
            pass  # ValueError covers a UnicodeDecodeError carrying output bytes.
        if out is None:
            raise _sanitised()
        return out

    def inspect(self, container: str) -> Mapping[str, Any]:
        text = self._run('inspect', '--type', 'container', '--', container)
        data: Any = None
        try:
            data = json.loads(text)
        except ValueError:
            pass
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise _sanitised()
        record: Mapping[str, Any] = data[0]
        return record

    def present(self, container_id: str) -> bool | None:
        """True only for the exact id; False only for an empty answer; None
        for no answer or any other output."""
        try:
            out = self._run('ps', '-a', '-q', '--no-trunc', '--filter', f'id={container_id}')
        except OSError:
            return None
        if out == '':
            return False  # Only an exactly empty answer means absent.
        lines = out.split('\n')
        if lines[-1] == '':
            lines = lines[:-1]
        if lines and all(line == container_id for line in lines):
            return True
        return None


class LaunchIdentity(ra._NoCopy):
    """One holder container as observed at launch. Private and redacted."""

    def __init__(self, generation: object) -> None:
        self._generation = generation
        self._usable = False
        self._id = ''
        self._pid = ''
        self._start = ''
        self._cgroups: tuple[tuple[str, str, str], ...] = ()
        self._ns: dict[str, str] = {}
        self._host_ns: dict[str, str] = {}
        self._bind_sockets = -1
        self._init_socket_fds = -1

    def __repr__(self) -> str:
        return '<LaunchIdentity redacted>'

    @property
    def usable(self) -> bool:
        return self._usable


@dataclass(frozen=True)
class ScopedObservation:
    """An observation that holds only for a stated scope."""

    observation: Observation
    scope: str


def _stat_fields(proc: ProcReader, node: str) -> list[str]:
    text = proc.read(node, 'stat').decode('ascii', 'replace')
    close = text.rfind(')')
    rest = text[close + 2:].split() if close >= 0 else []
    if len(rest) < 20 or not rest[19].isdigit():
        raise _sanitised()
    return rest


def _start_time(proc: ProcReader, node: str) -> str:
    """Field 22 of stat, counted after comm's LAST ')'; refuses a zombie."""
    rest = _stat_fields(proc, node)
    if rest[0] in ('Z', 'X', 'x'):
        raise _sanitised()
    return rest[19]


def _cgroup_entries(data: bytes) -> tuple[tuple[str, str, str], ...]:
    """(hierarchy-id, controllers, path) for every line; v1 and v2 forms."""
    entries = []
    for line in data.decode('utf-8', 'replace').split('\n'):
        if not line:
            continue
        parts = line.split(':', 2)
        controllers = parts[1].split(',') if len(parts) == 3 and parts[1] else []
        if (len(parts) != 3 or not parts[0].isdigit() or not parts[2].startswith('/')
                or (parts[0] == '0') != (parts[1] == '')
                or any(not _CONTROLLER.fullmatch(c) for c in controllers)):
            raise _sanitised()
        entries.append((parts[0], parts[1], parts[2]))
    if not entries:
        raise _sanitised()
    return tuple(entries)


def _ns_link(value: str, kind: str) -> str:
    match = _NS_LINK.fullmatch(value)
    if match is None or match.group(1) != kind:
        raise _sanitised()
    return value


def _namespaces(proc: ProcReader, node: str) -> dict[str, str]:
    return {k: _ns_link(proc.readlink(node, f'ns/{k}'), k) for k in NAMESPACES}


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base.rstrip('/') + '/')


def _in_captured_cgroup(entries: Iterable[tuple[str, str, str]],
                        captured: set[tuple[str, str, str]]) -> bool:
    return any(h == ch and c == cc and _under(p, cp) for h, c, p in entries for ch, cc, cp in captured)


def _sockets_at(proc: ProcReader, pid: str, dest: str, rows: list[tuple[str, str, str]]) -> int:
    """Sockets at a bind DESTINATION inside the task's root, counted without
    following any link. The destination must be the mountpoint of the task's
    effective (last-listed) mount there, with a matching device, and two walks
    of the tree must agree exactly. Any link, read error, missing mount or
    change raises."""
    parts = [p for p in dest.split('/') if p]
    if not parts or any(p in ('.', '..') for p in parts):
        raise _sanitised()
    path = ''
    for part in parts:
        path = f'{path}/{part}'
        if stat.S_ISLNK(proc.lstat_under_root(pid, path).st_mode):
            raise _sanitised()
    # The walk goes through the task's own root, so it counts what the
    # container actually sees at the destination. The record check confirms
    # that the destination IS a mountpoint there (the effective, last-listed
    # one) on the walked device; two mounts of one filesystem share a device,
    # which this does not separate and does not need to.
    mounted = [dev for dev, _, mountpoint in rows if mountpoint == path]
    info = proc.lstat_under_root(pid, path)
    if not mounted or mounted[-1] != f'{os.major(info.st_dev)}:{os.minor(info.st_dev)}':
        raise _sanitised()  # Not the effective bind the container sees.
    first = _walk_tree(proc, pid, path, 0)
    if _walk_tree(proc, pid, path, 0) != first:
        raise _sanitised()  # The tree changed while it was read.
    return sum(1 for _, mode, _, _ in first if stat.S_ISSOCK(mode))


def _walk_tree(proc: ProcReader, pid: str, path: str, depth: int) -> list[tuple[str, int, int, int]]:
    """(path, mode, device, inode) for the whole tree, so a second walk also
    notices an entry replaced by another inode of the same type."""
    if depth > ra.LIMITS['depth']:
        raise _sanitised()
    info = proc.lstat_under_root(pid, path)
    mode = info.st_mode
    out = [(path, mode, info.st_dev, info.st_ino)]
    if stat.S_ISDIR(mode):
        for name in sorted(proc.listdir_under_root(pid, path)):
            out.extend(_walk_tree(proc, pid, f'{path}/{name}', depth + 1))
    return out


def _mounts(info: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    mounts = info.get('Mounts')
    if not isinstance(mounts, list):
        raise _sanitised()
    for m in mounts:
        if (not isinstance(m, dict) or not all(isinstance(m.get(k), str) for k in ('Type', 'Source', 'Destination'))
                or m['Type'] not in _MOUNT_TYPES or not m['Destination'].startswith('/')):
            raise _sanitised()
    return mounts


def _fd_table(proc: ProcReader, pid: str) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((name, proc.readlink(pid, f'fd/{name}')) for name in proc.listdir(pid, 'fd')))


def _running_pid(info: Mapping[str, Any]) -> tuple[str, str] | None:
    cid = info.get('Id')
    state = info.get('State')
    if not isinstance(cid, str) or not _ID.fullmatch(cid) or not isinstance(state, dict):
        return None
    pid = state.get('Pid')
    if type(pid) is not int or pid <= 0 or state.get('Running') is not True:
        return None
    return cid, str(pid)


def procfs_ok(proc: ProcReader) -> bool:
    """The visible preconditions: a nonempty pid population, the controller in
    the same PID namespace as pid 1, and a procfs mount with no hiding option."""
    try:
        if not proc.pids():
            return False
        if _ns_link(proc.readlink('self', 'ns/pid'), 'pid') != _ns_link(proc.readlink('1', 'ns/pid'), 'pid'):
            return False
        table = proc.read('self', 'mountinfo').decode('utf-8', 'replace')
    except OSError:
        return False
    found = False
    for line in table.split('\n'):
        fields = line.split()
        sep = next((i for i in range(6, len(fields)) if fields[i] == '-'), None)
        if sep is None or len(fields) != sep + 4:
            continue
        if fields[sep + 1] == 'proc' and fields[4] == '/proc':
            found = True
            options = fields[sep + 3].split(',') + fields[5].split(',')
            if any(option in _HIDING for option in options):
                return False
    return found


def capture_launch_identity(container: str, *, generation: object, docker: DockerReader,
                            proc: ProcReader | None = None) -> LaunchIdentity:
    """Observe one started holder container. Read-only. On any failure the
    identity is returned unusable, which makes every later fact FAILED."""
    if generation is None:
        raise ra.CensusRefused('run_window_teardown: a capture needs a generation object')
    proc = proc if proc is not None else RealProc()
    ident = LaunchIdentity(generation)
    try:
        info = docker.inspect(container)
        bound = _running_pid(info)
        if bound is None:
            return ident
        cid, pid = bound
        start = _start_time(proc, pid)
        cgroups = _cgroup_entries(proc.read(pid, 'cgroup'))
        leaves = {cid, f'docker-{cid}.scope'}
        if not any(path.rstrip('/').rsplit('/', 1)[-1] in leaves for _, _, path in cgroups):
            return ident  # The task is not in this container's own cgroup on this host.
        ns = _namespaces(proc, pid)
        host = _namespaces(proc, '1')
        rows = _table(proc.read(pid, 'mountinfo'))
        binds = sum(_sockets_at(proc, pid, m['Destination'], rows) for m in _mounts(info) if m['Type'] == 'bind')
        fds = _fd_table(proc, pid)
        if _fd_table(proc, pid) != fds:
            return ident  # The fd table changed while it was read.
        sockets = sum(1 for _, target in fds if target.startswith('socket:'))
        if _start_time(proc, pid) != start or _running_pid(docker.inspect(container)) != (cid, pid):
            return ident  # The pid was reused, or the container changed.
    except (OSError, KeyError, TypeError, ValueError):
        return ident
    ident._id, ident._pid, ident._start = cid, pid, start
    ident._cgroups, ident._ns, ident._host_ns = cgroups, ns, host
    ident._bind_sockets, ident._init_socket_fds = binds, sockets
    ident._usable = True
    return ident


def _still_listed(proc: ProcReader, pid: str) -> bool | None:
    try:
        return pid in proc.pids()
    except OSError:
        return None


def _usable(identities: Iterable[LaunchIdentity], generation: object | None) -> list[LaunchIdentity] | None:
    out = list(identities)
    if not out or any(not isinstance(i, LaunchIdentity) or not i._usable for i in out):
        return None
    anchor = out[0]._generation if generation is None else generation
    if any(i._generation is not anchor for i in out):
        return None
    return out


def _nodes(proc: ProcReader) -> list[tuple[str, str]] | None:
    """(pid, node) for every task of every listed process; None on failure.
    A process that vanished mid-listing is skipped only if a relisting omits
    it. An empty population is a failure."""
    try:
        pids = proc.pids()
    except OSError:
        return None
    out: list[tuple[str, str]] = []
    for pid in pids:
        try:
            tasks = proc.tasks(pid)
        except OSError:
            if _still_listed(proc, pid) is False:
                continue
            return None
        if not tasks:
            if _still_listed(proc, pid) is False:
                continue
            return None
        out.extend((pid, t) for t in tasks)
    return out or None


def confirm_teardown(identities: Iterable[LaunchIdentity], *, docker: DockerReader,
                     proc: ProcReader | None = None, generation: object | None = None) -> Observation:
    """The holder domain is empty. SURVIVOR_OBSERVED if any captured container
    is still known to Docker, or any task sits in a captured cgroup or shares a
    captured namespace; OBSERVATION_FAILED on any unanswered, unreadable or
    malformed observation."""
    proc = proc if proc is not None else RealProc()
    held = _usable(identities, generation)
    if held is None or not procfs_ok(proc):
        return FAIL
    for ident in held:
        present: bool | None = None
        try:
            present = docker.present(ident._id)
        except Exception:  # noqa: BLE001 - a reader failure is an unanswered query
            present = None
        if present is None:
            return FAIL
        if present:
            return SURV
    cgroups = {c for i in held for c in i._cgroups}
    namespaces = {i._ns[k] for i in held for k in NAMESPACES}
    nodes = _nodes(proc)
    if nodes is None:
        return FAIL
    survivor = False
    for pid, node in nodes:
        try:
            before = _stat_fields(proc, node)[19]
            entries = _cgroup_entries(proc.read(node, 'cgroup'))
            links = set(_namespaces(proc, node).values())
            if _stat_fields(proc, node)[19] != before:
                return FAIL  # The task was replaced between related reads.
        except OSError:
            if _still_listed(proc, pid) is False:
                continue
            return FAIL
        if _in_captured_cgroup(entries, cgroups) or links & namespaces:
            survivor = True
    return SURV if survivor else NEG


def _holder_pass(census: ra.Census, proc: ProcReader) -> Observation:
    targets = {item.identity for item in census._entries}
    if census._root is not None:
        targets.add(census._root.identity)
    me = str(os.getpid())
    nodes = _nodes(proc)
    if nodes is None:
        return FAIL
    survivor = False
    seen_maps: set[str] = set()
    for pid, node in nodes:
        if pid == me:
            continue  # The controller's own tasks; its children are NOT excluded.
        try:
            before = _start_time(proc, node)
        except OSError:
            if _still_listed(proc, pid) is False:
                continue
            return FAIL
        subs = ['fd'] if pid in seen_maps else ['fd', 'map_files']
        seen_maps.add(pid)
        for sub in subs:
            where = node if sub == 'fd' else pid  # Mappings belong to the process.
            try:
                names = proc.listdir(where, sub)
            except OSError:
                if _still_listed(proc, pid) is False:
                    break
                return FAIL
            for name in names:
                try:
                    info = proc.stat_entry(where, sub, name)
                except OSError:
                    try:
                        again = name in proc.listdir(where, sub)
                    except OSError:
                        again = _still_listed(proc, pid) is not False
                    if again:
                        return FAIL
                    continue
                if ra.Identity(info) in targets:
                    survivor = True
        try:
            if _start_time(proc, node) != before:
                return FAIL  # The task was replaced while it was read.
        except OSError:
            if _still_listed(proc, pid) is not False:
                return FAIL
    return SURV if survivor else NEG


def fact_no_holder(census: ra.Census, *, proc: ProcReader | None = None) -> Observation:
    """Fact 2 (corroboration): no surviving task other than the controller's
    holds an fd to, and no surviving process maps, any census object or the
    census root. Two passes must agree. Run while the census entries are held."""
    proc = proc if proc is not None else RealProc()
    if not census.complete or census._released or not procfs_ok(proc):
        return FAIL
    first = _holder_pass(census, proc)
    if first is not NEG:
        return first
    second = _holder_pass(census, proc)
    if second is NEG:
        return NEG
    return SURV if second is SURV else FAIL


def fact_channel_isolated(identities: Iterable[LaunchIdentity],
                          generation: object | None = None) -> ScopedObservation:
    """Fact 2b at LAUNCH: every holder had private PID, mount, network and IPC
    namespaces (validated links), no bind destination holding a socket, and no
    socket fd in init. Scoped `launch-only`; a channel acquired after launch is
    PR-1's lifetime sampler (A23)."""
    held = _usable(identities, generation)
    if held is None:
        return ScopedObservation(FAIL, LAUNCH_ONLY)
    for ident in held:
        if any(ident._ns[k] == ident._host_ns[k] for k in NAMESPACES):
            return ScopedObservation(SURV, LAUNCH_ONLY)
        if ident._bind_sockets != 0 or ident._init_socket_fds != 0:
            return ScopedObservation(SURV, LAUNCH_ONLY)
    return ScopedObservation(NEG, LAUNCH_ONLY)


def _table(data: bytes) -> list[tuple[str, str, str]]:
    """(major:minor, root, mountpoint) for every record of one mountinfo
    table. Each record has the kernel's exact shape: mount id, parent id,
    major:minor, absolute root and mountpoint, options, optional fields, '-',
    then exactly fstype, source and super options; the table ends in a newline."""
    rows = []
    for line in data.split(b'\n'):
        if not line:
            continue
        f = line.split(b' ')
        sep = next((i for i in range(6, len(f)) if f[i] == b'-'), None)
        if (sep is None or len(f) != sep + 4 or not all(f) or not f[0].isdigit() or not f[1].isdigit()
                or not _MAJMIN.fullmatch(f[2].decode('ascii', 'replace'))
                or not f[3].startswith(b'/') or not f[4].startswith(b'/') or not all(f[sep + 1:])):
            raise _sanitised()
        rows.append((f[2].decode('ascii'), f[3].decode('utf-8', 'replace'), f[4].decode('utf-8', 'replace')))
    if not rows or not data.endswith(b'\n'):
        raise _sanitised()
    return rows


def fact_superblock_gone(census: ra.Census, *, proc: ProcReader | None = None) -> Observation:
    """Fact 3, after release and a non-lazy unmount: every mount namespace is
    read through a task whose root is the namespace root, and no table lists
    the census root's device."""
    proc = proc if proc is not None else RealProc()
    if not census.complete or not census._released or census._root_dev is None or not procfs_ok(proc):
        return FAIL
    majmin = f'{os.major(census._root_dev)}:{os.minor(census._root_dev)}'
    nodes = _nodes(proc)
    if nodes is None:
        return FAIL
    covered: dict[str, bool] = {}
    listed = False
    for pid, node in nodes:
        try:
            before = _stat_fields(proc, node)[19]
            mnt = _ns_link(proc.readlink(node, 'ns/mnt'), 'mnt')
            rows = _table(proc.read(node, 'mountinfo'))
            # A table is complete only if this task's root is its mount
            # namespace's root; a chrooted task's table omits outer mounts.
            complete = proc.root_is_ns_root(node) and any(
                mountpoint == '/' and root == '/' for _, root, mountpoint in rows)
            if _stat_fields(proc, node)[19] != before:
                return FAIL
        except OSError:
            if _still_listed(proc, pid) is False:
                continue
            return FAIL
        covered[mnt] = covered.get(mnt, False) or complete
        if any(dev == majmin for dev, _, _ in rows):
            listed = True
    if not covered or not all(covered.values()):
        return FAIL  # Some mount namespace was seen only through chrooted tasks.
    return SURV if listed else NEG
