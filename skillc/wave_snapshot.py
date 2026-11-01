"""Bounded opaque file/ref digests; also executed as isolated controller code.

No message syntax is parsed. Links are hashed as links, never followed. A
failed or racing read is unavailable evidence, never an empty revision.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys


class SnapshotUnavailable(ValueError):
    """The controller could not observe a complete stable surface."""


def _frame(digest: object, value: bytes) -> None:
    # hashlib's concrete runtime type is deliberately not an import dependency.
    digest.update(len(value).to_bytes(8, 'big'))  # type: ignore[attr-defined]
    digest.update(value)  # type: ignore[attr-defined]


def directory_digest(root: str, max_files: int, max_bytes: int) -> str:
    if not stat.S_ISDIR(os.lstat(root).st_mode):
        raise SnapshotUnavailable('shared root is not a directory')
    digest = hashlib.sha256()
    count = used = visited = 0
    def unavailable(error: OSError) -> None:
        raise SnapshotUnavailable('shared directory could not be enumerated') from error

    for directory, subdirs, filenames, fd in os.fwalk(root, follow_symlinks=False, onerror=unavailable):
        subdirs.sort()
        visited += 1
        before = os.fstat(fd)
        for name in sorted([*subdirs, *filenames]):
            count += 1
            if count > max_files:
                raise SnapshotUnavailable('shared entry budget exceeded')
            relative = os.path.relpath(os.path.join(directory, name), root)
            _frame(digest, os.fsencode(relative))
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            _frame(digest, str(stat.S_IMODE(info.st_mode)).encode())
            if stat.S_ISLNK(info.st_mode):
                _frame(digest, b'link')
                _frame(digest, os.fsencode(os.readlink(name, dir_fd=fd)))
            elif stat.S_ISDIR(info.st_mode):
                _frame(digest, b'directory')
            elif stat.S_ISREG(info.st_mode):
                _frame(digest, b'file')
                file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(file_fd, 'rb') as stream:
                    first = os.fstat(stream.fileno())
                    if not stat.S_ISREG(first.st_mode):
                        raise SnapshotUnavailable('shared entry changed type')
                    content = hashlib.sha256()
                    length = 0
                    while chunk := stream.read(min(65536, max_bytes - used + 1)):
                        used += len(chunk)
                        length += len(chunk)
                        if used > max_bytes:
                            raise SnapshotUnavailable('shared byte budget exceeded')
                        content.update(chunk)
                    last = os.fstat(stream.fileno())
                    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
                    if length != first.st_size or any(getattr(first, k) != getattr(last, k) for k in fields):
                        raise SnapshotUnavailable('shared entry changed while reading')
                    if (first.st_dev, first.st_ino) != (info.st_dev, info.st_ino):
                        raise SnapshotUnavailable('shared entry replaced while opening')
                    _frame(digest, content.digest())
            else:
                raise SnapshotUnavailable('shared entry has unsupported type')
        after = os.fstat(fd)
        if (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
            raise SnapshotUnavailable('shared directory changed while reading')
    if not visited:
        raise SnapshotUnavailable('shared directory was not observed')
    return 'sha256:' + digest.hexdigest()


def snapshot(root: str, remote: str, max_files: int = 4096, max_bytes: int = 4 * 1024 * 1024) -> dict[str, str]:
    if max_files < 1 or max_bytes < 1:
        raise SnapshotUnavailable('invalid shared-surface bounds')
    try:
        files = directory_digest(root, max_files, max_bytes)
        refs = subprocess.run(['git', '--git-dir=' + remote, 'for-each-ref',
                               '--count=' + str(max_files + 1), '--format=%(refname) %(objectname)'],
                              capture_output=True, check=False, timeout=5)
        if refs.returncode or len(refs.stdout) > max_bytes or len(refs.stdout.splitlines()) > max_files:
            raise SnapshotUnavailable('fixture refs unavailable or over budget')
        return {'files': files, 'refs': 'sha256:' + hashlib.sha256(refs.stdout).hexdigest()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SnapshotUnavailable('shared-surface observation unavailable') from exc


if __name__ == '__main__':
    try:
        print(json.dumps(snapshot(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))))
    except (SnapshotUnavailable, ValueError, IndexError):
        print('shared-surface observation unavailable', file=sys.stderr)
        raise SystemExit(2) from None
