"""Read-only collectors for #619; subject-controlled Git never runs on host.

Coverage/identity floors follow the pattern in cooneycw/kyle at
4021172f70d9cfab533f82987159d82447fc644c, core/container_inventory.py:328/629.
Kernel cwd liveness follows core/cwd_liveness.py:137/258 at that same pin.
Only the patterns are adapted; this module has no dependency on that project.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import re
import stat
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import git_snapshot as gs
from .clutter import (
    CPP_KINDS,
    MAX_BYTES,
    MAX_DEPTH,
    MAX_ITEMS,
    Policy,
    Surface,
    digest,
    strict_json,
)

_SHA = re.compile(r'[0-9a-f]{40}')
_MAIL = re.compile(rb'^<!-- cc-flow-wave-msg rev=([1-9][0-9]*) [^\r\n]*-->$', re.MULTILINE)


class BoundedTree(gs.SafeTree):
    """Shared raw-read and enumeration caps also cover GitDir's internal reads."""

    def read(self, rel: str, limit: int = gs.MAX_FILE_BYTES) -> tuple[bytes, int]:
        remaining = MAX_BYTES - self.bytes_read
        if remaining <= 0:
            raise gs.Unreadable('aggregate inventory byte bound exceeded')
        return super().read(rel, min(limit, remaining))

    def listdir(self, rel: str) -> list[tuple[str, str]]:
        rows = super().listdir(rel)
        if self.entries_listed > MAX_ITEMS:
            raise gs.Unreadable('aggregate inventory enumeration bound exceeded')
        return rows

    def symlink(self, rel: str) -> tuple[str, int]:
        """Read the link itself under a pinned no-follow parent, never its target."""
        parts = self._parts(rel)
        fd = self._open_dir(parts[:-1])
        try:
            before = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISLNK(before.st_mode):
                raise gs.Unreadable('inventory encountered an unsupported special file')
            target = os.readlink(parts[-1], dir_fd=fd)
            after = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            if (before.st_dev, before.st_ino, before.st_mode, before.st_ctime_ns) != (
                    after.st_dev, after.st_ino, after.st_mode, after.st_ctime_ns):
                raise gs.Unreadable('symlink identity changed during observation')
            self.bytes_read += len(os.fsencode(target))
            if len(os.fsencode(target)) > 4096 or self.bytes_read > MAX_BYTES:
                raise gs.Unreadable('symlink observation byte bound exceeded')
            return target, stat.S_IMODE(before.st_mode)
        except OSError as exc:
            raise gs.Unreadable('symlink observation unavailable') from exc
        finally:
            os.close(fd)


