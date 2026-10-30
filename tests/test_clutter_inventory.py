"""#619 controls: collected residue, unknown coverage, separate preservation."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from skillc import clutter as c
from skillc.clutter_controller import Inventory, Session

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'controls/clutter-inventory/cases.json').read_text())


def declaration(roles: tuple[str, ...] = ('agent',)) -> dict[str, Any]:
    scope = {'checkout': '/work/repo', 'gitdir': '/work/repo/.git',
             'remotes': {'fixture': '/work/fixture.git'},
             'cpp': {kind: ['/state/' + kind] for kind in c.CPP_KINDS}, 'temp_roots': ['/tmp']}
    scope['cpp']['registry'] = ['/state/registry.json']  # type: ignore[index]
    return {'schema_version': 1, 'daemon_scope': 'controller-isolated', 'roles': {role: copy.deepcopy(scope) for role in roles},
            'shared_roots': ['/shared'], 'settle_point': c.SETTLE_POINT, 'settle_seconds': 0,
            'delivered': [{'surface': roles[0] + '/workspace', 'key': 'file:/work/repo/result.txt'}],
            'declared_allowed': [{'surface': roles[0] + '/workspace', 'key': 'file:/work/repo/friction.log'}]}


def snapshots(policy: c.Policy) -> tuple[c.Snapshot, c.Snapshot]:
    surfaces = {name: c.Surface({'pre-existing': 'original'}) for name in policy.surfaces}
    return (c.Snapshot('scope', 'before', policy.identity, surfaces),
            c.Snapshot('scope', 'after', policy.identity, copy.deepcopy(surfaces)))


@pytest.mark.parametrize('case', CASES['not_clean'], ids=lambda row: row['name'])
def test_each_committed_planted_residue_is_not_clean(case: dict[str, str]) -> None:
    policy = c.parse_policy(declaration())
    before, after = snapshots(policy)
    rows = dict(after.surfaces)
    rows[case['surface']] = c.Surface({**rows[case['surface']].items, case['key']: 'planted'})
    after = c.Snapshot(after.scope_id, after.phase, after.policy_digest, rows)
    report = c.classify(policy, before, after)
    assert report['status'] == 'NOT_CLEAN'
    assert report['clean'] is False
    assert report['counts'] == {'delivered': 0, 'declared-allowed': 0, 'clutter': 1}
    assert report['additions']['clutter'][0]['key'] == case['key']


@pytest.mark.parametrize('name', CASES['clean'])
def test_clean_and_alternative_cleanup_order_have_the_same_endpoint(name: str) -> None:
    policy = c.parse_policy(declaration())
    before, after = snapshots(policy)
    rows = dict(after.surfaces)
    products = [('file:/work/repo/result.txt', 'result'), ('file:/work/repo/friction.log', 'log')]
    if name == 'alternative-cleanup-order':
        products.reverse()
        rows = dict(reversed(list(rows.items())))
    rows['agent/workspace'] = c.Surface({**rows['agent/workspace'].items, **dict(products)})
    report = c.classify(policy, before, c.Snapshot('scope', 'after', policy.identity, rows))
    assert report['status'] == 'CLEAN'
    assert report['counts'] == {'delivered': 1, 'declared-allowed': 1, 'clutter': 0}


def test_baseline_absence_of_cpp_is_not_a_failure_or_an_exemption_for_added_state() -> None:
    policy = c.parse_policy(declaration())
    empty = {name: c.Surface({}) for name in policy.surfaces}
    before = c.Snapshot('scope', 'before', policy.identity, empty)
    after = c.Snapshot('scope', 'after', policy.identity, empty)
    assert c.classify(policy, before, after)['status'] == 'CLEAN'
    rows = dict(empty)
    rows['agent/cpp-registry'] = c.Surface({'new-entry': 'state'})
    assert c.classify(policy, before, c.Snapshot('scope', 'after', policy.identity, rows))['status'] == 'NOT_CLEAN'


@pytest.mark.parametrize('fault', ['missing', 'unreadable', 'partial'])
def test_a_missing_or_unreadable_required_surface_never_reads_clean(fault: str) -> None:
    policy = c.parse_policy(declaration(('orchestrator', 'worker-a', 'worker-b')))
    before, after = snapshots(policy)
    rows = dict(after.surfaces)
    if fault == 'missing':
        del rows['worker-b/processes']
    else:
        rows['worker-b/processes'] = c.Surface({}, False, 'unreadable' if fault == 'unreadable' else None)
    report = c.classify(policy, before, c.Snapshot('scope', 'after', policy.identity, rows))
    assert report['status'] == 'UNKNOWN' and report['clean'] is None


def test_preservation_changes_and_removals_are_separate_and_never_offset_added_clutter() -> None:
    policy = c.parse_policy(declaration())
    before, after = snapshots(policy)
    rows = dict(after.surfaces)
    rows['agent/workspace'] = c.Surface({'pre-existing': 'changed', 'new-junk': 'junk'})
    rows['agent/stashes'] = c.Surface({})
    report = c.classify(policy, before, c.Snapshot('scope', 'after', policy.identity, rows))
    assert report['counts']['clutter'] == 1
    assert len(report['preservation']['changed']) == len(report['preservation']['removed']) == 1
    rows['agent/workspace'] = c.Surface({'pre-existing': 'changed'})
    separate = c.classify(policy, before, c.Snapshot('scope', 'after', policy.identity, rows))
    assert separate['counts']['clutter'] == 0
    assert separate['preservation']['changed'] and separate['preservation']['removed']


def test_policy_digest_binds_schema_scope_settle_point_and_allowed_list() -> None:
    raw = declaration()
    policy = c.parse_policy(raw)
    for field, value in (('declared_allowed', []), ('settle_seconds', 1), ('shared_roots', ['/other'])):
        changed = {**raw, field: value}
        assert c.parse_policy(changed).identity != policy.identity
    with pytest.raises(c.Refused):
        c.parse_policy({**raw, 'schema_version': True})
    before, after = snapshots(policy)
    changed_after = c.Snapshot(after.scope_id, after.phase, c.parse_policy({**raw, 'settle_seconds': 1}).identity,
                               after.surfaces)
    assert c.classify(policy, before, changed_after)['status'] == 'UNKNOWN'


def test_session_requires_every_role_completion_and_the_declared_settle_delay() -> None:
    policy = c.parse_policy(declaration(('orchestrator', 'worker-a', 'worker-b')))
    readers = {role: lambda role=role: {name: c.Surface({}) for name in policy.surfaces
                                      if name.startswith(role + '/')} for role in policy.roles}
    inventory = Inventory(policy, readers, lambda: c.Surface({}),
                          lambda: {'containers': c.Surface({}), 'networks': c.Surface({})})
    session = Session(inventory)
    session.setup()
    session.completion('orchestrator')
    assert session.finish()['status'] == 'UNKNOWN'
    raw = declaration()
    raw['settle_seconds'] = 1
    timed_policy = c.parse_policy(raw)
    now = [0.0]
    inv = Inventory(timed_policy, {'agent': lambda: {name: c.Surface({}) for name in timed_policy.surfaces
                                                    if name.startswith('agent/')}}, lambda: c.Surface({}),
                    lambda: {'containers': c.Surface({}), 'networks': c.Surface({})})
    early = Session(inv, clock=lambda: now[0], wait=lambda _: None)
    early.setup()
    early.completion('agent')
    assert early.finish()['status'] == 'UNKNOWN'
    settled = Session(inv, clock=lambda: now[0], wait=lambda seconds: now.__setitem__(0, now[0] + seconds))
    settled.setup()
    settled.completion('agent')
    assert settled.finish()['status'] == 'CLEAN'


def test_controller_snapshot_does_not_alias_a_mutable_reader_result() -> None:
    policy = c.parse_policy(declaration())
    mutable: dict[str, str] = {}
    rows = {name: c.Surface(mutable if name == 'agent/workspace' else {})
            for name in policy.surfaces if name.startswith('agent/')}
    inventory = Inventory(policy, {'agent': lambda: rows}, lambda: c.Surface({}),
                          lambda: {'containers': c.Surface({}), 'networks': c.Surface({})})
    before = inventory.capture('before')
    mutable['planted'] = 'leftover'
    after = inventory.capture('after')
    assert c.classify(policy, before, after)['status'] == 'NOT_CLEAN'


def assert_control_population(value: dict[str, Any]) -> None:
    required = {'leftover-worktree', 'stale-local-branch', 'stale-remote-branch', 'leftover-stash',
                'orphaned-watch', 'orphaned-supervise', 'stale-lock', 'unretired-registry-entry',
                'unretired-mailbox', 'stale-cursor', 'stale-heartbeat', 'stale-claim', 'ignored-file',
                'shared-wave-state', 'temporary-directory', 'leftover-container', 'leftover-network'}
    names = [row['name'] for row in value['not_clean']]
    assert value['schema_version'] == 1
    assert len(names) == len(set(names)) == len(required) and set(names) == required
    assert value['clean'] == ['cleaned-run', 'alternative-cleanup-order']


def test_committed_control_population_and_its_empty_negative_control() -> None:
    assert_control_population(CASES)
    missing = json.loads((ROOT / 'controls/clutter-inventory/missing-controls.json').read_text())
    with pytest.raises(AssertionError):
        assert_control_population(missing)
