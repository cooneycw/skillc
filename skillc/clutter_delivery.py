"""Retain and replay verified objects from a controller-held delivered remote.

The caller selects the exact independently captured delivered commit. This API
does not discover delivery from a role's HEAD, index, or unpushed tracked files.
Only controller custody authenticates the supplied capture; hashes bind bytes.
"""
from __future__ import annotations

import hashlib
import re
import stat
from typing import Any, cast

from . import git_snapshot as gs
from .clutter import MAX_BYTES, MAX_ITEMS, Refused, canonical, digest

SHA = re.compile(r'[0-9a-f]{40}\Z')


class _RecordingGit(gs.GitDir):
    retained: dict[str, Any]

    def object(self, sha: str) -> tuple[str, bytes]:
        kind, payload = super().object(sha)
        self.retained[sha] = {'kind': kind, 'hex': payload.hex()}
        if len(self.retained) > MAX_ITEMS or len(canonical(self.retained)) > MAX_BYTES:
            raise gs.Unreadable('delivered object capture exceeds inventory bounds')
        return kind, payload


class _ReplayGit(gs.GitDir):
    retained: dict[str, Any]

    def object(self, sha: str) -> tuple[str, bytes]:
        row = self.retained[sha]
        if not isinstance(row, dict) or set(row) != {'kind', 'hex'}:
            raise Refused('malformed retained Git object')
        kind = row['kind']
        if kind not in ('commit', 'tree', 'blob', 'tag') or not isinstance(row['hex'], str):
            raise Refused('malformed retained Git object content')
        payload = bytes.fromhex(row['hex'])
        framed = kind.encode() + b' ' + str(len(payload)).encode() + b'\0' + payload
        if hashlib.sha1(framed).hexdigest() != sha:
            raise Refused('retained Git object disagrees with its identity')
        return kind, payload


def capture_commit(role: str, remote: gs.GitDir, commit: str) -> dict[str, Any]:
    """Read exact remote objects without invoking Git or participant hooks."""
    if not isinstance(commit, str) or SHA.fullmatch(commit) is None:
        raise Refused('delivered commit must be an exact Git object identity')
    recording = _RecordingGit(remote.tree, remote.path)
    recording.retained = {}
    recording.check_plain()
    tree = recording.tree_of(commit)
    recording.commit_files(commit)
    packet = {'role': role, 'commit': commit, 'tree': tree, 'objects': recording.retained}
    return {**packet, 'capture_digest': digest(packet)}


def selectors(record: object, role: str, checkout: str) -> tuple[dict[str, str], dict[str, str]]:
    """Re-derive selectors from retained, hash-checked raw objects on recovery."""
    if (not isinstance(record, dict) or set(record) != {'role', 'commit', 'tree', 'objects', 'capture_digest'}
            or record['role'] != role or not isinstance(record['commit'], str)
            or SHA.fullmatch(record['commit']) is None or not isinstance(record['objects'], dict)
            or not 1 <= len(record['objects']) <= MAX_ITEMS or len(canonical(record)) > MAX_BYTES):
        raise Refused('delivered capture is missing, malformed or over budget')
    packet = {k: v for k, v in record.items() if k != 'capture_digest'}
    if record['capture_digest'] != digest(packet):
        raise Refused('delivered capture digest disagrees')
    # All object reads are overridden; recovery never reads a live filesystem.
    replay = _ReplayGit(cast(gs.SafeTree, None), '')
    replay.retained = record['objects']
    tree = replay.tree_of(record['commit'])
    if tree != record['tree']:
        raise Refused('delivered tree disagrees with captured commit')
    items: dict[str, str] = {}
    for path, (mode, data) in replay.commit_files(record['commit']).items():
        absolute = checkout + '/' + path
        if mode == '120000':
            value = {'target': data.decode('utf-8'), 'mode': 0o777}
            key = 'symlink:' + absolute
        else:
            value = {'mode': stat.S_IMODE(int(mode, 8)), 'digest': hashlib.sha256(data).hexdigest()}
            key = 'file:' + absolute
        items[key] = digest(value)
        parts = path.split('/')[:-1]
        for index in range(1, len(parts) + 1):
            items['directory:' + checkout + '/' + '/'.join(parts[:index])] = digest('directory')
    return items, {key: record[key] for key in ('commit', 'tree', 'capture_digest')}
