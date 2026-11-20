"""Removed-root absence evidence, part 2: teardown boundary, facts 2, 2b and 3
(#797 A-2, SECRET-PATH).

This continues docs/specs/evaluation-facility/run-window-contracts.md
section 2.2. It holds identities of the containers that held credentials (ids,
pids, cgroup paths, namespace inodes) and of the roots they wrote. It never
reads a credential's bytes.

- `capture_launch_identity` is a READ-ONLY observation, taken once per role
  or login container after `prepare()` has started it. It uses `docker
  inspect` and `/proc` only; no argv builder is touched and no mutating
  Docker verb is issued.
- `confirm_teardown` reports whether the holder domain is empty: every
  captured container gone (Docker answered), no process left in a captured
  cgroup, and none sharing a captured PID, mount, network or IPC namespace.
- `fact_no_holder` (fact 2) is corroboration: a `/proc` fd and `map_files`
  census of the surviving processes finds no census object. The controller
  itself is excluded; its census descriptors are O_CLOEXEC, so a child it
  spawns cannot inherit one.
- `fact_channel_isolated` (fact 2b) judges the launch captures and says so:
  its result is scoped `launch-only`. The design's lifetime invariant needs
  PR-1's sampler, and A-3 must not treat a launch-only 2b as sufficient.
- `fact_superblock_gone` (fact 3) runs after the census entries are released
  and the tmpfs is unmounted (by the caller). It requires that no readable
  mount table lists the census root's device, which catches bind aliases
  that carry a different mount id.

Every read is checked. A listed pid that cannot be read is skipped only if a
fresh listing omits it; an unreadable observation is OBSERVATION_FAILED,
never a zero. Refusals are fixed text raised outside handlers. Identities are
redacted, non-copyable and bound to one generation object.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from . import run_window_absence as ra
from .run_window_absence import FAIL, NEG, SURV, Observation

NAMESPACES = ('pid', 'mnt', 'net', 'ipc')
LAUNCH_ONLY = 'launch-only'
_ID = re.compile(r'[0-9a-f]{64}')
_MOUNT_TYPES = frozenset({'bind', 'volume', 'tmpfs', 'npipe', 'cluster', 'image'})
_DOCKER_TIMEOUT = 30.0


class ProcReader(Protocol):
    """Trusted reader of a /proc tree. Every method raises OSError on failure."""

    def pids(self) -> list[str]: ...
    def read(self, pid: str, name: str) -> bytes: ...
    def readlink(self, pid: str, name: str) -> str: ...
    def listdir(self, pid: str, sub: str) -> list[str]: ...
    def stat_entry(self, pid: str, sub: str, name: str) -> os.stat_result: ...


class DockerReader(Protocol):
    """Trusted, read-only Docker access. `inspect` raises on any failure;
    `present` is True, False, or None when the daemon did not answer."""

    def inspect(self, container: str) -> Mapping[str, Any]: ...
    def present(self, container_id: str) -> bool | None: ...


class RealProc:
    def __init__(self, root: str = '/proc') -> None:
        self._root = root

    def __repr__(self) -> str:
        return '<RealProc>'

    def pids(self) -> list[str]:
        return [n for n in os.listdir(self._root) if n.isdigit()]

    def _path(self, pid: str, *rest: str) -> str:
        return os.path.join(self._root, pid, *rest)

    def read(self, pid: str, name: str) -> bytes:
        with open(self._path(pid, name), 'rb') as handle:
            return handle.read()

    def readlink(self, pid: str, name: str) -> str:
        return os.readlink(self._path(pid, name))

    def listdir(self, pid: str, sub: str) -> list[str]:
        return os.listdir(self._path(pid, sub))

    def stat_entry(self, pid: str, sub: str, name: str) -> os.stat_result:
        return os.stat(self._path(pid, sub, name))


class RealDocker:
    """`docker inspect` and `docker ps` only, run with the handle's own env
    (the #85 rule: later calls must reach the daemon that holds the
    container). No other verb exists here."""

    VERBS = ('inspect', 'ps')

    def __init__(self, docker_bin: Sequence[str], env: Mapping[str, str] | None = None) -> None:
        self._bin = list(docker_bin)
        self._env = dict(env) if env is not None else None

    def __repr__(self) -> str:
        return '<RealDocker>'

    def _run(self, *argv: str) -> str:
        if argv[0] not in self.VERBS:
            raise OSError('verb not permitted')
        proc = subprocess.run([*self._bin, *argv], capture_output=True, text=True, env=self._env,
                              timeout=_DOCKER_TIMEOUT, check=False)
        if proc.returncode != 0:
            raise OSError('docker did not answer')
        return proc.stdout

    def inspect(self, container: str) -> Mapping[str, Any]:
        data = json.loads(self._run('inspect', '--type', 'container', '--', container))
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise OSError('inspect answered unexpectedly')
        return data[0]

    def present(self, container_id: str) -> bool | None:
        try:
            out = self._run('ps', '-a', '-q', '--no-trunc', '--filter', f'id={container_id}')
        except (OSError, subprocess.SubprocessError):
            return None
        return bool(out.strip())


class LaunchIdentity(ra._NoCopy):
    """One holder container as observed at launch. Private and redacted."""

    def __init__(self, generation: object) -> None:
        self._generation = generation
        self._usable = False
        self._id = ''
        self._pid = ''
        self._start = ''
        self._cgroups: tuple[str, ...] = ()
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


def _start_time(proc: ProcReader, pid: str) -> str:
    """Field 22 of /proc/<pid>/stat, counted after comm's LAST ')'; refuses a
    zombie or dead process."""
    text = proc.read(pid, 'stat').decode('ascii', 'replace')
    rest = text[text.rindex(')') + 2:].split()
    if not rest or rest[0] in ('Z', 'X', 'x') or len(rest) < 20 or not rest[19].isdigit():
        raise OSError('process not usable')
    return rest[19]


def _cgroup_paths(data: bytes) -> tuple[str, ...]:
    paths = []
    for line in data.decode('utf-8', 'replace').splitlines():
        if not line:
            continue
        parts = line.split(':', 2)
        if len(parts) != 3 or not parts[2].startswith('/'):
            raise ValueError('cgroup line not usable')
        paths.append(parts[2])
    if not paths:
        raise ValueError('no cgroup')
    return tuple(paths)


def _socket_count(path: str) -> int:
    """Sockets at a bind source or anywhere beneath it; any error raises."""
    info = os.lstat(path)
    if stat.S_ISSOCK(info.st_mode):
        return 1
    if not stat.S_ISDIR(info.st_mode):
        return 0
    count = 0

    def fail(err: OSError) -> None:
        raise err

    for root, dirs, files in os.walk(path, onerror=fail):
        for name in dirs + files:
            if stat.S_ISSOCK(os.lstat(os.path.join(root, name)).st_mode):
                count += 1
    return count


def _mounts(info: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    mounts = info.get('Mounts')
    if not isinstance(mounts, list):
        raise ValueError('mounts not usable')
    for m in mounts:
        if (not isinstance(m, dict) or not all(isinstance(m.get(k), str) for k in ('Type', 'Source', 'Destination'))
                or m['Type'] not in _MOUNT_TYPES):
            raise ValueError('mount not usable')
    return mounts


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
        cid = info.get('Id')
        state = info.get('State')
        if not isinstance(cid, str) or not _ID.fullmatch(cid) or not isinstance(state, dict):
            return ident
        pid = state.get('Pid')
        if type(pid) is not int or pid <= 0 or state.get('Running') is not True:
            return ident
        spid = str(pid)
        start = _start_time(proc, spid)
        cgroups = _cgroup_paths(proc.read(spid, 'cgroup'))
        ns = {k: proc.readlink(spid, f'ns/{k}') for k in NAMESPACES}
        host = {k: proc.readlink('1', f'ns/{k}') for k in NAMESPACES}
        binds = sum(_socket_count(m['Source']) for m in _mounts(info) if m['Type'] == 'bind')
        sockets = sum(1 for n in proc.listdir(spid, 'fd') if proc.readlink(spid, f'fd/{n}').startswith('socket:'))
        if _start_time(proc, spid) != start:
            return ident  # The pid was reused while it was being read.
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.SubprocessError):
        return ident
    ident._id, ident._pid, ident._start = cid, spid, start
    ident._cgroups, ident._ns, ident._host_ns = cgroups, ns, host
    ident._bind_sockets, ident._init_socket_fds = binds, sockets
    ident._usable = True
    return ident


def _still_listed(proc: ProcReader, pid: str) -> bool | None:
    """True if a fresh listing still shows pid, False if not, None if the
    listing itself failed."""
    try:
        return pid in proc.pids()
    except OSError:
        return None


def _usable(identities: Iterable[LaunchIdentity], generation: object | None) -> list[LaunchIdentity] | None:
    out = list(identities)
    if not out or any(not isinstance(i, LaunchIdentity) or not i._usable for i in out):
        return None
    if generation is not None and any(i._generation is not generation for i in out):
        return None
    if len({i._generation for i in out}) != 1:
        return None
    return out


def confirm_teardown(identities: Iterable[LaunchIdentity], *, docker: DockerReader,
                     proc: ProcReader | None = None, generation: object | None = None) -> Observation:
    """The holder domain is empty. SURVIVOR_OBSERVED if any captured container
    is still known to Docker, or any process sits in a captured cgroup or
    shares a captured namespace; OBSERVATION_FAILED on any unanswered or
    unreadable observation."""
    proc = proc if proc is not None else RealProc()
    held = _usable(identities, generation)
    if held is None:
        return FAIL
    for ident in held:
        present = docker.present(ident._id)
        if present is None:
            return FAIL
        if present:
            return SURV
    cgroups = {p for i in held for p in i._cgroups}
    namespaces = {i._ns[k] for i in held for k in NAMESPACES}
    try:
        pids = proc.pids()
    except OSError:
        return FAIL
    survivor = False
    for pid in pids:
        try:
            # Readability only: a zombie is still listed and still read.
            proc.read(pid, 'stat')
            paths = _cgroup_paths(proc.read(pid, 'cgroup'))
            links = {proc.readlink(pid, f'ns/{k}') for k in NAMESPACES}
        except OSError:
            again = _still_listed(proc, pid)
            if again is False:
                continue  # Exited mid-read: a fresh listing proves it gone.
            return FAIL
        except ValueError:
            return FAIL
        if any(p == c or p.startswith(c.rstrip('/') + '/') for p in paths for c in cgroups):
            survivor = True
        if links & namespaces:
            survivor = True
    return SURV if survivor else NEG


def fact_no_holder(census: ra.Census, *, proc: ProcReader | None = None) -> Observation:
    """Fact 2 (corroboration): no surviving process other than the controller
    holds an fd to, or maps, any census object. Run while the census entries
    are still held."""
    proc = proc if proc is not None else RealProc()
    if not census.complete or census._released:
        return FAIL
    # The root is a target too: a process holding the root directory keeps a
    # lazily detached tmpfs alive even though no table lists it any more.
    targets = {item.identity for item in census._entries}
    if census._root is not None:
        targets.add(census._root.identity)
    me = str(os.getpid())
    try:
        pids = proc.pids()
    except OSError:
        return FAIL
    survivor = False
    for pid in pids:
        if pid == me:
            continue  # The controller's own census fds; its children are NOT excluded.
        for sub in ('fd', 'map_files'):
            try:
                names = proc.listdir(pid, sub)
            except OSError:
                if _still_listed(proc, pid) is False:
                    break
                return FAIL
            for name in names:
                try:
                    info = proc.stat_entry(pid, sub, name)
                except OSError:
                    try:
                        again = name in proc.listdir(pid, sub)
                    except OSError:
                        again = _still_listed(proc, pid) is not False
                    if again:
                        return FAIL
                    continue
                if ra.Identity(info) in targets:
                    survivor = True
    return SURV if survivor else NEG


def fact_channel_isolated(identities: Iterable[LaunchIdentity],
                          generation: object | None = None) -> ScopedObservation:
    """Fact 2b at LAUNCH: every holder had private PID, mount, network and IPC
    namespaces, no bind source that is or contains a socket, and no socket fd
    in its init process. The result is scoped `launch-only`; a channel
    acquired after launch is PR-1's lifetime sampler (A23)."""
    held = _usable(identities, generation)
    if held is None:
        return ScopedObservation(FAIL, LAUNCH_ONLY)
    for ident in held:
        if any(ident._ns[k] == ident._host_ns[k] for k in NAMESPACES):
            return ScopedObservation(SURV, LAUNCH_ONLY)
        if ident._bind_sockets != 0 or ident._init_socket_fds != 0:
            return ScopedObservation(SURV, LAUNCH_ONLY)
    return ScopedObservation(NEG, LAUNCH_ONLY)


