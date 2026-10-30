"""#640 paired calibration through real dispatch, fake Docker and reviewed actors.

The declaration uses #287's matched-outcome shape with synthetic test approval;
it is never a live approval or profile proof. Oracle transport uses the reviewed
B1 control evaluator, guarded by equality to every captured Python input.
"""
from __future__ import annotations

import base64
import copy
import dataclasses
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import stamp_approval
from test_agent_trial import _fake_argv, _mapped_home
from test_agent_trial_fixture import GATE_ENTRY, GATE_SCRIPT, TOP_LEVEL, _actor, _gh
from test_agent_trial_gate_witness import VirtualMountBackend
from test_calibration_run import (
    _FAKE_DAEMON_TIMEOUT,
    _IMAGE,
    _docker_bin,
    _fresh_codex_credential,
    _treatment,
)
from test_inventory_runtime import ROOT, TASK, reviewed_oracle

from skillc import agent_trial as at
from skillc import calibration, verify
from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import docker_backend as d
from skillc import fixture_overlay as fo
from skillc import inventory_oracle as io

INVENTORY_IMAGE_ID = 'sha256:' + 'c' * 64


@pytest.fixture(autouse=True)
def no_quarantine() -> Iterator[None]:
    yield
    if verify._quarantine is not None:
        reason = verify._quarantine
        verify.clear_quarantine()
        pytest.fail(f'this test quarantined the verifier: {reason}')


@pytest.fixture(scope='module')
def reviewed_results() -> dict[str, dict[str, Any]]:
    return {program: reviewed_oracle(program) for program in ('reference', 'fixture')}


def declaration() -> calibration.CalibrationDeclaration:
    data = json.loads((ROOT / 'evals/calibration-287/pilot-improvement-declaration.json').read_text())
    grader = verify.GraderDef.load(TASK)
    data['issue'] = 640
    data['attempts_per_arm'] = 1
    data['arm_order']['sequence'] = calibration.derive_arm_order(data['arm_order']['seed'], ['intact', 'baseline'], 1)
    data['task'] = {'path': TASK.relative_to(ROOT).as_posix(), 'fixture': 'builder', 'fixture_case': 'inventory',
                    'grader_id': grader.id, 'grader_revision': grader.revision}
    data['shared']['image']['digest'] = INVENTORY_IMAGE_ID
    data['shared']['image']['tag'] = _IMAGE
    data['shared']['public_requirements'] = str(TASK.relative_to(ROOT) / 'goal.md')
    data['task_content'] = cr.task_content_identity((TASK / 'goal.md').read_bytes(), grader,
                                                    cc.task_surface(TASK / 'builder'))
    data['outcome_endpoint']['criteria'] = list(grader.criteria)
    data['approval'] = {'by': 'owner (synthetic test approval only)', 'at': '2026-10-30',
                        'attempts_per_arm': 1, 'task_fixture': 'builder',
                        'profile_inventory_digest': data['approval']['profile_inventory_digest']}
    return calibration.parse_declaration(stamp_approval(data))


def writer(path: Path) -> None:
    path.write_text('''import importlib.util,pathlib,sys
repo,remote,task,program,action=map(str,sys.argv[1:])
repo=pathlib.Path(repo); task=pathlib.Path(task)
source=task/('candidates/reference.py' if program=='reference' else 'fixture/inventory.py')
(repo/'inventory.py').write_bytes(source.read_bytes())
if action=='workspace': raise SystemExit(0)
(repo/'tests/test_import.py').write_bytes((task/'candidates/test_import.py').read_bytes())
spec=importlib.util.spec_from_file_location('reviewed_inventory_builder',task/'builder/build.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
b.host_git(['checkout','-qb','delivery'],repo)
b.host_git(['add','--all'],repo)
b.host_git(['commit','-qm','Deliver reviewed inventory control'],repo,date='2026-10-02T09:00:00+0000')
b.host_git(['push','-q',remote,'HEAD:refs/heads/delivery'],repo)
''')


