"""#619 realistic project controls: exclusions are explicit and cannot hide Git/state."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from test_clutter_capture import git, inventory
from test_clutter_capture import namespace as namespace  # noqa: PLC0414

from skillc import clutter as c
from skillc import clutter_capture as capture

CASES = json.loads((Path(__file__).resolve().parents[1] / 'controls/clutter-inventory/realistic.json').read_text())


def assert_realistic_population(value: dict[str, Any]) -> None:
    assert value.get('not_hideable') == ['worktree', 'branch', 'wave-state']
    roots = value.get('allowed_subtrees', [])
    assert len(roots) == 2
    assert {row['path'] for row in roots} == {'/work/repo/.venv', '/work/repo/__pycache__'}


def test_realistic_control_population_refuses_the_committed_empty_case() -> None:
    assert_realistic_population(CASES)
    missing = json.loads((Path(__file__).resolve().parents[1] / 'controls/clutter-inventory/missing-controls.json').read_text())
    with pytest.raises(AssertionError):
        assert_realistic_population(missing)


def realistic(policy: c.Policy) -> c.Policy:
    raw = copy.deepcopy(policy.data)
    raw['allowed_subtrees'] = CASES['allowed_subtrees']
    return c.parse_policy(raw)


def plant_project(root: Path) -> None:
    repo = root / 'work/repo'
    (repo / '.venv/bin').mkdir(parents=True)
    (repo / '.venv/bin/python').symlink_to('/unavailable-fixture-interpreter')
    (repo / '__pycache__').mkdir()
    (repo / '__pycache__/fixture.pyc').write_bytes(b'generated fixture cache')
    (repo / 'result.txt').write_text('delivered')


@pytest.mark.parametrize('outside', [False, True])
def test_realistic_environment_keeps_outside_clutter_visible(
        namespace: tuple[Path, c.Policy, Path], outside: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    root, original, proc = namespace
    policy = realistic(original)
    observer = inventory(root, policy, proc)
    before = observer.capture('before')
    plant_project(root)
    # An unreadable/special item INSIDE an allowance must not get visited.
    (root / 'work/repo/.venv/not-inspected').write_text('not a delivered item')
    if outside:
        (root / 'work/repo/task-leftover').write_text('clutter outside allowance')
    original_list = capture.BoundedTree.listdir

    def listdir(tree: capture.BoundedTree, rel: str) -> list[tuple[str, str]]:
        assert rel not in ('work/repo/.venv', 'work/repo/__pycache__'), 'allowed subtree was walked'
        return original_list(tree, rel)
    monkeypatch.setattr(capture.BoundedTree, 'listdir', listdir)
    report = c.classify(policy, before, observer.capture('after'))
    assert report['status'] == ('NOT_CLEAN' if outside else 'CLEAN'), report
    assert not report['unknown']
    assert report['counts']['delivered'] == 1
    if outside:
        assert any(row['key'] == 'file:/work/repo/task-leftover' for row in report['additions']['clutter'])
    assert {(row['surface'], row['path']) for row in report['not_inspected']} == {
        (row['surface'], row['path']) for row in CASES['allowed_subtrees']}
    assert all('not inspected' in row['reason'] for row in report['not_inspected'])
    assert all('not-inspected' not in row['key'] for items in report['additions'].values() for row in items)


def test_symlink_is_an_item_without_following_or_losing_the_delivered_product(
        namespace: tuple[Path, c.Policy, Path]) -> None:
    root, policy, proc = namespace
    observer = inventory(root, policy, proc)
    before = observer.capture('before')
    (root / 'work/repo/result.txt').write_text('delivered')
    (root / 'work/repo/interpreter').symlink_to('/unreadable/outside/target')
    report = c.classify(policy, before, observer.capture('after'))
    assert report['status'] == 'NOT_CLEAN' and not report['unknown'], report
    assert report['counts']['delivered'] == 1
    assert report['additions']['clutter'] == [{
        'surface': 'agent/workspace', 'key': 'symlink:/work/repo/interpreter',
        'value': c.digest({'target': '/unreadable/outside/target', 'mode': 0o777})}]


@pytest.mark.parametrize('leftover', CASES['not_hideable'])
def test_allowances_cannot_hide_workflow_leftovers(namespace: tuple[Path, c.Policy, Path], leftover: str) -> None:
    root, original, proc = namespace
    policy = realistic(original)
    observer = inventory(root, policy, proc)
    before = observer.capture('before')
    plant_project(root)
    repo = root / 'work/repo'
    if leftover == 'worktree':
        # Workspace enumeration skips .venv, but the independent registration
        # census must still see the worktree and its branch beneath it.
        git(repo, 'worktree', 'add', '-qb', 'stray-worktree', str(repo / '.venv/stray'))
        expected = 'agent/worktrees'
    elif leftover == 'branch':
        git(repo, 'branch', 'stray-branch')
        expected = 'agent/local-branches'
    else:
        (root / 'shared/stray-wave-state').write_text('unretired')
        expected = 'shared'
    report = c.classify(policy, before, observer.capture('after'))
    assert report['status'] == 'NOT_CLEAN', report
    assert any(row['surface'] == expected for row in report['additions']['clutter'])


@pytest.mark.parametrize('protected', ['gitdir', 'remote', 'cpp', 'shared', 'temp'])
def test_allowances_cannot_exclude_independent_state_scopes(namespace: tuple[Path, c.Policy, Path], protected: str) -> None:
    _, original, _ = namespace
    raw = copy.deepcopy(original.data)
    path = '/work/repo/.venv'
    raw['allowed_subtrees'] = [{'surface': 'agent/workspace', 'path': path}]
    scope = raw['roles']['agent']
    if protected == 'gitdir':
        scope['gitdir'] = path + '/metadata'
    elif protected == 'remote':
        scope['remotes']['fixture'] = path + '/fixture.git'
    elif protected == 'cpp':
        scope['cpp']['registry'] = [path + '/wave-state.json']
    elif protected == 'shared':
        raw['shared_roots'] = [path + '/shared']
    else:
        scope['temp_roots'] = [path + '/tmp']
    with pytest.raises(c.Refused, match='overlap'):
        c.parse_policy(raw)


@pytest.mark.parametrize('fault', ['whole-workspace', 'cpp-surface', 'git-surface', 'duplicate', 'overlapping', 'product'])
def test_subtree_selector_is_bounded_and_cannot_be_a_general_clutter_exemption(
        namespace: tuple[Path, c.Policy, Path], fault: str) -> None:
    _, original, _ = namespace
    raw: dict[str, Any] = copy.deepcopy(original.data)
    rows = [{'surface': 'agent/workspace', 'path': '/work/repo/.venv'}]
    raw['allowed_subtrees'] = rows
    if fault == 'whole-workspace':
        rows[0]['path'] = '/work/repo'
    elif fault in ('cpp-surface', 'git-surface'):
        rows[0]['surface'] = 'agent/cpp-registry' if fault == 'cpp-surface' else 'agent/worktrees'
    elif fault == 'product':
        rows[0]['path'] = '/work/repo/result.txt'
    else:
        rows.append({'surface': 'agent/workspace', 'path': '/work/repo/.venv' + ('/nested' if fault == 'overlapping' else '')})
    with pytest.raises(c.Refused):
        c.parse_policy(raw)


def test_subtree_list_is_part_of_the_common_policy_identity(namespace: tuple[Path, c.Policy, Path]) -> None:
    _, original, _ = namespace
    policy = realistic(original)
    assert policy.identity != original.identity
    changed = copy.deepcopy(policy.data)
    changed['allowed_subtrees'].pop()
    assert c.parse_policy(changed).identity != policy.identity