_MAJMIN = re.compile(r'[0-9]+:[0-9]+')


def _table_matches(data: bytes, majmin: str) -> int:
    """Rows in one mountinfo table whose device is majmin. Every row must be a
    well-formed record (ids, major:minor, absolute root and mountpoint, the
    '-' separator after at least six fields and three fields after it)."""
    rows = 0
    hits = 0
    for line in data.decode('utf-8', 'replace').splitlines():
        if not line.strip():
            continue
        f = line.split()
        sep = next((i for i in range(6, len(f)) if f[i] == '-'), None)
        if (sep is None or len(f) < sep + 4 or not f[0].isdigit() or not f[1].isdigit()
                or not _MAJMIN.fullmatch(f[2]) or not f[3].startswith('/') or not f[4].startswith('/')):
            raise ValueError('mount table not usable')
        rows += 1
        if f[2] == majmin:
            hits += 1
    if rows == 0:
        raise ValueError('mount table empty')
    return hits


def fact_superblock_gone(census: ra.Census, *, proc: ProcReader | None = None) -> Observation:
    """Fact 3, after release and a non-lazy unmount: no readable mount table
    lists the census root's device."""
    proc = proc if proc is not None else RealProc()
    if not census.complete or not census._released or census._root_dev is None:
        return FAIL
    majmin = f'{os.major(census._root_dev)}:{os.minor(census._root_dev)}'
    try:
        pids = proc.pids()
    except OSError:
        return FAIL
    if not pids:
        return FAIL
    listed = False
    scanned = 0
    for pid in pids:
        try:
            data = proc.read(pid, 'mountinfo')
        except OSError:
            if _still_listed(proc, pid) is False:
                continue
            return FAIL
        try:
            if _table_matches(data, majmin):
                listed = True
        except ValueError:
            return FAIL
        scanned += 1
    if scanned == 0:
        return FAIL
    return SURV if listed else NEG
