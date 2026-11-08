"""Delivered products come from captured remote objects, never the local index."""
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
from skillc import git_snapshot as gs
from skillc.backend import Confirmation
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
    cache = repo / 'nhl/__pycache__'
    cache.mkdir()
    (cache / 'api.pyc').write_bytes(b'bytecode remains enabled')
    if case == 'stray':
        (repo / 'leftover.txt').write_text('not delivered')
    elif case == 'ignored-stray':
        (repo / 'ignored.log').write_text('ignored is not delivered')
    elif case in ('unpushed', 'local-index'):
        (repo / 'local-only.txt').write_text('not in final remote commit')
        git(repo, 'add', 'local-only.txt')
        if case == 'unpushed':
            git(repo, 'commit', '-qm', 'local only')
    elif case == 'cache-symlink':
        (repo / '__pycache__').symlink_to('/tmp', target_is_directory=True)
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
    after = observer.capture('after')
    from skillc.clutter_delivery import handoff_binding
    binding = handoff_binding(policy, before, after)
    evidence = {'agent': capture_commit('agent', remote, commit, binding=binding)}
    if case == 'missing-capture':
        evidence = {}
    elif case == 'corrupt-capture':
        evidence['agent']['commit'] = '0' * 40
    handoff = {'binding': binding, 'role_stops': {'agent': 'confirmed'},
               'helper_stop': 'confirmed', 'delivered_commits': {'agent': commit}}
    report = c.classify(policy, before, after, delivered_captures=evidence, delivered_handoff=handoff)
    expected = 'CLEAN' if case == 'delivered' else 'UNKNOWN' if case in ('missing-capture', 'corrupt-capture') else 'NOT_CLEAN'
    assert report['status'] == expected, report
    if case == 'delivered':
        assert report['counts']['delivered'] == 2  # package directory and file
        assert report['delivered_commits']['agent']['commit'] == commit
        assert report['not_inspected'] == [{'surface': 'agent/workspace', 'path': '/work/repo/nhl/__pycache__',
                                          'reason': 'Declared cache directory; contents are not inspected.'}]
    elif expected == 'NOT_CLEAN':
        assert report['counts']['clutter'] > 0
        required = {
            'stray': ('agent/workspace', 'file:/work/repo/leftover.txt'),
            'ignored-stray': ('agent/workspace', 'file:/work/repo/ignored.log'),
            'unpushed': ('agent/workspace', 'file:/work/repo/local-only.txt'),
            'local-index': ('agent/workspace', 'file:/work/repo/local-only.txt'),
            'cache-symlink': ('agent/workspace', 'symlink:/work/repo/__pycache__'),
            'different-bytes': ('agent/workspace', 'file:/work/repo/nhl/api.py'),
            'outside-checkout': ('agent/temp', 'directory:/tmp/__pycache__'),
            'too-deep': ('agent/workspace', 'directory:/work/repo/nhl/a/b/__pycache__'),
            'too-many': ('agent/workspace', 'directory:/work/repo/nhl/other/__pycache__'),
        }
        if case in required:
            assert required[case] in {(row['surface'], row['key']) for row in report['additions']['clutter']}


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


@pytest.mark.parametrize('protected', ['gitdir', 'coordination', 'shared', 'temp', 'remote', 'delivered-product', 'allowed-product'])
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
    elif protected == 'remote':
        scope['remotes']['fixture'] = path + '/remote.git'
    else:
        category = 'delivered' if protected == 'delivered-product' else 'declared_allowed'
        raw[category] = [{'surface': 'agent/workspace', 'key': 'file:' + path + '/product.txt'}]
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
    commit = remote.refs()['refs/heads/main']
    session.completion('agent')
    session.capture_after()
    packet = capture_commit('agent', remote, commit, binding=session.delivery_binding())
    report = session.finalize({'agent': packet}, delivered_commits={'agent': commit},
                              role_stops={'agent': Confirmation.CONFIRMED}, helper_stop=Confirmation.CONFIRMED)
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


SEMANTIC_CASES = json.loads((Path(__file__).resolve().parents[1] /
                            'controls/clutter-inventory/semantic-delivery.json').read_text())


