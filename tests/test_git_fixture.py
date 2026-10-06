"""Synthetic disposable git controls, including mutations of their certifiers."""
from __future__ import annotations

import copy
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from skillc import git_fixture as g
from skillc import trial


def file(text: str, executable: bool = False) -> dict[str, Any]:
    return {'hex': text.encode().hex(), 'executable': executable}


def declaration() -> dict[str, Any]:
    return {'fixture_schema': 1, 'commits': [
        {'message': 'first', 'date': '2020-01-01T00:00:00+0000',
         'files': {'tracked': file('first'), 'script': file('run', True)}},
        {'message': 'second', 'date': '2020-01-02T00:00:00+0000',
         'files': {'tracked': file('second')}}],
        'refs': {'refs/heads/other': 0}, 'staged': {'added': file('index')},
        'unstaged': {'tracked': file('working')}, 'untracked': {'loose': file('loose', True)},
        'ignored': {'ignored': file('hidden')},
        'stash': {'staged': {'stashed': file('saved', True)},
                  'unstaged': {'tracked': file('stash-working')}},
        'worktree': {'name': 'sibling', 'commit': 0}}


def make_setup(tmp_path: Path) -> tuple[g.BuildResult, trial.Experiment, str]:
    root = tmp_path / 'fixture'
    root.mkdir()
    result = g.build(declaration(), root)
    store = trial.open_store(tmp_path / 'store', forbidden=[])
    experiment = trial.plan({'experiment': 'git-test', 'trials': [{
        'label': 'case', 'case': {'id': 'git', 'revision': '1'},
        'grader': {'id': 'git', 'revision': '1'}, 'subject': {'digest': 'sha256:5a'},
        'client': {'name': 'fake', 'version': '1'}, 'image': {'digest': 'sha256:1a'},
        'config': {'model': 'fake'}, 'attempts': 1}]}, store)
    _, attempt = next(experiment.attempts())
    return result, experiment, str(attempt['attempt_id'])


@pytest.fixture
def setup(tmp_path: Path) -> tuple[g.BuildResult, trial.Experiment, str]:
    return make_setup(tmp_path)


def capture(setup: tuple[g.BuildResult, trial.Experiment, str]) -> dict[str, Any]:
    result, experiment, attempt = setup
    return g.capture(experiment, attempt, result.repo, expected=result, worktree=result.worktree)


def test_round_trip(setup: tuple[g.BuildResult, trial.Experiment, str]) -> None:
    result, experiment, attempt = setup
    facts = capture(setup)
    for category in ('head', 'refs', 'staged', 'unstaged', 'untracked', 'ignored', 'stash', 'worktree'):
        assert facts[category]['status'] == 'satisfied'
    assert facts['refs']['value'] == result.expected['refs']
    for category in ('staged', 'unstaged', 'untracked', 'ignored'):
        for path, entry in result.declaration[category].items():
            assert facts[category]['files'][path]['value'] == g._identity(entry)
    assert facts['stash']['present']
    assert facts['stash']['trees']['index']['stashed'] == g._identity(file('saved', True))
    assert facts['stash']['trees']['working']['tracked'] == g._identity(file('stash-working'))
    assert facts['worktree']['role'] == 'linked-worktree-of-fixture'
    assert facts['worktree']['resolves'] is True
    assert experiment.events(attempt)[-1]['facts'] == facts
    g.leak_guard(facts, result.root)
    planted = copy.deepcopy(facts)
    planted['stash']['trees']['injected'] = str(result.root)
    with pytest.raises(g.Refused, match='absolute-path-leak'):
        g.leak_guard(planted, result.root)


def test_determinism_and_date_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def build(name: str) -> g.BuildResult:
        root = tmp_path / name
        root.mkdir()
        return g.build(declaration(), root)
    assert build('a').commits == build('b').commits
    original = g._git

    def wall_clock(args: list[str], cwd: Path, env_extra: dict[str, str] | None = None
                   ) -> subprocess.CompletedProcess[bytes]:
        if env_extra:
            now = datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%S+0000')
            env_extra = {'GIT_AUTHOR_DATE': now, 'GIT_COMMITTER_DATE': now}
        return original(args, cwd, env_extra)
    with monkeypatch.context() as mutation:
        mutation.setattr(g, '_git', wall_clock)
        first = build('c').commits
        time.sleep(1.1)
        second = build('d').commits
        with pytest.raises(AssertionError):
            assert first == second
        print('RED date mutation: identical-SHA assertion failed with wall-clock dates')
    assert build('e').commits == build('f').commits
    print('GREEN restored dates: identical commit SHAs')