class Reader:
    def __init__(self, tree: BoundedTree) -> None:
        self.tree = tree
        self.count = 0

    def put(self, items: dict[str, str], key: str, value: object) -> None:
        if key in items:
            raise gs.Unreadable('duplicate inventory logical identity')
        self.count += 1
        if self.count > MAX_ITEMS or self.tree.bytes_read > MAX_BYTES:
            raise gs.Unreadable('aggregate inventory item or byte bound exceeded')
        items[key] = digest(value)

    def read(self, path: str) -> tuple[bytes, int]:
        data, mode = self.tree.read(path)
        if self.tree.bytes_read > MAX_BYTES:
            raise gs.Unreadable('aggregate inventory byte bound exceeded')
        return data, mode

    def json_nodes(self, items: dict[str, str], key: str, value: object, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise gs.Unreadable('structured state depth bound exceeded')
        if isinstance(value, dict):
            for name, child in sorted(value.items()):
                escaped = name.replace('~', '~0').replace('/', '~1')
                node = key + '/' + escaped
                self.put(items, node, child)
                self.json_nodes(items, node, child, depth + 1)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                node = key + '/' + str(index)
                self.put(items, node, child)
                self.json_nodes(items, node, child, depth + 1)

    def structured(self, items: dict[str, str], path: str, data: bytes, family: str) -> None:
        if path.endswith('.json'):
            try:
                value = strict_json(data)
                self.json_nodes(items, 'entry:' + path, value)
            except (ValueError, TypeError, RecursionError) as exc:
                raise gs.Unreadable('structured state cannot be read faithfully') from exc
        elif family == 'mailboxes' and path.endswith('.md'):
            matches = list(_MAIL.finditer(data))
            if data.strip() and not matches:
                raise gs.Unreadable('mailbox has no supported revision framing')
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(data)
                self.put(items, 'message:' + path + '#' + match[1].decode('ascii'), data[match.start():end].hex())

    def files(self, roots: list[str], *, family: str = '', allowed_subtrees: frozenset[str] = frozenset()) -> Surface:
        items: dict[str, str] = {}

        def walk(path: str, depth: int = 0) -> None:
            if depth > MAX_DEPTH:
                raise gs.Unreadable('inventory tree depth bound exceeded')
            kind = self.tree.kind(path)
            if kind == 'missing':
                return  # A genuinely absent optional CPP/temp path is observable empty state.
            if kind == 'dir':
                if '/' + path in allowed_subtrees:
                    return  # Explicit declaration-bound blind spot, named in every report.
                self.put(items, 'directory:/' + path, 'directory')
                for name, _ in self.tree.listdir(path):
                    # Repository metadata is inventoried as Git, not counted
                    # a second time as arbitrary workspace bytes.
                    if family == 'workspace' and depth == 0 and name == '.git':
                        continue
                    walk(path + '/' + name, depth + 1)
            elif kind == 'file':
                data, mode = self.read(path)
                self.put(items, 'file:/' + path, {'mode': stat.S_IMODE(mode),
                                                'digest': hashlib.sha256(data).hexdigest()})
                if family in ('registry', 'mailboxes', 'shared'):
                    self.structured(items, '/' + path, data, family)
            else:
                target, mode = self.tree.symlink(path)
                self.put(items, 'symlink:/' + path, {'target': target, 'mode': mode})
        try:
            for path in roots:
                walk(path.lstrip('/'))
            return Surface(items)
        except (gs.Unreadable, OSError, ValueError, RecursionError) as exc:
            return Surface(items, False, f'{type(exc).__name__}: {exc}')

    def git(self, scope: dict[str, Any], namespace_root: str) -> dict[str, Surface]:
        rows: dict[str, dict[str, str]] = {name: {} for name in ('worktrees', 'local-branches', 'remote-branches', 'stashes')}
        try:
            common = gs.GitDir(self.tree, scope['gitdir'].lstrip('/'))
            refs = common.refs()
            for ref, sha in refs.items():
                if ref != 'refs/stash':
                    self.put(rows['local-branches'], ref, sha)
            for wt in gs.worktrees(common, scope['checkout'].lstrip('/'), namespace_root, refs):
                self.put(rows['worktrees'], '/' + wt.path,
                         {'head': wt.head, 'branch': wt.branch, 'gitdir': '/' + wt.gitdir})
            for name, path in sorted(scope['remotes'].items()):
                remote = gs.GitDir(self.tree, path.lstrip('/'))
                for ref, sha in remote.refs().items():
                    self.put(rows['remote-branches'], name + ':' + ref, sha)
            stash_log = scope['gitdir'].lstrip('/') + '/logs/refs/stash'
            stashes: Counter[str] = Counter()
            if self.tree.optional(stash_log):
                for line in self.tree.text(stash_log).splitlines():
                    fields = line.split(' ', 2)
                    if len(fields) != 3 or any(_SHA.fullmatch(sha) is None for sha in fields[:2]):
                        raise gs.Unreadable('stash reflog is malformed')
                    sha = fields[1]
                    if sha == '0' * 40:
                        raise gs.Unreadable('stash reflog contains a null stash identity')
                    common.tree_of(sha)
                    stashes[sha] += 1
                    self.put(rows['stashes'], sha + '#' + str(stashes[sha]), sha)
            stash = refs.get('refs/stash')
            if (stash is None) != (not stashes) or stash is not None and stash not in stashes:
                raise gs.Unreadable('stash ref and reflog population disagree')
            return {name: Surface(items) for name, items in rows.items()}
        except (gs.Unreadable, OSError, ValueError) as exc:
            return {name: Surface(items, False, f'{type(exc).__name__}: {exc}') for name, items in rows.items()}


@contextmanager
def _filesystem_ids(uid: int, gid: int) -> Iterator[None]:
    """Read proc cwd with matching filesystem credentials, keeping real/effective IDs.

    Root without SYS_PTRACE cannot necessarily read a non-root process's cwd.
    Linux's READ_FSCREDS check permits the matching identity. The observer's
    real/effective identity stays privileged; a subject cannot ptrace it as a
    same-user helper. Every transition and restoration is checked.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        set_uid, set_gid = libc.setfsuid, libc.setfsgid
    except AttributeError as exc:
        raise PermissionError('filesystem credential observation unavailable') from exc
    for function in (set_uid, set_gid):
        function.argtypes = [ctypes.c_uint]
        function.restype = ctypes.c_uint
    query = (1 << 32) - 1
    old_uid, old_gid = set_uid(query), set_gid(query)
    try:
        set_gid(gid)
        set_uid(uid)
        if set_uid(query) != uid or set_gid(query) != gid:
            raise PermissionError('filesystem credential transition unavailable')
        yield
    finally:
        set_uid(old_uid)
        set_gid(old_gid)
        if set_uid(query) != old_uid or set_gid(query) != old_gid:
            raise PermissionError('filesystem credential restoration unavailable')


def _cwd_stat(path: Path) -> os.stat_result:
    data = (path / 'status').read_bytes()
    if len(data) > 65536:
        raise ValueError('process status bound exceeded')
    credentials = {}
    for line in data.splitlines():
        if line.startswith((b'Uid:', b'Gid:')):
            values = [int(value) for value in line.split()[1:]]
            if len(values) != 4 or len(set(values[:3])) != 1 or not 0 <= values[0] < (1 << 32) - 1:
                raise ValueError('process credentials cannot be observed faithfully')
            credentials[line[:3]] = values[0]
    if set(credentials) != {b'Uid', b'Gid'}:
        raise ValueError('process credentials unavailable')
    # Open before changing filesystem IDs: fixture/export parent permissions
    # cannot redirect the lookup, and the proc directory pins this process.
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with _filesystem_ids(credentials[b'Uid'], credentials[b'Gid']):
            return os.stat('cwd', dir_fd=fd)
    finally:
        os.close(fd)


def processes(proc_root: Path = Path('/proc'), *, observer_pid: int | None = None) -> Surface:
    """Kernel process identities and cwd inodes; never read environ or retain argv.

    PID+starttime prevents PID reuse from looking like preserved state. nlink
    detects deleted cwd even if another directory is recreated at the same path.
    A vanished process may be skipped; a still-visible unreadable one is UNKNOWN.
    """
    items: dict[str, str] = {}
    deleted: list[str] = []
    try:
        for index, path in enumerate(proc_root.iterdir()):
            if index >= MAX_ITEMS:
                raise ValueError('process census bound exceeded')
            if not path.name.isdigit() or int(path.name) == observer_pid:
                continue
            try:
                fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
                if fields[0] in ('Z', 'X'):
                    continue  # Not live; do not silently discard paused/sleeping processes.
                key = path.name + ':' + fields[19]
                info = _cwd_stat(path)
                command = (path / 'comm').read_bytes()
                if len(command) > 4096:
                    raise ValueError('process name bound exceeded')
                check = (path / 'stat').read_text().rsplit(')', 1)[1].split()
                if check[19] != fields[19]:
                    raise ValueError('process identity changed during census')
                items[key] = digest({'comm': command.hex(), 'cwd_dev': info.st_dev,
                                     'cwd_ino': info.st_ino, 'cwd_nlink': info.st_nlink})
                if info.st_nlink == 0:
                    deleted.append(key)
            except (FileNotFoundError, ProcessLookupError):
                if path.exists():
                    raise ValueError('visible process has unreadable or vanished cwd') from None
                continue
        return Surface(items, deleted_cwds=tuple(sorted(deleted)))
    except (OSError, ValueError, IndexError) as exc:
        return Surface(items, False, f'process inventory unavailable: {type(exc).__name__}', tuple(sorted(deleted)))


def capture_role(policy: Policy, role: str, root: Path, *, proc_root: Path = Path('/proc'),
                 observer_pid: int | None = None, namespace_root: str = '/') -> dict[str, Surface]:
    if role not in policy.roles:
        raise ValueError('undeclared inventory role')
    scope = policy.data['roles'][role]
    try:
        reader = Reader(BoundedTree(root))
        rows = reader.git(scope, namespace_root)
        rows['workspace'] = reader.files([scope['checkout']], family='workspace',
                                         allowed_subtrees=policy.allowed_subtrees(role + '/workspace'))
        for family in CPP_KINDS:
            rows['cpp-' + family] = reader.files(scope['cpp'][family], family=family)
        rows['temp'] = reader.files(scope['temp_roots'])
    except gs.Unreadable as exc:
        rows = {kind: Surface({}, False, str(exc)) for kind in (
            'worktrees', 'local-branches', 'remote-branches', 'stashes', 'workspace',
            *(f'cpp-{family}' for family in CPP_KINDS), 'temp')}
    rows['processes'] = processes(proc_root, observer_pid=observer_pid)
    return {role + '/' + kind: row for kind, row in rows.items()}


def capture_shared(policy: Policy, root: Path) -> Surface:
    try:
        reader = Reader(BoundedTree(root))
        for path in policy.data['shared_roots']:
            if reader.tree.kind(path.lstrip('/')) != 'dir':
                raise gs.Unreadable('declared shared-volume root unavailable')
        return reader.files(policy.data['shared_roots'], family='shared')
    except gs.Unreadable as exc:
        return Surface({}, False, str(exc))
