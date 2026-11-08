"""Synthetic VM facts and local trees only; no host observation or launch."""
from __future__ import annotations

import copy
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from skillc import vm_identity as vm

CONTROLS = Path(__file__).resolve().parent.parent / 'controls/vm-identity'
CASES = json.loads((CONTROLS / 'cases.json').read_text())


def environment() -> dict[str, Any]:
    return json.loads((CONTROLS / 'environment.json').read_text())


def observation(tmp_path: Path, env: dict[str, Any]) -> vm.Observation:
    root = tmp_path / 'install'
    shutil.copytree(CONTROLS / 'install', root)
    # Git controls the executable class, not checkout group/other write bits.
    # Materialize the declared synthetic artifact before observing any drift.
    for rel, entry in env['skillc']['install_manifest'].items():
        (root / rel).chmod(entry['mode'])
    return vm.Observation(copy.deepcopy(env['vm']), env['skillc']['revision'], root,
                          {name: root / path for name, path in vm.REQUIRED_IMPORTS.items()})


def case_input(case: dict[str, Any], tmp_path: Path) -> tuple[dict[str, Any], vm.Observation]:
    env = environment()
    obs = observation(tmp_path, env)
    action = case['action']
    if action == 'delete':
        node = env
        for key in case['path'][:-1]:
            node = node[key]
        del node[case['path'][-1]]
    elif action == 'observed-vm':
        obs.vm[case['field']] = case['value']  # type: ignore[index]
    elif action == 'write':
        path = obs.install_root / case['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(case['value'])
    elif action == 'wrong-origin':
        obs.imports['skillc.calibration'] = tmp_path / 'other/calibration.py'  # type: ignore[index]
    elif action == 'missing-origin':
        del obs.imports['skillc.calibration']  # type: ignore[attr-defined]
    elif action == 'mode':
        (obs.install_root / 'skillc/calibration.py').chmod(0o755)
    elif action == 'symlink':
        path = obs.install_root / 'skillc/calibration.py'
        path.unlink()
        path.symlink_to(tmp_path / 'outside.py')
    elif action == 'excluded-directories':
        for path in ['.git/index', '.venv/lib/unused.py', '.pytest_cache/file',
                     '.mypy_cache/file', '.ruff_cache/file', 'skillc/__pycache__/unused.pyc']:
            excluded = obs.install_root / path
            excluded.parent.mkdir(parents=True, exist_ok=True)
            excluded.write_bytes(b'synthetic generated bookkeeping')
    elif action == 'empty':
        shutil.rmtree(obs.install_root)
        obs.install_root.mkdir()
    elif action != 'none':
        raise AssertionError('unimplemented committed control')
    return env, obs


Verifier = Callable[[object, vm.Observation | None], dict[str, Any]]


def qualify(verifier: Verifier, tmp_path: Path) -> None:
    """Both known verdicts are required; an always-match verifier loses."""
    for case in CASES['cases']:
        where = tmp_path / case['name']
        where.mkdir()
        env, obs = case_input(case, where)
        try:
            result = verifier(env, obs)
            assert result['status'] == 'MATCH'
            actual = 'MATCH'
        except vm.IdentityRefused:
            actual = 'REFUSED'
        assert actual == case['expected'], case['name']


def test_committed_good_and_bad_installations(tmp_path: Path) -> None:
    qualify(vm.verify, tmp_path)


def test_committed_blind_verifier_is_rejected(tmp_path: Path) -> None:
    control = CASES['qualification_controls'][0]
    assert control['verifier'] == 'always-match' and control['expected'] == 'REFUSED'
    with pytest.raises(AssertionError, match=control['witness']):
        qualify(lambda _env, _obs: {'status': 'MATCH'}, tmp_path)


def test_matching_record_has_identity_but_no_local_paths(tmp_path: Path) -> None:
    env = environment()
    obs = observation(tmp_path, env)
    before = copy.deepcopy(env)
    record = vm.verify(env, obs)
    assert record['vm'] == env['vm']
    assert record['skillc_revision'] == env['skillc']['revision']
    assert record['window'] == env['window']
    assert record['scope'] == 'binding-and-install-match-only'
    assert str(tmp_path) not in json.dumps(record)
    record['vm']['kernel'] = 'different'
    assert env == before and obs.vm == before['vm']


def test_no_default_vm_observation() -> None:
    with pytest.raises(vm.IdentityRefused, match='observation'):
        vm.verify(environment(), None)


@pytest.mark.parametrize('mutation', ['null', 'unknown', 'extra', 'version-bool', 'window-naive',
                                    'window-reversed', 'bad-digest', 'excluded-path', 'empty-manifest',
                                    'path-traversal', 'mode-bool', 'bytes-bool', 'missing-module'])
def test_invalid_closed_schema_is_refused(mutation: str) -> None:
    env = environment()
    if mutation == 'null':
        env = None  # type: ignore[assignment]
    elif mutation == 'unknown':
        env['vm']['id'] = 'UNKNOWN'
    elif mutation == 'extra':
        env['exclusions'] = ['*']
    elif mutation == 'version-bool':
        env['version'] = True
    elif mutation == 'window-naive':
        env['window']['starts_at'] = '2026-01-01T00:00:00'
    elif mutation == 'window-reversed':
        env['window']['ends_at'] = env['window']['starts_at']
    else:
        manifest = env['skillc']['install_manifest']
        row = manifest['skillc/calibration.py']
        if mutation == 'bad-digest':
            row['sha256'] = 'not-a-digest'
        elif mutation == 'excluded-path':
            manifest['.venv/file.py'] = row
        elif mutation == 'empty-manifest':
            env['skillc']['install_manifest'] = {}
        elif mutation == 'path-traversal':
            manifest['../outside.py'] = row
        elif mutation == 'mode-bool':
            row['mode'] = True
        elif mutation == 'bytes-bool':
            row['bytes'] = True
        elif mutation == 'missing-module':
            del manifest['skillc/calibration.py']
    with pytest.raises(vm.IdentityRefused, match='execution_environment'):
        vm.validate(env)


def test_racing_install_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = environment()
    obs = observation(tmp_path, env)
    read = vm.install_manifest
    calls = 0

    def racing(root: Path) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        result = read(root)
        if calls == 1:
            (root / 'skillc/calibration.py').write_text('changed during origin checking\n')
        return result

    monkeypatch.setattr(vm, 'install_manifest', racing)
    with pytest.raises(vm.IdentityRefused, match='changed during'):
        vm.verify(env, obs)


def test_read_failure_is_refused_without_private_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(_root: Path) -> object:
        raise OSError('private path and synthetic secret')

    monkeypatch.setattr(vm, 'SafeTree', unavailable)
    with pytest.raises(vm.IdentityRefused, match='installation unreadable') as err:
        vm.install_manifest(tmp_path)
    assert 'private path' not in str(err.value)


def test_byte_depth_and_population_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = environment()
    obs = observation(tmp_path, env)
    for name, value in [('MAX_FILE', 1), ('MAX_BYTES', 1), ('MAX_DEPTH', 0), ('MAX_FILES', 1)]:
        with monkeypatch.context() as patch:
            patch.setattr(vm, name, value)
            with pytest.raises(vm.IdentityRefused):
                vm.install_manifest(obs.install_root)


@pytest.mark.parametrize('checkout_mode', [0o664, 0o666])
def test_fixture_materialization_is_checkout_mode_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkout_mode: int,
) -> None:
    env = environment()
    checkout = tmp_path / 'synthetic-checkout'
    shutil.copytree(CONTROLS, checkout)
    for path in (checkout / 'install').rglob('*'):
        if path.is_file():
            path.chmod(checkout_mode)
    monkeypatch.setattr(sys.modules[__name__], 'CONTROLS', checkout)
    observed = observation(tmp_path / 'materialized', env)
    assert vm.install_manifest(observed.install_root) == env['skillc']['install_manifest']
    assert vm.verify(env, observed)['status'] == 'MATCH'


def test_installed_write_bit_drift_is_still_refused(tmp_path: Path) -> None:
    env = environment()
    observed = observation(tmp_path, env)
    (observed.install_root / 'skillc/calibration.py').chmod(0o666)
    with pytest.raises(vm.IdentityRefused, match='installed population'):
        vm.verify(env, observed)
