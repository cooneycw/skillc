"""Synthetic qualification only; no real host statvfs/helper measurement."""
from __future__ import annotations

import copy
import inspect
import json
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skillc import nhl_headroom as nh

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'controls/nhl-headroom/fixture.json').read_text())
CASES = json.loads((ROOT / 'controls/nhl-headroom/cases.json').read_text())
MUTANTS = json.loads((ROOT / 'controls/nhl-headroom/mutants.json').read_text())


def inputs(case: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], float]:
    data = copy.deepcopy(FIXTURE)
    data['receipt_binding'] = copy.deepcopy(data['binding'])
    for patch in case['patches'] if case else ():
        target = data
        for part in patch[:-2]:
            target = target[part]
        target[patch[-2]] = patch[-1]
    policy = data['policy']
    try:
        digest = nh.policy_digest(policy)
    except nh.HeadroomRefused:
        digest = 'sha256:' + '00' * 32
    receipt = {'version': 1, 'policy_digest': digest, 'binding': data['receipt_binding'],
               'started_at': data['started_at'], 'finished_at': data['finished_at'], 'roots': data['roots']}
    return policy, receipt, data['binding'], data['now']


@pytest.mark.parametrize('case', CASES, ids=lambda row: row['name'])
def test_qualified_pass_fail_unknown(case: dict[str, Any]) -> None:
    result = nh.evaluate(*inputs(case))
    assert result['status'] == case['status'] and result['admission_authority'] is False
    if 'required_bytes' in case:
        assert result['filesystems'][0]['required_bytes'] == case['required_bytes']


@pytest.mark.parametrize('mutant', MUTANTS, ids=lambda row: row['name'])
def test_committed_blind_variants_lose_their_shortage_witness(mutant: dict[str, str]) -> None:
    source = inspect.getsource(nh._evaluate)
    assert source.count(mutant['before']) == 1
    source = source.replace(mutant['before'], mutant['after'])
    namespace = dict(vars(nh))
    exec(compile(source, '<blind-headroom-validator>', 'exec'), namespace)  # noqa: S102
    case = next(row for row in CASES if row['name'] == mutant['witness'])
    assert nh.evaluate(*inputs(case))['status'] == 'FAIL'
    with pytest.raises(AssertionError):
        assert namespace['_evaluate'](*inputs(case))['status'] == 'FAIL'


def test_same_actual_reference_copy_is_counted_once_but_distinct_copies_are_not() -> None:
    policy, receipt, bound, now = inputs()
    policy['demands'].append({**policy['demands'][0], 'root': 'alias'})
    receipt['roots']['alias'] = copy.deepcopy(receipt['roots']['reference'])
    receipt['policy_digest'] = nh.policy_digest(policy)
    result = nh.evaluate(policy, receipt, bound, now)
    assert result['status'] == 'PASS' and result['filesystems'][0]['required_bytes'] == 240
    receipt['roots']['alias']['inode'] += 10
    result = nh.evaluate(policy, receipt, bound, now)
    assert result['filesystems'][0]['required_bytes'] == 300
    receipt['roots']['alias']['inode'] -= 10
    policy['demands'][-1]['bytes'] += 1
    receipt['policy_digest'] = nh.policy_digest(policy)
    assert nh.evaluate(policy, receipt, bound, now)['status'] == 'UNKNOWN'


def test_sample_uses_run_user_available_space_and_inodes_from_one_descriptor(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[int] = []
    with monkeypatch.context() as patch:
        patch.setattr(nh.os, 'open', lambda *_a: 123)
        patch.setattr(nh.os, 'close', closed.append)
        patch.setattr(nh.os, 'fstat', lambda _fd: SimpleNamespace(st_mode=stat.S_IFDIR, st_dev=11, st_ino=101))
        patch.setattr(nh.os, 'fstatvfs', lambda _fd: SimpleNamespace(
            f_frsize=4, f_bavail=5, f_bfree=999, f_favail=7, f_ffree=999, f_fsid=(1 << 63) + 1))
        value = nh._sample('/controlled/owner-private-marker')
    assert value['available_bytes'] == 20 and value['available_inodes'] == 7
    assert value['filesystem_id'] == (1 << 63) + 1 and closed == [123]


def test_owner_collection_is_injected_and_public_output_has_no_private_marker() -> None:
    policy, _receipt, bound, now = inputs()
    marker = 'owner-private-marker'
    paths = {name: '/controlled/' + marker + '/' + name for name in FIXTURE['roots']}
    calls = []
    times = iter([100.0, 101.0])
    def observe(path: str) -> object:
        calls.append(path)
        return copy.deepcopy(FIXTURE['roots'][Path(path).name])
    receipt = nh.collect(policy, bound, paths, observe=observe, clock=lambda: next(times))
    assert set(calls) == set(paths.values())
    result = nh.evaluate(policy, receipt, bound, now)
    assert result['status'] == 'PASS'
    public = json.dumps(result)
    assert marker not in public and 'device' not in public and 'inode"' not in public
    # Prove the no-marker instrument can see its seeded bad population.
    assert marker in json.dumps({**result, 'private_paths': paths})


def test_unreadable_owner_root_does_not_echo_path_or_become_zero() -> None:
    policy, _receipt, bound, now = inputs()
    paths = {name: '/controlled/owner-private-marker/' + name for name in FIXTURE['roots']}
    def unavailable(_path: str) -> object:
        raise OSError('owner-private-marker must not enter public diagnostics')
    receipt = nh.collect(policy, bound, paths, observe=unavailable, clock=lambda: 100.0)
    result = nh.evaluate(policy, receipt, bound, now)
    assert result['status'] == 'UNKNOWN' and 'owner-private-marker' not in json.dumps(result)


@pytest.mark.parametrize('case', [CASES[0], CASES[2], CASES[7]], ids=lambda row: row['name'])
def test_owner_evaluation_cli_uses_supplied_evidence_without_host_probing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, case: dict[str, Any],
) -> None:
    policy, receipt, bound, now = inputs(case)
    paths = {}
    for name, value in [('policy', policy), ('receipt', receipt), ('binding', bound)]:
        paths[name] = tmp_path / (name + '.json')
        paths[name].write_text(json.dumps(value))
    def forbidden(*_a: object) -> None:
        raise AssertionError('evaluation must not probe any host')
    monkeypatch.setattr(nh.os, 'fstatvfs', forbidden)
    code = nh.main(['evaluate', '--policy', str(paths['policy']), '--receipt', str(paths['receipt']),
                    '--binding', str(paths['binding']), '--now', str(now)])
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == case['status'] and code == {'PASS': 0, 'FAIL': 1, 'UNKNOWN': 2}[case['status']]


def test_committed_case_population_is_not_empty() -> None:
    assert len(CASES) == 19 and {row['status'] for row in CASES} == {'PASS', 'FAIL', 'UNKNOWN'}
    assert {row['name'] for row in MUTANTS} == {'always-PASS', 'ignore-reservations'}
