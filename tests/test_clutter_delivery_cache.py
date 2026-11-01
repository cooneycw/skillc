"""Delivered products come from captured remote objects, never the local index."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_clutter_capture import git, inventory
from test_clutter_capture import namespace as namespace  # noqa: PLC0414

from skillc import clutter as c
from skillc import clutter_capture as capture
from skillc import git_snapshot as gs
from skillc.clutter_controller import Session, report_from_events

CONTROL = json.loads((Path(__file__).resolve().parents[1] / 'controls/clutter-inventory/delivery-cache.json').read_text())


@pytest.mark.parametrize('case', CONTROL['cases'])
def test_delivered_tree_and_cache_controls(namespace: tuple[Path, c.Policy, Path], case: str) -> None:
    root, original, proc = namespace
    raw = copy.deepcopy(original.data)
    raw['delivered'] = []
    raw['delivered_commit_roles'] = ['agent']
    raw['allowed_cache_directories'] = [CONTROL['cache_rule']]
    policy = c.parse_policy(raw)
    from skillc.clutter_delivery import capture_commit
    observer = inventory(root, policy, proc)
    before = observer.capture('before')
    repo = root / 'work/repo'
    (repo / 'nhl').mkdir()
    (repo / 'nhl/api.py').write_text('source\n')
    git(repo, 'add', 'nhl/api.py')
    git(repo, 'commit', '-qm', 'delivered source')
    git(repo, 'push', str(root / 'work/fixture.git'), 'main')
    remote = gs.GitDir(capture.BoundedTree(root), 'work/fixture.git')
    commit = remote.refs()['refs/heads/main']
    evidence = {'agent': capture_commit('agent', remote, commit)}
    cache = repo / 'nhl/__pycache__'
    cache.mkdir()
    (cache / 'api.pyc').write_bytes(b'bytecode remains enabled')
    if case == 'stray':
        (repo / 'leftover.txt').write_text('not delivered')
    elif case == 'different-bytes':
        (repo / 'nhl/api.py').write_text('uncommitted replacement')
    elif case == 'outside-checkout':
        (root / 'tmp/__pycache__').mkdir()
    elif case == 'too-deep':
        deep = repo / 'nhl/a/b/__pycache__'
        deep.mkdir(parents=True)
    elif case == 'too-many':
        (repo / '__pycache__').mkdir()
        (repo / 'nhl/other').mkdir()
        (repo / 'nhl/other/__pycache__').mkdir()
    elif case == 'extra-branch':
        git(repo, 'branch', 'stray')
    elif case == 'missing-capture':
        evidence = {}
    elif case == 'corrupt-capture':
        evidence['agent']['commit'] = '0' * 40
    after = observer.capture('after')
    report = c.classify(policy, before, after, delivered_captures=evidence)
    expected = 'CLEAN' if case == 'delivered' else 'UNKNOWN' if case in ('missing-capture', 'corrupt-capture') else 'NOT_CLEAN'
    assert report['status'] == expected, report
    if case == 'delivered':
        assert report['counts']['delivered'] == 2  # package directory and file
        assert report['delivered_commits']['agent']['commit'] == commit
        assert report['not_inspected'] == [{'surface': 'agent/workspace', 'path': '/work/repo/nhl/__pycache__',
                                          'reason': 'Declared cache directory; contents are not inspected.'}]
    elif expected == 'NOT_CLEAN':
        assert report['counts']['clutter'] > 0


@pytest.mark.parametrize('fault', ['healthy', 'blob', 'commit', 'missing-object'])
def test_retained_objects_rederive_delivery_and_reject_tampering(
        namespace: tuple[Path, c.Policy, Path], fault: str) -> None:
    from skillc.clutter_delivery import capture_commit, selectors

    root, _, _ = namespace
    remote = gs.GitDir(capture.BoundedTree(root), 'work/fixture.git')
    packet = capture_commit('agent', remote, remote.refs()['refs/heads/main'])
    if fault == 'blob':
        row = next(r for r in packet['objects'].values() if r['kind'] == 'blob')
        row['hex'] = b'corrupt bytes'.hex()
    elif fault == 'commit':
        packet['commit'] = '0' * 40
    elif fault == 'missing-object':
        del packet['objects'][packet['tree']]
    packet['capture_digest'] = c.digest({k: v for k, v in packet.items() if k != 'capture_digest'})
    if fault == 'healthy':
        items, receipt = selectors(packet, 'agent', '/work/repo')
        assert 'file:/work/repo/base.txt' in items and receipt['tree'] == packet['tree']
    else:
        with pytest.raises((ValueError, KeyError)):
            selectors(packet, 'agent', '/work/repo')


@pytest.mark.parametrize('protected', ['gitdir', 'coordination', 'shared', 'temp', 'remote'])
def test_cache_patterns_cannot_exclude_independent_scopes(
        namespace: tuple[Path, c.Policy, Path], protected: str) -> None:
    root, original, proc = namespace
    raw = copy.deepcopy(original.data)
    raw['allowed_cache_directories'] = [CONTROL['cache_rule']]
    path = '/work/repo/__pycache__'
    scope = raw['roles']['agent']
    if protected == 'gitdir':
        scope['gitdir'] = path + '/metadata'
    elif protected == 'coordination':
        scope['coordination']['registry'] = [path + '/registry.json']
    elif protected == 'shared':
        raw['shared_roots'] = [path + '/shared']
    elif protected == 'temp':
        scope['temp_roots'] = [path + '/temp']
    else:
        scope['remotes']['fixture'] = path + '/remote.git'
    policy = c.parse_policy(raw)
    (root / path.lstrip('/')).mkdir()
    row = capture.capture_role(policy, 'agent', root, proc_root=proc)['agent/workspace']
    assert not row.complete and row.error and 'overlap' in row.error


def test_session_persists_raw_objects_and_recovery_ignores_cached_verdict(
        namespace: tuple[Path, c.Policy, Path]) -> None:
    from skillc.clutter_delivery import capture_commit

    root, original, proc = namespace
    raw = copy.deepcopy(original.data)
    raw['delivered'] = []
    raw['delivered_commit_roles'] = ['agent']
    policy = c.parse_policy(raw)
    observer = inventory(root, policy, proc)
    session = Session(observer)
    session.setup()
    repo = root / 'work/repo'
    (repo / 'result.txt').write_text('delivered')
    git(repo, 'add', 'result.txt')
    git(repo, 'commit', '-qm', 'delivered')
    git(repo, 'push', str(root / 'work/fixture.git'), 'main')
    remote = gs.GitDir(capture.BoundedTree(root), 'work/fixture.git')
    packet = capture_commit('agent', remote, remote.refs()['refs/heads/main'])
    observer.delivered_reader = lambda: {'agent': packet}
    session.completion('agent')
    report = session.finish()
    assert report['status'] == 'CLEAN'
    # Recovery must recompute from retained object bytes, not a stale clean flag.
    report['status'] = 'NOT_CLEAN'
    objects: dict[str, bytes] = {}
    def store(data: bytes) -> str:
        import hashlib
        key = 'sha256:' + hashlib.sha256(data).hexdigest()
        objects[key] = data
        return key
    before_id = store(c.canonical(report['before']))
    def recover() -> dict[str, object]:
        report_id = store(c.canonical(report))
        events = [{'event': 'clutter-before', 'policy_digest': policy.identity, 'digest': before_id},
                  {'event': 'clutter-after', 'policy_digest': policy.identity,
                   'before_digest': before_id, 'digest': report_id}]
        return report_from_events(policy, events, objects.__getitem__)
    assert recover()['status'] == 'CLEAN'
    report['delivered_captures']['agent']['objects'][packet['commit']]['hex'] = '00'
    assert recover()['status'] == 'UNKNOWN'


@pytest.mark.parametrize('field,value', [
    ('surface', 'shared'), ('surface', []), ('name_pattern', '*'), ('name_pattern', '../cache'),
    ('max_depth', 0), ('max_depth', True), ('max_depth', 65),
    ('max_matches', 0), ('max_matches', True), ('max_matches', c.MAX_ITEMS + 1),
])
def test_cache_rule_refuses_unbounded_or_foreign_selectors(
        namespace: tuple[Path, c.Policy, Path], field: str, value: object) -> None:
    _, original, _ = namespace
    raw = copy.deepcopy(original.data)
    rule = copy.deepcopy(CONTROL['cache_rule'])
    rule[field] = value
    raw['allowed_cache_directories'] = [rule]
    with pytest.raises(c.Refused):
        c.parse_policy(raw)


def test_pattern_and_delivery_opt_in_are_bound_to_declaration_identity(
        namespace: tuple[Path, c.Policy, Path]) -> None:
    _, original, _ = namespace
    raw = copy.deepcopy(original.data)
    raw['allowed_cache_directories'] = [CONTROL['cache_rule']]
    first = c.parse_policy(raw)
    assert first.identity != original.identity
    raw['allowed_cache_directories'][0]['max_matches'] += 1
    assert c.parse_policy(raw).identity != first.identity
    raw['delivered_commit_roles'] = ['agent']
    assert c.parse_policy(raw).identity != first.identity
