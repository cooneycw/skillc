"""VM declaration binding and reviewed-install content matching (#630).

This proves binding and match only, NOT physical VM provenance. Observation
objects belong to a trusted controller/operator adapter, never participant JSON.
No host probing, deployment, authorization, credential handling or launch occurs
here. Calibration's existing approval gate remains the only authorization path.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .git_snapshot import SafeTree, Unreadable

VM_KEYS = frozenset({'id', 'host_key_fingerprint', 'base_image_digest', 'kernel', 'docker_version'})
REQUIRED_IMPORTS = {
    'skillc': 'skillc/__init__.py',
    'skillc.calibration': 'skillc/calibration.py',
    'skillc.vm_identity': 'skillc/vm_identity.py',
    'skillc.fixture_service': 'skillc/fixture_service.py',
    'fixture_shim': 'docker/fixture-service/skillc-gh-shim.py',
}
# Closed bookkeeping exclusions, NOT gitignore rules or caller-supplied globs.
# Only actual directories qualify (the worktree .git metadata can be a file).
ROOT_EXCLUSIONS = frozenset({'.git', '.venv', '.pytest_cache', '.mypy_cache', '.ruff_cache'})
CACHE_DIRECTORY = '__pycache__'
MAX_FILES = 20_000
MAX_BYTES = 64 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_DEPTH = 32
_DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
_REVISION = re.compile(r'[0-9a-f]{40}')


class IdentityRefused(ValueError):
    """VM binding or installation evidence is absent, invalid or different."""


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise IdentityRefused('execution_environment: ' + reason)


def _object(value: object, keys: set[str] | frozenset[str], name: str) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == keys, name + ' fields are incomplete or unknown')
    assert isinstance(value, dict)
    return value


def _text(value: object) -> bool:
    return (isinstance(value, str) and bool(value) and value.strip() == value
            and value != 'UNKNOWN' and len(value) <= 512 and not any(ord(c) < 32 for c in value))


def _path(value: str) -> bool:
    parts = PurePosixPath(value).parts
    return (_text(value) and bool(parts) and not value.startswith('/') and str(PurePosixPath(value)) == value
            and all(p not in ('.', '..') for p in parts) and '\\' not in value and '\0' not in value
            and parts[0] not in ROOT_EXCLUSIONS and CACHE_DIRECTORY not in parts)


def validate(raw: object) -> dict[str, Any]:
    """Validate shape only; canonical copied data contains no live paths."""
    env = _object(raw, {'version', 'kind', 'vm', 'skillc', 'window'}, 'environment')
    _require(type(env['version']) is int and env['version'] == 1
             and env['kind'] == 'dedicated-vm', 'unsupported version or kind')
    vm = _object(env['vm'], VM_KEYS, 'vm')
    _require(all(_text(v) for v in vm.values()), 'vm identity must be fully recorded')
    _require(_DIGEST.fullmatch(vm['base_image_digest']), 'invalid VM base image digest')
    _require(re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', vm['host_key_fingerprint']),
             'invalid host key fingerprint')
    install = _object(env['skillc'], {'revision', 'install_manifest'}, 'skillc')
    _require(isinstance(install['revision'], str) and _REVISION.fullmatch(install['revision']),
             'invalid reviewed revision')
    manifest = install['install_manifest']
    _require(isinstance(manifest, dict) and 0 < len(manifest) <= MAX_FILES, 'empty or oversized install_manifest')
    total = 0
    for path, row in manifest.items():
        _require(isinstance(path, str) and _path(path), 'unsafe or excluded manifest path')
        row = _object(row, {'mode', 'bytes', 'sha256'}, 'manifest entry')
        _require(type(row['mode']) is int and row['mode'] in (0o644, 0o755), 'invalid install mode')
        _require(type(row['bytes']) is int and 0 <= row['bytes'] <= MAX_FILE, 'invalid install size')
        _require(isinstance(row['sha256'], str) and _DIGEST.fullmatch(row['sha256']), 'invalid content digest')
        total += row['bytes']
    _require(total <= MAX_BYTES and set(REQUIRED_IMPORTS.values()) <= set(manifest),
             'incomplete or oversized runtime installation')
    window = _object(env['window'], {'id', 'starts_at', 'ends_at'}, 'window')
    _require(all(_text(v) for v in window.values()), 'invalid window')
    try:
        start, end = (datetime.fromisoformat(window[key])
                      for key in ('starts_at', 'ends_at'))
        _require(start.utcoffset() is not None and end.utcoffset() is not None and start < end,
                 'window needs ordered timezone-aware bounds')
    except (ValueError, TypeError) as exc:
        raise IdentityRefused('execution_environment: invalid window bounds') from exc
    # Copy to keep caller-owned mutable dictionaries out of retained records.
    return json.loads(json.dumps(env))  # type: ignore[no-any-return]


@dataclass(frozen=True)
class Observation:
    """Trusted adapter facts; no defaults and no automatic host observer."""

    vm: Mapping[str, object]
    revision: str
    install_root: Path
    imports: Mapping[str, Path]


def install_manifest(root: Path) -> dict[str, Any]:
    """Read the complete bounded installation without following links.

    Root bookkeeping directories and __pycache__ directories are excluded by
    name only. Symlinks, special files and masquerading excluded files refuse.
    Required imported modules must still name reviewed source, never cache/venv.
    """
    try:
        tree = SafeTree(root)
        entries: dict[str, Any] = {}

        def walk(rel: str, depth: int) -> None:
            _require(depth <= MAX_DEPTH, 'install depth exceeded')
            for name, kind in tree.listdir(rel):
                path = rel + '/' + name if rel else name
                excluded = (not rel and name in ROOT_EXCLUSIONS) or name == CACHE_DIRECTORY
                if excluded:
                    _require(kind == 'dir' or (not rel and name == '.git' and kind == 'file'),
                             'excluded entry is not bookkeeping')
                    continue
                if kind == 'dir':
                    walk(path, depth + 1)
                else:
                    _require(kind == 'file' and len(entries) < MAX_FILES, 'unsupported or oversized install')
                    data, mode = tree.read(path, MAX_FILE)
                    _require(tree.bytes_read <= MAX_BYTES, 'install byte bound exceeded')
                    entries[path] = {'mode': stat.S_IMODE(mode), 'bytes': len(data),
                                     'sha256': 'sha256:' + hashlib.sha256(data).hexdigest()}

        walk('', 0)
        _require(entries, 'installation is empty')
        return entries
    except (OSError, Unreadable, RecursionError) as exc:
        # Never echo local paths or content from IO exception text.
        raise IdentityRefused('execution_environment: installation unreadable') from exc


def verify(raw: object, observed: Observation | None) -> dict[str, Any]:
    """Match observed identity, complete install bytes and required import origins.

    No approval is granted here. The returned record belongs inside the
    protected controller evidence; public summaries must omit host identity.
    """
    env = validate(raw)
    _require(isinstance(observed, Observation), 'VM/install observation is required')
    assert observed is not None
    _require(dict(observed.vm) == env['vm'], 'observed VM identity differs')
    _require(observed.revision == env['skillc']['revision'], 'observed revision differs')
    expected = env['skillc']['install_manifest']
    current = install_manifest(observed.install_root)
    _require(current == expected, 'installed population, modes or content differ')
    _require(set(observed.imports) == set(REQUIRED_IMPORTS), 'required import observations are incomplete')
    try:
        root = observed.install_root.resolve(strict=True)
        for module, rel in REQUIRED_IMPORTS.items():
            origin = observed.imports[module]
            _require(origin.is_absolute() and origin == root / rel and origin.resolve(strict=True) == root / rel,
                     'import origin differs from reviewed installation')
    except (OSError, RuntimeError) as exc:
        raise IdentityRefused('execution_environment: import origin unreadable') from exc
    # Re-read after origins to refuse ordinary concurrent install changes.
    _require(install_manifest(observed.install_root) == current, 'installation changed during verification')
    encoded = json.dumps(expected, sort_keys=True, separators=(',', ':')).encode()
    return {'version': 1, 'scope': 'binding-and-install-match-only', 'status': 'MATCH',
            'vm': env['vm'], 'skillc_revision': observed.revision, 'window': env['window'],
            'install_manifest_digest': 'sha256:' + hashlib.sha256(encoded).hexdigest()}
