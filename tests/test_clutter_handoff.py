"""Freeze the live census, then bind final delivery after confirmed writer stop."""
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
from skillc.clutter_delivery import capture_commit

CONTROLS = json.loads((Path(__file__).resolve().parents[1] /
                       'controls/clutter-inventory/handoff.json').read_text())


def prepared(namespace: tuple[Path, c.Policy, Path]) -> tuple[Session, gs.GitDir, str]:
    root, original, proc = namespace
    raw = copy.deepcopy(original.data)
    raw['delivered'] = []
    raw['delivered_commit_roles'] = ['agent']
    session = Session(inventory(root, c.parse_policy(raw), proc))
    session.setup()
    repo = root / 'work/repo'
    (repo / 'result.txt').write_text('delivered')
    git(repo, 'add', 'result.txt')
    git(repo, 'commit', '-qm', 'delivery')
    git(repo, 'push', str(root / 'work/fixture.git'), 'main')
    remote = gs.GitDir(capture.BoundedTree(root), 'work/fixture.git')
    session.completion('agent')
    return session, remote, remote.refs()['refs/heads/main']


def test_one_phase_reader_cannot_authorize_unbound_delivery(
    namespace: tuple[Path, c.Policy, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, remote, commit = prepared(namespace)
    calls: list[str] = []
    def read() -> dict[str, Any]:
        calls.append('called')
        return {'agent': capture_commit('agent', remote, commit)}
    # A one-phase reader cannot establish post-stop delivered-capture custody.
    monkeypatch.setattr(session.inventory, 'delivered_reader', read, raising=False)
    assert session.finish()['status'] == 'UNKNOWN'
    assert not calls


@pytest.mark.parametrize('case', CONTROLS, ids=lambda case: case['name'])
def test_frozen_census_and_final_delivery_handoff(
    namespace: tuple[Path, c.Policy, Path], case: dict[str, str],
) -> None:
    session, remote, commit = prepared(namespace)
    observer = session.inventory
    read_role = observer.role_readers['agent']
    survivor = case['name'] == 'pre-stop-survivor'
    def live_role() -> dict[str, c.Surface]:
        rows = dict(read_role())
        if survivor:
            rows['agent/processes'] = c.Surface({'pid:234:567': 'watcher'})
        return rows
    observer.role_readers['agent'] = live_role
    returned_after = session.capture_after()
    binding = session.delivery_binding()
    captures = {'agent': capture_commit('agent', remote, commit, binding=binding)}
    stops = {'agent': Confirmation.CONFIRMED}
    helper = Confirmation.CONFIRMED
    expected_commits = {'agent': commit}
    # Shutdown removes the watcher and the original readers become unavailable.
    # Finalize must never re-observe that now-clean or inaccessible namespace.
    returned_items = returned_after.surfaces['agent/processes'].items
    assert isinstance(returned_items, dict)
    returned_items.clear()
    assert session.before is not None
    assert isinstance(session.before.surfaces, dict)
    session.before.surfaces.clear()
    observer.role_readers['agent'] = lambda: pytest.fail('recaptured after stop')
    name = case['name']
    if name == 'missing-capture':
        captures = {}
    elif name == 'unbound-capture':
        captures = {'agent': capture_commit('agent', remote, commit)}
    elif name == 'stale-session':
        stale = {**binding, 'scope_id': 'another-session'}
        captures = {'agent': capture_commit('agent', remote, commit, binding=stale)}
    elif name == 'malformed-binding':
        malformed = {**binding, 'schema_version': True}
        captures = {'agent': capture_commit('agent', remote, commit, binding=malformed)}
    elif name == 'wrong-role':
        captures = {'agent': capture_commit('foreign', remote, commit, binding=binding)}
    elif name == 'stale-commit':
        expected_commits['agent'] = '0' * 40
    elif name == 'role-not-stopped':
        stops['agent'] = Confirmation.UNKNOWN
    elif name == 'helper-not-stopped':
        helper = Confirmation.UNKNOWN
    elif name == 'missing-stop':
        stops = {}
    elif name == 'extra-role':
        captures['foreign'] = captures['agent']
    report = session.finalize(captures, delivered_commits=expected_commits,
                              role_stops=stops, helper_stop=helper)
    assert report['status'] == case['expected'], report
    if survivor:
        assert report['additions']['clutter'] == [
            {'surface': 'agent/processes', 'key': 'pid:234:567', 'value': 'watcher'}]
    # Replay from immutable object bytes; a cached verdict supplies no authority.
    report['status'], report['clean'] = 'CLEAN', True
    objects: dict[str, bytes] = {}
    def store(data: bytes) -> str:
        key = c.digest(json.loads(data))
        # Object store identity is a hash of exact canonical bytes.
        objects[key] = data
        return key
    before_key = store(c.canonical(report['before']))
    report_key = store(c.canonical(report))
    events = [{'event': 'clutter-before', 'policy_digest': observer.policy.identity, 'digest': before_key},
              {'event': 'clutter-after', 'policy_digest': observer.policy.identity,
               'before_digest': before_key, 'digest': report_key}]
    assert report_from_events(observer.policy, events, objects.__getitem__)['status'] == case['expected']
    with pytest.raises(ValueError):
        session.capture_after()
    with pytest.raises(ValueError):
        session.finalize(captures, delivered_commits=expected_commits,
                         role_stops=stops, helper_stop=helper)


@pytest.mark.parametrize('stale', [False, True], ids=['fresh-session', 'previous-session'])
def test_reused_inventory_requires_a_fresh_session_binding(
    namespace: tuple[Path, c.Policy, Path], stale: bool,
) -> None:
    root, original, proc = namespace
    raw = copy.deepcopy(original.data)
    raw['delivered_commit_roles'] = ['agent']
    observer = inventory(root, c.parse_policy(raw), proc)
    first, second = Session(observer), Session(observer)
    for session in (first, second):
        session.setup()
        session.completion('agent')
        session.capture_after()
    remote = gs.GitDir(capture.BoundedTree(root), 'work/fixture.git')
    commit = remote.refs()['refs/heads/main']
    binding = first.delivery_binding() if stale else second.delivery_binding()
    packet = capture_commit('agent', remote, commit, binding=binding)
    report = second.finalize({'agent': packet}, delivered_commits={'agent': commit},
                             role_stops={'agent': Confirmation.CONFIRMED}, helper_stop=Confirmation.CONFIRMED)
    assert report['status'] == ('UNKNOWN' if stale else 'CLEAN')


def test_direct_classifier_cannot_bypass_delivery_handoff(namespace: tuple[Path, c.Policy, Path]) -> None:
    session, remote, commit = prepared(namespace)
    assert session.before is not None
    observed = session.inventory.capture('after')
    after = c.Snapshot(session.before.scope_id, 'after', session.inventory.policy.identity, observed.surfaces)
    report = c.classify(session.inventory.policy, session.before, after,
                        delivered_captures={'agent': capture_commit('agent', remote, commit)})
    assert report['status'] == 'UNKNOWN'
