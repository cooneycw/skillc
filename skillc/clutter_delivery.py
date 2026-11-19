"""Retain and replay verified objects from a controller-held delivered remote.

The caller selects the exact independently captured delivered commit. This API
does not discover delivery from a role's HEAD, index, or unpushed tracked files.
Only controller custody authenticates the supplied capture; hashes bind bytes.
"""
from __future__ import annotations

import hashlib
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from . import git_snapshot as gs
from .clutter import MAX_BYTES, MAX_ITEMS, Policy, Refused, Snapshot, canonical, digest

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


def capture_commit(role: str, remote: gs.GitDir, commit: str, *,
                   binding: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Read exact remote objects without invoking Git or participant hooks."""
    if not isinstance(commit, str) or SHA.fullmatch(commit) is None:
        raise Refused('delivered commit must be an exact Git object identity')
    recording = _RecordingGit(remote.tree, remote.path)
    recording.retained = {}
    recording.check_plain()
    tree = recording.tree_of(commit)
    recording.commit_files(commit)
    packet = {'role': role, 'commit': commit, 'tree': tree, 'objects': recording.retained}
    if binding is not None:
        from .clutter import strict_json
        packet['binding'] = strict_json(canonical(binding))
    return {**packet, 'capture_digest': digest(packet)}


#: Git records one permission fact for a regular file: 100755 when the
#: owner-execute bit (S_IXUSR) is set, else 100644 (#727). Every other
#: permission bit comes from the umask that created the file, so a delivered
#: file matches on its bytes and that one bit. setuid, setgid and sticky are
#: never accepted: git cannot deliver them, so a file carrying one differs.
GIT_PERMISSION_BITS = 0o777
#: One candidate mode per combination of the 8 bits git does not record.
CANDIDATES_PER_FILE = 256
_MODES = {executable: tuple(m for m in range(GIT_PERMISSION_BITS + 1) if bool(m & stat.S_IXUSR) is executable)
          for executable in (False, True)}
if any(len(modes) != CANDIDATES_PER_FILE for modes in _MODES.values()):  # pragma: no cover - a constant
    raise RuntimeError("the git permission candidate set is not 256 modes per execute state")


@dataclass(frozen=True)
class Expected:
    """What a delivered key must look like on disk. A regular file is matched
    by its bytes and git's execute bit; anything else by its exact digest."""

    kind: str  # "file" or "exact"
    executable: bool
    content: str  # sha256 of the delivered bytes (files)
    exact: str  # the item digest (directories, symlinks)


def accepts(expected: Expected, observed: str) -> bool:
    """Whether a census item digest is the delivered item, as git sees it."""
    if expected.kind != 'file':
        return observed == expected.exact
    return any(digest({'mode': mode, 'digest': expected.content}) == observed for mode in _MODES[expected.executable])


def selectors(record: object, role: str, checkout: str) -> tuple[dict[str, Expected], dict[str, str]]:
    """Re-derive selectors from retained, hash-checked raw objects on recovery."""
    if (not isinstance(record, dict) or not {'role', 'commit', 'tree', 'objects', 'capture_digest'} <= set(record) <= {
                'role', 'commit', 'tree', 'objects', 'capture_digest', 'binding'}
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
    items: dict[str, Expected] = {}
    for path, (mode, data) in replay.commit_files(record['commit']).items():
        absolute = checkout + '/' + path
        if mode == '120000':
            exact = digest({'target': data.decode('utf-8'), 'mode': 0o777})
            items['symlink:' + absolute] = Expected('exact', False, '', exact)
        else:
            executable = bool(int(mode, 8) & stat.S_IXUSR)
            items['file:' + absolute] = Expected('file', executable, hashlib.sha256(data).hexdigest(), '')
        parts = path.split('/')[:-1]
        for index in range(1, len(parts) + 1):
            items['directory:' + checkout + '/' + '/'.join(parts[:index])] = Expected('exact', False, '', digest('directory'))
    return items, {key: record[key] for key in ('commit', 'tree', 'capture_digest')}


def handoff_binding(policy: Policy, before: Snapshot, after: Snapshot) -> dict[str, Any]:
    """Bind final delivery to this controller's already frozen live census."""
    if (before.phase != 'before' or after.phase != 'after'
            or not before.scope_id or before.scope_id != after.scope_id
            or before.policy_digest != policy.identity or after.policy_digest != policy.identity):
        raise Refused('delivery handoff snapshot binding disagrees')
    return {'schema_version': 1, 'scope_id': before.scope_id, 'policy_digest': policy.identity,
            'before_digest': digest(before.to_json()), 'after_digest': digest(after.to_json()),
            'delivered_commit_roles': list(policy.data.get('delivered_commit_roles', []))}


def validate_handoff(policy: Policy, before: Snapshot, after: Snapshot,
                     captures: object, handoff: object) -> Mapping[str, Any]:
    """Validate a controller-held stop/capture handoff; hashes are not authority.

    Callers must independently confirm stops and select the final delivered
    commit from held capture. Production wiring/custody remains #623/#620.
    A participant-provided packet or stop assertion is never such evidence.
    """
    roles = set(policy.data.get('delivered_commit_roles', []))
    if (not isinstance(handoff, dict)
            or set(handoff) != {'binding', 'role_stops', 'helper_stop', 'delivered_commits'}
            or canonical(handoff['binding']) != canonical(handoff_binding(policy, before, after))
            or not isinstance(handoff['role_stops'], dict)
            or set(handoff['role_stops']) != set(policy.roles)
            or any(value != 'confirmed' for value in handoff['role_stops'].values())
            or handoff['helper_stop'] != 'confirmed'
            or not isinstance(handoff['delivered_commits'], dict)
            or set(handoff['delivered_commits']) != roles
            or not isinstance(captures, dict) or set(captures) != roles):
        raise Refused('final delivery requires bound captures and confirmed role/helper stops')
    for role in roles:
        record = captures[role]
        commit = handoff['delivered_commits'][role]
        if (not isinstance(commit, str) or SHA.fullmatch(commit) is None
                or not isinstance(record, dict) or record.get('role') != role
                or record.get('commit') != commit
                or canonical(record.get('binding')) != canonical(handoff['binding'])):
            raise Refused('final delivered capture is stale, wrong-role or unbound')
    return captures