def test_config_isolation_red_then_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / 'operator'
    real = Path.home().resolve()
    assert fake != real and fake not in real.parents and real not in fake.parents
    fake.mkdir()
    hooks = fake / 'hooks'
    hooks.mkdir()
    sentinel = fake / 'hook-fired'
    hook = hooks / 'pre-commit'
    hook.write_text(f'#!/bin/sh\ntouch "{sentinel}"\n')
    hook.chmod(0o755)
    (fake / '.gitconfig').write_text(f'[commit]\n gpgsign = true\n[core]\n hooksPath = {hooks}\n')
    monkeypatch.setenv('HOME', str(fake))
    def build(name: str) -> None:
        root = tmp_path / name
        root.mkdir()
        g.build(declaration(), root)
    build('isolated')
    assert not sentinel.exists()
    print('GREEN isolation: commit succeeded; hook sentinel absent')
    original = g._environment
    def broken(home: str) -> dict[str, str]:
        env = original(home)
        for key in ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM', 'HOME'):
            env.pop(key)
        env['HOME'] = os.environ['HOME']
        return env
    with monkeypatch.context() as mutation:
        mutation.setattr(g, '_environment', broken)
        build('unisolated')
        assert sentinel.exists()
        with pytest.raises(AssertionError):
            assert not sentinel.exists()
        print('RED isolation mutation: operator pre-commit hook sentinel created')
    sentinel.unlink()
    build('restored')
    assert not sentinel.exists()
    print('GREEN restored isolation: commit succeeded; hook sentinel absent')


def test_wrong_repo(setup: tuple[g.BuildResult, trial.Experiment, str], tmp_path: Path) -> None:
    root = tmp_path / 'other'
    root.mkdir()
    other = g.build(declaration(), root)
    result, experiment, attempt = setup
    with pytest.raises(g.Refused, match='wrong-repository'):
        g.capture(experiment, attempt, other.repo, expected=result)
    assert capture(setup)['head']['status'] == 'satisfied'


def test_omitted_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = g._git
    def omit(args: list[str], cwd: Path, env_extra: dict[str, str] | None = None
             ) -> subprocess.CompletedProcess[bytes]:
        if args == ['add', '--', 'added']:
            return subprocess.CompletedProcess(args, 0, b'', b'')
        return original(args, cwd, env_extra)
    # Reuse the fixture factory while the actual build's add call is mutated.
    with monkeypatch.context() as mutation:
        mutation.setattr(g, '_git', omit)
        state = make_setup(tmp_path)
    assert capture(state)['staged']['files']['added']['status'] == 'violated'
    g._git(['add', '--', 'added'], state[0].repo)
    assert capture(state)['staged']['files']['added']['status'] == 'satisfied'


def test_loss_mode_and_stale(setup: tuple[g.BuildResult, trial.Experiment, str]) -> None:
    result = setup[0]
    before = capture(setup)
    (result.repo / 'loose').unlink()
    assert capture(setup)['untracked']['files']['loose']['status'] == 'unknown'
    g._write(result.repo, result.declaration['untracked'])
    (result.repo / 'loose').chmod(0o644)
    assert capture(setup)['untracked']['files']['loose']['status'] == 'violated'
    g._write(result.repo, result.declaration['untracked'])
    assert capture(setup)['untracked']['status'] == 'satisfied'
    (result.repo / 'tracked').write_bytes(b'changed')
    after = capture(setup)
    assert before['unstaged']['files']['tracked']['value']['digest'] != after['unstaged']['files']['tracked']['value']['digest']
    assert after['unstaged']['files']['tracked']['status'] == 'violated'
    g._write(result.repo, result.declaration['unstaged'])
    assert capture(setup)['unstaged']['status'] == 'satisfied'


def test_partial_unavailable(setup: tuple[g.BuildResult, trial.Experiment, str], monkeypatch: pytest.MonkeyPatch) -> None:
    original = g._git
    def unavailable(args: list[str], cwd: Path, env_extra: dict[str, str] | None = None
                    ) -> subprocess.CompletedProcess[bytes]:
        if args[:2] == ['stash', 'list']:
            raise subprocess.CalledProcessError(1, args)
        return original(args, cwd, env_extra)
    with monkeypatch.context() as mutation:
        mutation.setattr(g, '_git', unavailable)
        facts = capture(setup)
        assert facts['stash']['status'] == 'unknown'
        assert all(facts[k]['status'] == 'satisfied' for k in
                   ('head', 'refs', 'staged', 'unstaged', 'untracked', 'ignored', 'worktree'))
    assert capture(setup)['stash']['status'] == 'satisfied'