@pytest.mark.parametrize('case', SEMANTIC_CASES, ids=lambda case: case['name'])
def test_semantic_delivered_project_verdict(
    namespace: tuple[Path, c.Policy, Path], case: dict[str, str],
) -> None:
    """Replay legacy APIs on main; hold the intended verdict fixed across versions.

    The compatibility dispatch supplies new opt-ins only when the classifier
    supports them. Main must reach classification using its original public
    policy/snapshot API, rather than fail on an unknown field or import.
    """
    import inspect

    root, original, proc = namespace
    name = case['name']
    supports_delivery = 'delivered_captures' in inspect.signature(c.classify).parameters
    raw = copy.deepcopy(original.data)
    raw['delivered'] = []
    raw['allowed_subtrees'] = [{'surface': 'agent/workspace', 'path': '/work/repo/.venv'}]
    # Separate the two positive semantic changes: exact cache allowance isolates
    # delivered-tree classification; exact product selectors isolate cache names.
    if name == 'delivered-tree':
        raw['allowed_subtrees'].append({'surface': 'agent/workspace',
                                        'path': '/work/repo/nhl/__pycache__'})
        if supports_delivery:
            raw['delivered_commit_roles'] = ['agent']
    else:
        raw['delivered'] = [{'surface': 'agent/workspace', 'key': key} for key in (
            'file:/work/repo/nhl/api.py',)]
        if supports_delivery:
            raw['allowed_cache_directories'] = [CONTROL['cache_rule']]
        elif name != 'cache-pattern':
            # Keep the negative twins independently meaningful on old main:
            # its exact-path allowance covers the healthy cache, never residue.
            raw['allowed_subtrees'].append({'surface': 'agent/workspace',
                                            'path': '/work/repo/nhl/__pycache__'})
    policy = c.parse_policy(raw)
    repo = root / 'work/repo'
    (repo / '.venv/bin').mkdir(parents=True)
    (repo / '.venv/bin/python').symlink_to('/unavailable-fixture-interpreter')
    if name != 'delivered-tree':
        (repo / 'nhl').mkdir()
    observer = inventory(root, policy, proc)
    before = observer.capture('before')
    (repo / 'nhl/__pycache__').mkdir(parents=True)
    (repo / 'nhl/api.py').write_text('def score(): return 1\n')
    (repo / 'nhl/__pycache__/api.cpython-312.pyc').write_bytes(b'generated bytecode')
    git(repo, 'add', 'nhl/api.py')
    git(repo, 'commit', '-qm', 'delivered NHL source')
    git(repo, 'push', str(root / 'work/fixture.git'), 'main')
    if name == 'undelivered-stray':
        (repo / 'leftover.txt').write_text('not delivered')
    elif name == 'out-of-bounds-cache':
        (repo / 'nhl/deep/deeper/__pycache__').mkdir(parents=True)
    after = observer.capture('after')
    options: dict[str, Any] = {}
    if name == 'delivered-tree' and supports_delivery:
        from skillc.clutter_delivery import capture_commit, handoff_binding

        remote = gs.GitDir(capture.BoundedTree(root), 'work/fixture.git')
        commit = remote.refs()['refs/heads/main']
        binding = handoff_binding(policy, before, after)
        options = {'delivered_captures': {'agent': capture_commit('agent', remote, commit, binding=binding)},
                   'delivered_handoff': {'binding': binding, 'role_stops': {'agent': 'confirmed'},
                                         'helper_stop': 'confirmed', 'delivered_commits': {'agent': commit}}}
    report = c.classify(policy, before, after, **options)
    print(json.dumps({'case': name, 'status': report['status'], 'counts': report['counts']}, sort_keys=True))
    assert report['status'] == case['expected'], report
    assert not report['unknown']
    if case['expected'] == 'CLEAN':
        assert report['counts']['delivered'] == (2 if name == 'delivered-tree' else 1)
    elif name == 'undelivered-stray':
        assert any(row['key'] == 'file:/work/repo/leftover.txt' for row in report['additions']['clutter'])
    else:
        assert any(row['key'] == 'directory:/work/repo/nhl/deep/deeper/__pycache__'
                   for row in report['additions']['clutter'])
    if name == 'cache-pattern':
        assert {'surface': 'agent/workspace', 'path': '/work/repo/nhl/__pycache__',
                'reason': 'Declared cache directory; contents are not inspected.'} in report['not_inspected']
