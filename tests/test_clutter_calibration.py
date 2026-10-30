"""#619 common-arm declaration and actual controller lifecycle integration.

Fake Docker/scripted clients only; no live model or physical isolation claim.
The collector reads the fake namespace's real Git/files while its role is up.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import stamp_approval
from test_calibration_run import _declaration_data, _run
from test_clutter_capture import git
from test_clutter_inventory import declaration

from skillc import calibration
from skillc import calibration_run as cr
from skillc import clutter as c
from skillc import clutter_capture as capture
from skillc import clutter_controller as controller


def declared() -> calibration.CalibrationDeclaration:
    raw = _declaration_data(attempts=1)
    raw['clutter_inventory'] = declaration()
    return calibration.parse_declaration(stamp_approval(raw))


def test_common_inventory_policy_and_approval_digest_bind_allowed_state() -> None:
    value = declared()
    policy = calibration.clutter_policy(value.data)
    assert policy is not None
    original = calibration.declaration_digest(value.data)
    assert value.approval is not None
    calibration._require_whole_declaration_approval(value.data, value.approval)
    changed = copy.deepcopy(value.data)
    changed['clutter_inventory']['declared_allowed'] = []  # type: ignore[index]
    assert calibration.declaration_digest(changed) != original
    parsed = calibration.parse_declaration(changed)
    assert parsed.approval is not None
    with pytest.raises(calibration.DeclarationRefused, match='digest'):
        calibration._require_whole_declaration_approval(parsed.data, parsed.approval)


def test_subtree_allowance_changes_require_a_new_whole_declaration_approval() -> None:
    raw = _declaration_data(attempts=1)
    policy = declaration()
    policy['allowed_subtrees'] = [{'surface': 'agent/workspace', 'path': '/work/repo/.venv'}]
    raw['clutter_inventory'] = policy
    approved = calibration.parse_declaration(stamp_approval(raw))
    assert approved.approval is not None
    calibration._require_whole_declaration_approval(approved.data, approved.approval)
    changed: dict[str, Any] = copy.deepcopy(dict(approved.data))
    changed['clutter_inventory']['allowed_subtrees'].append(
        {'surface': 'agent/workspace', 'path': '/work/repo/node_modules'})
    parsed = calibration.parse_declaration(changed)
    assert parsed.approval is not None
    with pytest.raises(calibration.DeclarationRefused, match='digest'):
        calibration._require_whole_declaration_approval(parsed.data, parsed.approval)


@pytest.mark.parametrize('fault', ['schema', 'empty-roles', 'omit-cpp', 'empty-cpp', 'empty-temp',
                                  'unsafe-path', 'wrong-settle', 'overlap', 'per-arm', 'mailbox-marker'])
def test_invalid_inventory_declarations_are_refused_before_dispatch(fault: str) -> None:
    raw: dict[str, Any] = copy.deepcopy(dict(declared().data))
    policy = raw['clutter_inventory']
    if fault == 'schema':
        policy['schema_version'] = True
    elif fault == 'empty-roles':
        policy['roles'] = {}
    elif fault == 'omit-cpp':
        del policy['roles']['agent']['coordination']['locks']
    elif fault == 'empty-cpp':
        policy['roles']['agent']['coordination']['locks'] = []
    elif fault == 'empty-temp':
        policy['roles']['agent']['temp_roots'] = []
    elif fault == 'unsafe-path':
        policy['roles']['agent']['checkout'] = '/work/../repo'
    elif fault == 'wrong-settle':
        policy['settle_point'] = 'after-teardown'
    elif fault == 'overlap':
        policy['declared_allowed'] = copy.deepcopy(policy['delivered'])
    elif fault == 'mailbox-marker':
        policy['roles']['agent']['mailbox_marker'] = 'not a bounded marker'
    else:
        raw['arms'][0]['clutter_inventory'] = policy
    with pytest.raises(calibration.DeclarationRefused):
        calibration.parse_declaration(raw)


@pytest.mark.parametrize('leave_clutter', [False, True])
def test_paired_calibration_captures_both_arms_before_teardown(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leave_clutter: bool) -> None:
    raw: dict[str, Any] = copy.deepcopy(dict(declared().data))
    scope = raw['clutter_inventory']['roles']['agent']
    scope['checkout'], scope['gitdir'], scope['remotes'] = '/work', '/work/.git', {'fixture': '/fixture.git'}
    # This fixed client's output marker is its product. The exact two
    # controller scaffold files are declared; arbitrary residue is not.
    raw['clutter_inventory']['delivered'] = [{'surface': 'agent/workspace', 'key': 'file:/work/agent-touched.txt'}]
    raw['clutter_inventory']['declared_allowed'] = [
        {'surface': 'agent/workspace', 'key': 'file:/work/.skillc-canary-result'},
        {'surface': 'agent/workspace', 'key': 'file:/work/observations'}]
    value = calibration.parse_declaration(stamp_approval(raw))
    policies: list[str] = []
    stages: list[str] = []
    actual = controller.single_role_session

    def session(policy: c.Policy, backend: Any, handle: Any) -> controller.Session:
        policies.append(policy.identity)
        state_dir = Path(backend.docker_bin[backend.docker_bin.index('--state') + 1])
        root = state_dir / (handle.name + '.fsroot')
        repo = root / 'work'
        git(repo, 'init', '-q', '-b', 'main')
        git(repo, 'config', 'user.name', 'Fixture')
        git(repo, 'config', 'user.email', 'fixture@example.invalid')
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'controller setup')
        git(repo, 'clone', '-q', '--bare', str(repo), str(root / 'fixture.git'))
        for path in ('state/locks', 'state/mailboxes', 'state/cursors', 'state/heartbeats',
                     'state/claims', 'shared', 'tmp', 'proc'):
            (root / path).mkdir(parents=True, exist_ok=True)
        (root / 'state/registry.json').write_text('{"waves": {}}')

        captured = [0]

        def read_role() -> dict[str, c.Surface]:
            # This assertion becomes red if the after capture moves behind
            # stop/teardown. No physical Docker behavior is mocked as proved.
            status = json.loads((state_dir / (handle.name + '.json')).read_text())['status']
            assert status == 'running', 'capture happened after role teardown'
            assert (repo / 'agent-touched.txt').exists() is (captured[0] > 0), 'capture crossed client execution'
            captured[0] += 1
            stages.append(status)
            return capture.capture_role(policy, 'agent', root, proc_root=root / 'proc', namespace_root=str(root))
        observer = controller.Inventory(policy, {'agent': read_role},
                                        lambda: capture.capture_shared(policy, root),
                                        lambda: {'containers': c.Surface({}), 'networks': c.Surface({})})

        class Session(controller.Session):
            def completion(self, role: str) -> None:
                if leave_clutter:
                    (root / 'state/locks/task-leftover').write_text('unretired')
                super().completion(role)
        return Session(observer)

    assert actual is not session
    monkeypatch.setattr(controller, 'single_role_session', session)
    experiment, outcomes, _, _ = _run(tmp_path, monkeypatch, declaration=value, solve_arms=())
    report: dict[str, Any] = cr.build_report(experiment, outcomes, declared_model='gpt-6-astra', declared_effort='high')
    assert len(policies) == len(outcomes) == 2 and len(set(policies)) == 1
    assert stages == ['running'] * 4
    assert report['clutter_inventory']['policy_digest'] == policies[0]
    expected = 'NOT_CLEAN' if leave_clutter else 'CLEAN'
    assert {entry['arm'] for entry in report['attempts']} == set(value.arms)
    assert all(entry['clutter']['status'] == expected for entry in report['attempts']), report['attempts']
    if leave_clutter:
        assert all(any(item['key'] == 'file:/state/locks/task-leftover'
                       for item in entry['clutter']['additions']['clutter']) for entry in report['attempts'])
    # A mutable outcomes checkpoint is not the inventory's evidence channel.
    for outcome in outcomes:
        outcome.record['clutter'] = {'status': 'CLEAN', 'clean': True}
    replayed: dict[str, Any] = cr.build_report(experiment, outcomes, declared_model='gpt-6-astra', declared_effort='high')
    assert all(entry['clutter']['status'] == expected for entry in replayed['attempts'])