@pytest.mark.parametrize(('field', 'value', 'reason'), [
    ('fixture_schema', 2, 'declaration-schema'),
    ('commits', [], 'empty-commits'),
    ('untracked', {'../escape': file('bad')}, 'unsafe-path'),
    ('untracked', {'bad': {'hex': '00', 'executable': 1}}, 'file-mode'),
    ('worktree', {'name': 'repo', 'commit': 0}, 'worktree-name'),
    ('refs', {'not-a-ref': 0}, 'ref-name'),
])
def test_declaration_refusals(tmp_path: Path, field: str, value: Any, reason: str) -> None:
    bad = declaration()
    bad[field] = value
    root = tmp_path / 'bad'
    root.mkdir()
    with pytest.raises(g.Refused, match=reason):
        g.build(bad, root)
    good = tmp_path / 'good'
    good.mkdir()
    assert len(g.build(declaration(), good).commits) == 2


def test_root_and_date_boundaries(tmp_path: Path) -> None:
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'owned-by-someone-else').write_text('keep')
    with pytest.raises(g.Refused, match='root-not-empty'):
        g.build(declaration(), root)
    assert (root / 'owned-by-someone-else').read_text() == 'keep'
    link = tmp_path / 'link'
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(g.Refused, match='linked-root'):
        g.build(declaration(), link)
    empty = tmp_path / 'empty'
    empty.mkdir()
    bad = declaration()
    bad['commits'][0]['date'] = 'now'
    with pytest.raises(g.Refused, match='fixed-date-required'):
        g.build(bad, empty)
    assert g.build(declaration(), empty).repo.is_dir()


def test_pointer_shape_and_repository_shape(setup: tuple[g.BuildResult, trial.Experiment, str]) -> None:
    result = setup[0]
    pointer = result.worktree / '.git'
    original = pointer.read_bytes()
    pointer.write_text('gitdir: /nonexistent-fixture\n')
    assert capture(setup)['worktree']['status'] == 'violated'
    pointer.write_bytes(original)
    assert capture(setup)['worktree']['status'] == 'satisfied'
    saved = result.repo / '.git-saved'
    (result.repo / '.git').rename(saved)
    with pytest.raises(g.Refused, match='repository-shape'):
        capture(setup)
    saved.rename(result.repo / '.git')
    assert capture(setup)['repository']['status'] == 'satisfied'


def test_index_failure_is_partial(setup: tuple[g.BuildResult, trial.Experiment, str], monkeypatch: pytest.MonkeyPatch) -> None:
    original = g._git
    def unavailable(args: list[str], cwd: Path, env_extra: dict[str, str] | None = None
                    ) -> subprocess.CompletedProcess[bytes]:
        if args[:2] == ['ls-files', '--stage']:
            raise subprocess.CalledProcessError(1, args)
        return original(args, cwd, env_extra)
    with monkeypatch.context() as mutation:
        mutation.setattr(g, '_git', unavailable)
        facts = capture(setup)
        assert facts['staged']['status'] == 'unknown'
        assert all(facts[k]['status'] == 'satisfied' for k in
                   ('head', 'refs', 'unstaged', 'untracked', 'ignored', 'stash', 'worktree'))
    assert capture(setup)['staged']['status'] == 'satisfied'


def test_unexpected_file_is_not_clean(setup: tuple[g.BuildResult, trial.Experiment, str]) -> None:
    result = setup[0]
    extra = result.repo / 'extra'
    extra.write_bytes(b'unplanned')
    assert capture(setup)['untracked']['files']['extra']['status'] == 'violated'
    extra.unlink()
    assert capture(setup)['untracked']['status'] == 'satisfied'


def test_no_remote_and_network_protocol_refused(setup: tuple[g.BuildResult, trial.Experiment, str]) -> None:
    """#275 item 3: build() never adds a remote, and GIT_ALLOW_PROTOCOL=file in
    the isolated environment refuses a network transport outright - not merely
    "no remote happens to be configured", but "one could not reach GitHub even
    if asked"."""
    result = setup[0]
    assert g._git(['remote'], result.repo).stdout == b''
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        g._git(['ls-remote', 'https://example.invalid/repo.git'], result.repo)
    assert b"transport 'https' not allowed" in excinfo.value.stderr
