"""Model-free actual HTTP/SQLite replay controls and Docker lifecycle tests."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import nhl_rerun, nhl_rerun_control, nhl_snapshot
from skillc.nhl_rerun_control import actual_control, materialize, sample

ROOT = Path(__file__).resolve().parents[1]
CONTROLS = ROOT / 'controls' / 'nhl-rerun'
IMAGE = 'python@sha256:' + 'a' * 64


@pytest.fixture
def cases(tmp_path: Path) -> list[dict[str, Any]]:
    return nhl_rerun.scenarios(*sample(tmp_path))


@pytest.mark.parametrize('index', range(10))
def test_reference_passes_actual_http_sqlite_exports(tmp_path: Path, cases: list[dict[str, Any]], index: int) -> None:
    assert actual_control(tmp_path / 'project', 'reference', cases[index])['status'] == 'PASS'


@pytest.mark.parametrize('mode,index', [('strict', 1), ('drop-fields', 1), *[('never-discrepancy', i) for i in range(2, 10)]])
def test_committed_wrong_projects_fail(tmp_path: Path, cases: list[dict[str, Any]], mode: str, index: int) -> None:
    assert actual_control(tmp_path / 'project', mode, cases[index])['status'] == 'FAIL'


def export(case: dict[str, Any], root: Path) -> dict[str, Any]:
    root.mkdir()
    mapping = {}
    for i, (path, value) in enumerate(case['payloads'].items()):
        mapping[path] = f'{i}.json'
        (root / mapping[path]).write_text(json.dumps(value))
    (root / 'reconciliation.json').write_text(json.dumps({'games': list(case['expected'].values())}))
    return {'payloads': mapping, 'reconciliation': 'reconciliation.json'}


def test_wrong_game_missing_family_false_positive_rejected(tmp_path: Path, cases: list[dict[str, Any]]) -> None:
    case = cases[2]
    adapter = export(case, tmp_path / 'exports')
    path = tmp_path / 'exports/reconciliation.json'
    original = json.loads(path.read_text())
    # Unchanged second game must not acquire a planted game's status.
    for mutate in ('wrong-game', 'false-positive', 'missing-family', 'duplicate-game'):
        data = copy.deepcopy(original)
        if mutate == 'wrong-game':
            for game in data['games']:
                game['game_id'] += 100
        elif mutate == 'false-positive':
            clean = next(g for g in data['games'] if g['game_id'] != case['game_id'])
            clean['families'][0]['status'] = 'DISCREPANCY'
        elif mutate == 'missing-family':
            data['games'][0]['families'].pop()
        else:
            data['games'][1] = data['games'][0]
        path.write_text(json.dumps(data))
        assert nhl_rerun.grade(case, tmp_path / 'exports', adapter)['status'] == 'FAIL', mutate


def test_source_retention_is_not_only_marker_presence(tmp_path: Path, cases: list[dict[str, Any]]) -> None:
    case = cases[1]
    adapter = export(case, tmp_path / 'exports')
    path = tmp_path / 'exports' / next(iter(adapter['payloads'].values()))
    value = json.loads(path.read_text())
    value.pop('gameWeek')
    path.write_text(json.dumps(value))
    assert nhl_rerun.grade(case, tmp_path / 'exports', adapter)['status'] == 'FAIL'


def test_declaration_refuses_empty_stale_or_blind_plants(tmp_path: Path) -> None:
    root, digest, ids, plants = sample(tmp_path)
    for chosen, pin, mutations in [([], digest, plants), (ids, '0'*64, plants),
                                  (ids, digest, plants[:-1]), (ids, digest, [])]:
        with pytest.raises(nhl_snapshot.ReferenceError):
            nhl_rerun.scenarios(root, pin, chosen, mutations)
    plants[0]['after'] = plants[0]['before']
    with pytest.raises(nhl_snapshot.ReferenceError, match='mutation is empty'):
        nhl_rerun.scenarios(root, digest, ids, plants)


@pytest.mark.parametrize('path', ['../escape', '/etc/passwd'])
def test_artifact_path_escape_refused(tmp_path: Path, path: str) -> None:
    with pytest.raises(nhl_snapshot.ReferenceError):
        nhl_rerun.safe_file(tmp_path, path)


def test_symlink_export_refused(tmp_path: Path, cases: list[dict[str, Any]]) -> None:
    adapter = export(cases[0], tmp_path / 'exports')
    path = tmp_path / 'exports/reconciliation.json'
    path.rename(tmp_path / 'elsewhere')
    path.symlink_to(tmp_path / 'elsewhere')
    assert nhl_rerun.grade(cases[0], tmp_path / 'exports', adapter)['status'] == 'FAIL'


def test_missing_documented_entrypoint_is_fail_without_launch(tmp_path: Path, cases: list[dict[str, Any]]) -> None:
    adapter = materialize(tmp_path / 'project')
    adapter['commands'] = ['invented-command']
    def run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        pytest.fail('must not execute undocumented candidate command')
    runner = nhl_rerun.DockerReplay(IMAGE, IMAGE, run=run)
    result = runner.execute(tmp_path / 'project', adapter, cases[0], tmp_path / 'evidence')
    assert result['status'] == 'FAIL'
    assert 'entry points missing' in result['reasons'][0]


@pytest.mark.parametrize('failed', ['none', 'exec', 'copy', 'cleanup'])
def test_docker_lifecycle_internal_network_custody_and_failures(tmp_path: Path, cases: list[dict[str, Any]], failed: str) -> None:
    adapter = materialize(tmp_path / 'project')
    calls = []
    def run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert timeout > 0
        if args[1] == 'cp' and args[2].endswith(':/access.jsonl'):
            Path(args[3]).write_text(''.join(json.dumps(p)+'\n' for p in cases[0]['payloads']))
        if args[1] == 'cp' and args[2].endswith('/exports/.') and failed != 'copy':
            adapter.update(export(cases[0], tmp_path / 'generated'))
            shutil.copytree(tmp_path / 'generated', Path(args[3]), dirs_exist_ok=True)
        rc = int((failed == 'exec' and args[1] == 'exec' and '/bin/sh' in args)
                 or (failed == 'copy' and args[1] == 'cp' and args[2].endswith('/exports/.'))
                 or (failed == 'cleanup' and args[1] == 'rm'))
        return subprocess.CompletedProcess(args, rc, 'true' if args[1] == 'inspect' else '', '')
    result = nhl_rerun.DockerReplay(IMAGE, IMAGE, run=run).execute(
        tmp_path / 'project', adapter, cases[0], tmp_path / 'evidence')
    assert result['status'] == {'none': 'PASS', 'exec': 'FAIL', 'copy': 'UNKNOWN', 'cleanup': 'UNKNOWN'}[failed]
    assert calls[0][1:4] == ['network', 'create', '--internal']
    creates = [c for c in calls if c[1] == 'create']
    assert len(creates) == 2
    for command in creates:
        assert '--pull=never' in command and '--cap-drop=ALL' in command
        assert '--privileged' not in command and '--publish' not in command and '--volume' not in command
    assert calls[-2][1:3] == ['rm', '-f']
    assert calls[-1][1:3] == ['network', 'rm']
    assert not any('expected' in c or 'manifest.json' in c for call in calls for c in call)


def test_qualifier_rejects_blind_comparator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nhl_rerun, 'grade', lambda *args, **kwargs: {'status': 'PASS'})
    with pytest.raises(nhl_snapshot.ReferenceError, match='blind/noisy'):
        nhl_rerun_control.qualify()


def test_qualifier_committed_matrix() -> None:
    result = nhl_rerun_control.qualify()
    assert result['status'] == 'PASS'
    assert len(result['controls']) == 21


def test_command_capture_timeout_and_overflow_controls() -> None:
    import sys
    good = nhl_rerun.run_command([sys.executable, '-c', 'print("ordinary output")'], 2)
    assert good.returncode == 0 and good.stdout.strip() == 'ordinary output'
    with pytest.raises(subprocess.TimeoutExpired):
        nhl_rerun.run_command([sys.executable, '-c', 'import time;time.sleep(10)'], .05)
    with pytest.raises(nhl_snapshot.ReferenceError, match='capture cap'):
        nhl_rerun.run_command([sys.executable, '-c', 'print("x" * (4*1024*1024+1))'], 2)


def test_served_routes_exact_and_no_fallback() -> None:
    import threading
    import urllib.error
    import urllib.request

    from skillc.nhl_serve import make_server
    path = '/stats/rest/en/shiftcharts?cayenneExp=gameId=123'
    with make_server({path: {'data': []}}, '127.0.0.1', 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(base + path) as response:
                assert json.load(response) == {'data': []}
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + path + '4')
            assert error.value.code == 404
        finally:
            server.shutdown()
            thread.join()


def test_private_material_cannot_be_copied_with_project(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    project.mkdir()
    nhl_rerun.custody(project, tmp_path / 'private')
    with pytest.raises(nhl_snapshot.ReferenceError, match='outside delivered'):
        nhl_rerun.custody(project, project / 'private-evidence')


def test_documented_base_argument_placeholder(tmp_path: Path) -> None:
    project = tmp_path / 'project'
    adapter = materialize(project)
    adapter.pop('base_env')
    adapter['api_base_placeholder'] = '<API_BASE>'
    adapter['commands'] = ['python3 project.py --base <API_BASE>']
    (project / 'README.md').write_text(adapter['commands'][0])
    nhl_rerun.validate_adapter(project, adapter)
    adapter['api_base_placeholder'] = '<UNDOCUMENTED>'
    with pytest.raises(nhl_snapshot.ReferenceError, match='override absent'):
        nhl_rerun.validate_adapter(project, adapter)


def test_alternate_schedule_date_does_not_require_fetching_all_aliases(tmp_path: Path, cases: list[dict[str, Any]]) -> None:
    assert actual_control(tmp_path / 'project', 'alternate-date', cases[0])['status'] == 'PASS'


def test_observed_request_population_is_required(tmp_path: Path, cases: list[dict[str, Any]]) -> None:
    adapter = export(cases[0], tmp_path / 'exports')
    assert nhl_rerun.grade(cases[0], tmp_path / 'exports', adapter, requested=[])['status'] == 'FAIL'
    only_schedule = ['/v1/schedule/2025-10-07']
    assert nhl_rerun.grade(cases[0], tmp_path / 'exports', adapter, requested=only_schedule)['status'] == 'FAIL'


@pytest.mark.parametrize('confirmed', [True, False])
def test_entrypoint_timeout_vs_unknown_execution(tmp_path: Path, cases: list[dict[str, Any]], confirmed: bool) -> None:
    adapter = materialize(tmp_path / 'project')
    def run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        if args[1] == 'exec' and '/bin/sh' in args:
            raise subprocess.TimeoutExpired(args, timeout)
        if args[1] == 'inspect':
            return subprocess.CompletedProcess(args, 0 if confirmed else 1, 'true' if confirmed else '', '')
        return subprocess.CompletedProcess(args, 0, '', '')
    result = nhl_rerun.DockerReplay(IMAGE, IMAGE, run=run).execute(
        tmp_path / 'project', adapter, cases[0], tmp_path / 'evidence')
    assert result['status'] == ('FAIL' if confirmed else 'UNKNOWN')
    assert (tmp_path / 'evidence/execution.json').is_file()
