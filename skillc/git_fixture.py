"""Disposable, declared git state and attempt-bound observations (#275)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .trial import Experiment


class Refused(ValueError):
    """A named fixture boundary was not met."""


def _digest(data: bytes) -> str:
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def _environment(home: str) -> dict[str, str]:
    # Allowlist, rather than inheriting GIT_DIR, config injection, SSH or credentials.
    return {'PATH': os.defpath, 'LC_ALL': 'C', 'HOME': home,
            'XDG_CONFIG_HOME': home, 'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0',
            'GIT_ALLOW_PROTOCOL': 'file'}


def _git(args: list[str], cwd: Path, env_extra: dict[str, str] | None = None
         ) -> subprocess.CompletedProcess[bytes]:
    with tempfile.TemporaryDirectory(prefix='git-home-', dir=cwd.parent) as home:
        env = _environment(home)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
             '-c', 'commit.gpgsign=false', *args], cwd=cwd, env=env,
            capture_output=True, timeout=30, check=True)


def _path(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or str(path) != name
            or any(p in ('.', '..', '.git') for p in path.parts)
            or any(ord(c) < 32 for c in name) or '\\' in name):
        raise Refused('unsafe-path')
    return name


def _write(repo: Path, files: dict[str, Any]) -> None:
    for name, entry in files.items():
        dest = repo / _path(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(bytes.fromhex(entry['hex']))
        dest.chmod(0o755 if entry['executable'] else 0o644)


def _identity(entry: dict[str, Any]) -> dict[str, str]:
    return {'digest': _digest(bytes.fromhex(entry['hex'])),
            'mode': '100755' if entry['executable'] else '100644'}


@dataclass(frozen=True)
class BuildResult:
    root: Path
    repo: Path
    worktree: Path
    declaration: dict[str, Any]
    commits: tuple[str, ...]
    expected: dict[str, Any]


def build(declaration: dict[str, Any], root: Path) -> BuildResult:
    """Build only inside an existing empty disposable directory; never reuse state."""
    if root.is_symlink():
        raise Refused('linked-root')
    root = root.resolve()
    if not root.is_dir() or any(root.iterdir()):
        raise Refused('root-not-empty')
    d = json.loads(json.dumps(declaration))
    if set(d) != {'fixture_schema', 'commits', 'refs', 'staged', 'unstaged',
                  'untracked', 'ignored', 'stash', 'worktree'} or d['fixture_schema'] != 1:
        raise Refused('declaration-schema')
    if not d['commits']:
        raise Refused('empty-commits')
    for commit in d['commits']:
        if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+]0000', commit['date']):
            raise Refused('fixed-date-required')
    for files in [*(c['files'] for c in d['commits']), d['staged'], d['unstaged'],
                  d['untracked'], d['ignored'], d['stash']['staged'], d['stash']['unstaged']]:
        for name, entry in files.items():
            _path(name)
            bytes.fromhex(entry['hex'])
            if type(entry['executable']) is not bool:
                raise Refused('file-mode')
    name = _path(d['worktree']['name'])
    if '/' in name or name == 'repo':
        raise Refused('worktree-name')
    repo = root / 'repo'
    repo.mkdir()
    _git(['init', '--template=', '--initial-branch=main', '--object-format=sha1'], repo)
    commits = []
    for commit in d['commits']:
        _write(repo, commit['files'])
        _git(['add', '--all'], repo)
        _git(['commit', '--allow-empty', '-m', commit['message']], repo,
             {'GIT_AUTHOR_DATE': commit['date'], 'GIT_COMMITTER_DATE': commit['date']})
        commits.append(_git(['rev-parse', 'HEAD'], repo).stdout.decode().strip())
    for ref, index in d['refs'].items():
        if not ref.startswith('refs/'):
            raise Refused('ref-name')
        _git(['check-ref-format', ref], repo)
        _git(['update-ref', ref, commits[index]], repo)
    _write(repo, d['stash']['staged'])
    for path in d['stash']['staged']:
        _git(['add', '--', path], repo)
    _write(repo, d['stash']['unstaged'])
    _git(['stash', 'push', '-m', 'fixture-stash'], repo,
         {'GIT_AUTHOR_DATE': d['commits'][-1]['date'],
          'GIT_COMMITTER_DATE': d['commits'][-1]['date']})
    _write(repo, d['staged'])
    for path in d['staged']:
        _git(['add', '--', path], repo)
    _write(repo, d['unstaged'])
    _write(repo, d['untracked'])
    _write(repo, d['ignored'])
    if d['ignored']:
        (repo / '.gitignore').write_text(''.join('/' + p + '\n' for p in d['ignored']))
    worktree = root / name
    _git(['worktree', 'add', '--detach', str(worktree), commits[d['worktree']['commit']]], repo)
    expected: dict[str, Any] = {'head': commits[-1], 'refs': {
        'refs/heads/main': commits[-1], **{r: commits[i] for r, i in d['refs'].items()}}}
    expected['files'] = {category: dict(d[category]) for category in
                         ('staged', 'unstaged', 'untracked', 'ignored')}
    if d['ignored']:
        ignore_bytes = ''.join('/' + p + '\n' for p in d['ignored']).encode()
        expected['files']['untracked']['.gitignore'] = {
            'hex': ignore_bytes.hex(), 'executable': False}
    expected['refs']['refs/stash'] = _git(['rev-parse', 'refs/stash'], repo).stdout.decode().strip()
    return BuildResult(root, repo, worktree, d, tuple(commits), expected)


def leak_guard(facts: Any, *paths: Path) -> None:
    """Refuse owned absolute paths in keys as well as nested string values."""
    if isinstance(facts, str):
        if any(str(p.resolve()) in facts for p in paths):
            raise Refused('absolute-path-leak')
    elif isinstance(facts, dict):
        for key, value in facts.items():
            leak_guard(key, *paths)
            leak_guard(value, *paths)
    elif isinstance(facts, (tuple, list)):
        for value in facts:
            leak_guard(value, *paths)


def _fact(value: Any, expected: Any) -> dict[str, Any]:
    return {'status': 'satisfied' if value == expected else 'violated', 'value': value}


def capture(experiment: Experiment, attempt_id: str, repo: Path, *,
            expected: BuildResult, worktree: Path | None = None) -> dict[str, Any]:
    """Observe each category independently; expected identity is caller-owned."""
    experiment.trial_of(attempt_id)
    if repo.resolve() != expected.repo or (worktree is not None and
                                         worktree.resolve() != expected.worktree):
        raise Refused('wrong-repository-or-worktree')
    if (repo / '.git').is_symlink() or not (repo / '.git').is_dir():
        raise Refused('repository-shape')
    facts: dict[str, Any] = {'capture_schema': 1, 'attempt_id': attempt_id,
                             'repository': {'status': 'satisfied', 'value': 'fixture-repository',
                                            'gitdir_shape': 'directory'}}

    def observe(category: str, fn: Any) -> None:
        try:
            facts[category] = fn()
        except (subprocess.SubprocessError, OSError, ValueError):
            facts[category] = {'status': 'unknown', 'reason': 'observation-unavailable'}

    observe('head', lambda: _fact(_git(['rev-parse', 'HEAD'], repo).stdout.decode().strip(),
                                  expected.expected['head']))

    def refs() -> dict[str, Any]:
        rows = _git(['for-each-ref', '--format=%(refname) %(objectname)'], repo).stdout.decode()
        return _fact(dict(row.split(' ', 1) for row in rows.splitlines()), expected.expected['refs'])
    observe('refs', refs)

    def files(category: str) -> dict[str, Any]:
        status = b''
        indexed: dict[str, dict[str, str]] = {}
        if category in ('staged', 'unstaged'):
            status = _git(['status', '--porcelain=v2', '-z', '--untracked-files=all',
                           '--ignored'], repo).stdout
        if category == 'staged':
            index = _git(['ls-files', '--stage', '-z'], repo).stdout
            for row in index.split(b'\0'):
                if row:
                    meta, raw_path = row.split(b'\t', 1)
                    mode, oid, stage = meta.decode().split()
                    if stage != '0':
                        raise ValueError('unmerged-index')
                    indexed[raw_path.decode()] = {'mode': mode, 'digest': _digest(
                        _git(['cat-file', 'blob', oid], repo).stdout)}
        listed: set[str] = set()
        if category in ('untracked', 'ignored'):
            args = ['ls-files', '--others', '--exclude-standard', '-z']
            if category == 'ignored':
                args.insert(2, '--ignored')
            listed = set(_git(args, repo).stdout.decode().strip('\0').split('\0')) - {''}
        else:
            for row in status.split(b'\0'):
                if row.startswith(b'1 '):
                    parts = row.decode().split(' ', 8)
                    xy = parts[1]
                    if xy[0 if category == 'staged' else 1] != '.':
                        listed.add(parts[8])
        entries = {}
        for path in sorted(listed | set(expected.expected['files'][category])):
            try:
                dest = repo / _path(path)
                if dest.is_symlink():
                    raise ValueError('linked-file')
                value = indexed.get(path) if category == 'staged' else {
                    'digest': _digest(dest.read_bytes()),
                    'mode': '100755' if dest.stat().st_mode & 0o111 else '100644'}
                wanted = expected.expected['files'][category].get(path)
                entries[path] = _fact(value, _identity(wanted) if wanted else None)
                if path not in listed:
                    entries[path]['status'] = 'violated'
            except (OSError, ValueError):
                entries[path] = {'status': 'unknown', 'reason': 'file-unavailable'}
        return {'status': 'violated' if any(e['status'] == 'violated' for e in entries.values())
                else 'unknown' if any(e['status'] == 'unknown' for e in entries.values())
                else 'satisfied', 'files': entries}
    for category in ('staged', 'unstaged', 'untracked', 'ignored'):
        observe(category, lambda category=category: files(category))

    def stash() -> dict[str, Any]:
        ids = _git(['stash', 'list', '--format=%H'], repo).stdout.decode().splitlines()
        trees = {}
        for suffix in ('', '^2'):
            rows = _git(['ls-tree', '-r', '-z', 'refs/stash' + suffix], repo).stdout
            inventory = {}
            for row in rows.split(b'\0'):
                if row:
                    meta, path = row.split(b'\t', 1)
                    mode, _, oid = meta.decode().split()
                    inventory[path.decode()] = {'mode': mode, 'digest': _digest(
                        _git(['cat-file', 'blob', oid], repo).stdout)}
            trees['working' if not suffix else 'index'] = inventory
        ok = ids == [expected.expected['refs']['refs/stash']]
        for category, tree in (('staged', 'index'), ('unstaged', 'working')):
            for path, entry in expected.declaration['stash'][category].items():
                ok = ok and trees[tree].get(path) == _identity(entry)
        return {'status': 'satisfied' if ok else 'violated', 'present': bool(ids), 'trees': trees}
    observe('stash', stash)

    def linked() -> dict[str, Any]:
        assert worktree is not None
        pointer = worktree / '.git'
        if pointer.is_symlink():
            return {'status': 'violated', 'role': 'linked-worktree-of-fixture',
                    'gitdir_pointer_present': True, 'resolves': False}
        text = pointer.read_text()
        target = Path(text.removeprefix('gitdir: ').strip()).resolve()
        shaped = (text.startswith('gitdir: ') and target.parent == repo / '.git' / 'worktrees'
                  and target.is_dir())
        head = (_git(['rev-parse', 'HEAD'], worktree).stdout.decode().strip()
                if shaped else None)
        return {'status': 'satisfied' if shaped and head == expected.commits[
            expected.declaration['worktree']['commit']] else 'violated',
            'role': 'linked-worktree-of-fixture', 'gitdir_pointer_present': pointer.is_file(),
            'resolves': shaped, 'head': head}
    if worktree is not None:
        observe('worktree', linked)
    leak_guard(facts, expected.root, expected.repo, expected.worktree)
    facts['digest'] = _digest(json.dumps(facts, sort_keys=True, separators=(',', ':')).encode())
    experiment.record(attempt_id, 'git-fixture-captured', facts=facts)
    return facts