@pytest.mark.parametrize('scenario,expected', [('correct', 'PASS'), ('wrong-main', 'FAIL'),
                                              ('undelivered', 'FAIL'), ('missing-export', 'INCONCLUSIVE'),
                                              ('oracle-unavailable', 'INCONCLUSIVE')])
def test_paired_runtime_grades_only_captured_main(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reviewed_results: dict[str, dict[str, Any]],
        scenario: str, expected: str) -> None:
    treatment = _treatment(tmp_path, monkeypatch)
    treatment = dataclasses.replace(treatment, home_files={**treatment.home_files, GATE_ENTRY: GATE_SCRIPT},
                                    verify_home_files={GATE_ENTRY: 'sha256:' + hashlib.sha256(GATE_SCRIPT).hexdigest()},
                                    gate_entrypoint=GATE_ENTRY)
    monkeypatch.setattr(cr, 'guard_kwargs', lambda client, model: {})
    monkeypatch.setattr(at, '_FLOW_CHECK_GATE_HARNESS_ROOT', '/home/candidate/.protected-harness')
    monkeypatch.setattr(fo, 'install_gh_shim', lambda *args: fo.PlacedFile(fo.GH_PATH, '-'))
    monkeypatch.setattr(fo, 'install_codex_guard', lambda *args: {})
    run_dir, state = tmp_path / 'run', tmp_path / 'state'
    run_dir.mkdir()
    channel = Path(tempfile.mkdtemp(prefix='sk-inventory-'))
    actor_writer = tmp_path / 'reviewed-writer.py'
    writer(actor_writer)
    jobs: list[dict[str, Any]] = []
    cleanups: list[str] = []
    real_run = subprocess.run
    trusted: list[dict[str, Any]] = []
    grade = verify.grade_files

    def observe(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get('trusted_observation'):
            trusted.append(json.loads(kwargs['trusted_observation']))
        return grade(*args, **kwargs)

    monkeypatch.setattr(verify, 'grade_files', observe)

    def oracle(argv: list[str], data: str, **kwargs: Any) -> tuple[int, bytes, str | None]:
        job = json.loads(data)
        jobs.append(job)
        assert argv[argv.index('--network') + 1] == 'none' and 'exec' not in argv
        if scenario == 'oracle-unavailable':
            return 0, b'', 'timeout'
        files = {p: base64.b64decode(row['data_b64']) for p, row in job['files'].items() if p.endswith('.py')}
        program = 'fixture' if scenario == 'wrong-main' else 'reference'
        expected_code = (TASK / ('fixture/inventory.py' if program == 'fixture' else 'candidates/reference.py')).read_bytes()
        assert files == {'inventory.py': expected_code,
                         'tests/test_legacy.py': (TASK / 'fixture/tests/test_legacy.py').read_bytes(),
                         'tests/test_import.py': (TASK / 'candidates/test_import.py').read_bytes()}
        return 0, (job['nonce'] + json.dumps(reviewed_results[program]) + '\n').encode(), None

    def remove_or_run(argv: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(argv, list) and str(argv[-1]).startswith('skillc-inventory-oracle-'):
            if argv[-3:-1] == ['rm', '-f']:
                cleanups.append(argv[-1])
                return subprocess.CompletedProcess(argv, 1, stdout='', stderr='No such container')
            if argv[-2] == 'inspect':
                return subprocess.CompletedProcess(argv, 1, stdout='', stderr='Error: No such object: ' + argv[-1])
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(io.transport, '_bounded', oracle)
    monkeypatch.setattr(subprocess, 'run', remove_or_run)

    class Backend(VirtualMountBackend):
        def _image_id(self, handle: Any) -> str:
            return INVENTORY_IMAGE_ID  # synthetic measured-ID response from this fake image

        def export(self, handle: object, dest: Path, root: str | None = None) -> None:
            super().export(handle, dest, root)
            if scenario == 'missing-export' and (dest / '.remote').is_dir():
                shutil.rmtree(dest / '.remote')

    def backends() -> tuple[Any, Any]:
        return (Backend(image=_IMAGE, base_dir=run_dir, docker_bin=_docker_bin(state),
                        daemon_timeout=_FAKE_DAEMON_TIMEOUT, trigger_socket_dir=channel),
                d.DockerBackend(image=_IMAGE, base_dir=run_dir, docker_bin=_docker_bin(state),
                                daemon_timeout=_FAKE_DAEMON_TIMEOUT))

    def argv_for(scheduled: Any) -> list[str]:
        home = _mapped_home(state, scheduled.attempt_id)
        workspace = state / f'{d._container_name(scheduled.attempt_id)}.fsroot/work'
        repo, remote = workspace / 'repo', workspace / '.remote/widget.git'
        rel = f'.codex/sessions/2026/01/01/rollout-{scheduled.attempt_id}.jsonl'
        requests: list[Any] = [TOP_LEVEL]
        if scenario != 'undelivered':
            program = 'fixture' if scenario == 'wrong-main' else 'reference'
            requests.append({'sh': [sys.executable, str(actor_writer), str(repo), str(remote), str(TASK), program, 'deliver']})
            for args in (['pr', 'create', '--head', 'delivery', '--base', 'main', '--title', 'Import inventory', '--body', 'Refs #1'],
                         ['pr', 'merge', '2', '--squash']):
                request = copy.deepcopy(_gh(args))
                request['context']['branch'] = 'delivery'  # type: ignore[index]
                requests.append(request)
        local = 'reference' if scenario in ('wrong-main', 'undelivered') else 'fixture'
        requests.append({'sh': [sys.executable, str(actor_writer), str(repo), str(remote), str(TASK), local, 'workspace']})
        actor = tmp_path / f'actor-{scheduled.attempt_id}.py'
        _actor(actor, str(d.trigger_socket_host_path_for(channel, d._container_name(scheduled.attempt_id))),
               home / rel, requests, 'The task is complete.')
        return [sys.executable, str(actor), *_fake_argv(fmt='codex-fake', home=home, transcript_relpath=rel)[1:]]

    declared = declaration()
    try:
        experiment, result = cr.run_calibration(declared, run_dir=run_dir, treatment=treatment,
                                               image_digest=INVENTORY_IMAGE_ID, backends=backends, argv_for=argv_for,
                                               credential_explicit_path=_fresh_codex_credential(tmp_path))
        report: dict[str, Any] = cr.build_report(experiment, result, declared_model='gpt-6-astra',
                                               declared_effort='high')
    finally:
        shutil.rmtree(channel, ignore_errors=True)
    assert len(result) == len(trusted) == 2
    assert report['fixture']['symmetric'] is True
    assert report['fixture']['dispatched_by_arm'] == {'baseline': 1, 'intact': 1}
    assert all(entry['primary_endpoint']['status'] == expected for entry in report['attempts']), report['attempts']
    assert all(entry['accounting'] == {'PASS': 'success', 'FAIL': 'task-failure', 'INCONCLUSIVE': 'unknown'}[expected]
               for entry in report['attempts'])
    by_offer = {entry['gates_offered']: entry for entry in trusted}
    assert set(by_offer) == {False, True}
    records_by_arm: dict[str, Any] = {outcome.scheduled.arm: outcome.record for outcome in result}
    baseline = {row['id']: row for row in records_by_arm['baseline']['graded']['criteria']}
    assert baseline['gate-ran']['outcome'] == 'UNKNOWN' and 'not applicable' in baseline['gate-ran']['missing']
    assert len(jobs) == len(cleanups)
    if scenario == 'missing-export':
        assert not jobs and all(entry['git'] is None for entry in trusted)
