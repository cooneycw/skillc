"""Committed trusted NHL replay qualification; never execute delivered code locally."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from . import nhl_oracle, nhl_rerun, nhl_serve, nhl_snapshot

ROOT = Path(__file__).resolve().parents[1]
CONTROLS = ROOT / 'controls' / 'nhl-rerun'


def sample(tmp_path: Path) -> tuple[Path, str, list[int], list[dict[str, Any]]]:
    original = json.loads((ROOT / 'controls/nhl-reference/good/sources.json').read_text())
    ids = [original['game']['id'], original['game']['id'] - 1]
    responses = {}
    games = []
    for identity in ids:
        data = copy.deepcopy(original)
        data['game']['id'] = identity
        games.append(data['game'])
        for source in nhl_snapshot.SOURCE_IDS:
            data[source]['id'] = identity
            responses[nhl_snapshot.endpoint(source, identity)] = json.dumps(data[source]).encode()
    responses[nhl_snapshot.endpoint('schedule', '2025-10-07')] = json.dumps(
        {'gameWeek': [{'date': '2025-10-07', 'games': games}]}).encode()
    root = tmp_path / 'snapshot'
    nhl_snapshot.acquire(root, '2025-10-07', '2025-10-07', fetch=responses.__getitem__)
    recipes = json.loads((ROOT / 'controls/nhl-reference/bad/cases.json').read_text())
    plants = []
    for recipe in recipes:
        if recipe['mutation'] == 'source_mismatch':
            path = recipe['path']
            value = original
            for key in path:
                value = value[key]
            plants.append({'family_id': recipe['family_id'], 'game_id': ids[0],
                           'source_id': path[0], 'path': path[1:], 'before': value,
                           'after': recipe['value']})
    return root, nhl_snapshot.sha256((root / 'manifest.json').read_bytes()), ids, plants


def materialize(project: Path) -> dict[str, Any]:
    project.mkdir()
    shutil.copy(CONTROLS / 'project.py', project)
    package = project / 'oracle'
    package.mkdir()
    (package / '__init__.py').touch()
    for module in (nhl_oracle, nhl_snapshot):
        shutil.copy(str(module.__file__), package)
    (project / 'README.md').write_text('Set NHL_API_BASE then run:\npython3 project.py\n')
    return {'readme': 'README.md', 'commands': ['python3 project.py'], 'base_env': 'NHL_API_BASE',
            'export_dir': '/project/exports', 'reconciliation': 'reconciliation.json'}


def actual_control(project: Path, mode: str, case: dict[str, Any]) -> dict[str, Any]:
    """Only the committed trusted reference fixture runs locally, never subject code."""
    adapter = materialize(project)
    paths = ['/v1/schedule/2025-10-07']
    for identity in sorted(case['expected']):
        paths.extend(nhl_rerun.route(nhl_snapshot.endpoint(source, identity)) for source in nhl_snapshot.SOURCE_IDS)
    with nhl_serve.make_server(case['payloads'], '127.0.0.1', 0) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            completed = subprocess.run([sys.executable, 'project.py'], cwd=project,
                env={**os.environ, 'NHL_API_BASE': f'http://127.0.0.1:{server.server_port}',
                     'CONTROL_MODE': mode}, capture_output=True, text=True, timeout=20, check=False)
        finally:
            server.shutdown()
            worker.join()
    if completed.returncode:
        return {'status': 'FAIL', 'reasons': [completed.stderr]}
    adapter['payloads'] = {path: f'payload-{index}.json' for index, path in enumerate(paths)}
    return nhl_rerun.grade(case, project / 'exports', adapter)


def qualify() -> dict[str, Any]:
    matrix = json.loads((CONTROLS / 'cases.json').read_text())
    required = [('reference', 'all', 'PASS'), ('strict', 'drift', 'FAIL'),
                ('drop-fields', 'drift', 'FAIL'), ('never-discrepancy', 'F1-F8', 'FAIL')]
    if [(c['mode'], c['scenario'], c['expected']) for c in matrix] != required:
        raise nhl_snapshot.ReferenceError('replay qualification control population differs')
    observations = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        cases = nhl_rerun.scenarios(*sample(root))
        for control in matrix:
            chosen = cases if control['scenario'] == 'all' else [c for c in cases if
                c['name'] == control['scenario'] or (control['scenario'] == 'F1-F8' and c['name'].startswith('F'))]
            if not chosen:
                raise nhl_snapshot.ReferenceError('empty replay control selection')
            for case in chosen:
                project = root / f"{control['mode']}-{case['name']}"
                actual = actual_control(project, control['mode'], case)['status']
                if actual != control['expected']:
                    raise nhl_snapshot.ReferenceError(f"replay qualifier blind/noisy: {control['mode']}/{case['name']}: {actual}")
                observations.append({'mode': control['mode'], 'scenario': case['name'], 'status': actual})
    return {'status': 'PASS', 'controls': observations}
