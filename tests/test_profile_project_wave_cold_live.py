"""Opt-in physical command proof. Default skips are never cold evidence."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from test_profile_flow_auto_87ecb097_cold import (
    Budget,
    cleanup_owned,
    failure_diagnostic,
    need,
    settings,
    stage_context,
)
from test_profile_project_wave import CONTROLS, ROOT, check_source

CASES: list[str] = json.loads((CONTROLS / 'cold-cases.json').read_text())
EXPECTED: dict[str, int] = json.loads((CONTROLS / 'expected-observations.json').read_text())


def case_population(rows: list[dict[str, Any]]) -> None:
    need(list(EXPECTED) == CASES and len(set(CASES)) == 10, 'nonempty declared cold case population')
    need([row['case'] for row in rows] == CASES, 'cold executed case population')
    for row in rows:
        need(not row.get('skipped') and len(row.get('observations', [])) == EXPECTED[row['case']],
             'cold executed observation population')


def require_cleanup(rows: list[dict[str, Any]]) -> None:
    need(bool(rows) and all(row.get('absent') is True for row in rows), 'cleanup not independently confirmed')


def cold_proof(tmp: Path) -> dict[str, Any]:
    """One source-bound budget, no operator bind mounts or live services."""
    budget = Budget(tmp, reserve=120)
    nonce = uuid.uuid4().hex
    containers: list[str] = []
    tags: list[str] = []
    rows: list[dict[str, Any]] = []
    identities: dict[str, Any] = {}
    cleanup: list[dict[str, Any]] = []
    context = tmp / 'context'
    context.mkdir()

    def ownership() -> None:
        (tmp / 'owned.json').write_text(json.dumps({'nonce': nonce, 'containers': containers,
            'tags': tags, 'identities': identities}, indent=2) + '\n')

    ownership()
    try:
        paths = ['skillc', 'tests/test_profile_flow_auto_87ecb097_cold.py',
                 'tests/test_profile_project_wave.py', 'tests/test_profile_project_wave_cold_live.py',
                 'tests/profile_project_wave_cold_actor.py',
                 'tests/fixtures/profile-cpp-codex-project-wave-auto-87ecb097',
                 'evals/subjects/cpp-codex-project-wave-auto-87ecb097',
                 'controls/profile-project-wave', 'docker/profile-project-wave/Dockerfile',
                 'docker/fixture-service/skillc-gh-shim.py']
        for path in paths:
            rc, out, _ = budget.command(['git', 'status', '--porcelain', '--', path], cwd=ROOT)
            need(rc == 0 and not out, 'build sources must be committed and clean')
        rc, head, _ = budget.command(['git', 'rev-parse', 'HEAD'], cwd=ROOT)
        need(rc == 0, 'source commit unavailable')
        identities['commit'] = head.strip()
        check_source()
        identities['source_files'] = stage_context(budget, context, paths, ROOT)
        tag = 'skillc-project-wave-' + nonce + ':cold'
        tags.append(tag)
        identities['build'] = 'active or cancellation unconfirmed'
        ownership()
        rc, _, err = budget.command(['docker', 'build', '--label', 'skillc.b3a=' + nonce,
            '-t', tag, '-f', str(context / 'docker/profile-project-wave/Dockerfile'), str(context)], 300)
        need(rc == 0, 'image build unavailable: ' + err[-500:])
        rc, out, _ = budget.command(['docker', 'image', 'inspect', tag])
        image = json.loads(out)[0]
        need(rc == 0 and image['Config']['Labels']['skillc.b3a'] == nonce, 'owned image identity')
        identities.update(image=image['Id'], build='completed')
        ownership()
        for case in CASES:
            case_end = min(budget.work_deadline, time.monotonic() + 90)
            name = 'skillc-project-wave-' + nonce + '-' + str(len(containers))
            containers.append(name)
            ownership()
            argv = ['docker', 'create', '--name', name, '--label', 'skillc.b3a=' + nonce,
                    '--network', 'none', '--read-only', '--memory', '512m', '--memory-swap', '512m',
                    '--cpus', '1', '--pids-limit', '128', '--tmpfs', '/home/proof:rw,size=256m',
                    '--tmpfs', '/work:rw,size=256m', '--tmpfs', '/project:rw,size=32m',
                    '--tmpfs', '/tmp:rw,size=64m', '-e', 'HOME=/home/proof',
                    '-e', 'SKILLC_PROJECT_WAVE_ACTOR=1']
            if case == 'forbidden-bind':
                sentinel = tmp / 'synthetic-sentinel'
                sentinel.write_text('owned control, no operator data')
                argv += ['--mount', 'type=bind,source=' + str(sentinel) + ',target=/sentinel,readonly']
            argv += [image['Id'], 'python', '/opt/controller/tests/profile_project_wave_cold_actor.py', case]
            rc, out, _ = budget.command(argv, min(30, case_end - time.monotonic()))
            need(rc == 0 and bool(out.strip()), 'container allocation unavailable')
            rc, out, _ = budget.command(['docker', 'inspect', name], min(30, case_end - time.monotonic()))
            observed = json.loads(out)[0]
            need(rc == 0 and observed['Config']['Labels']['skillc.b3a'] == nonce, 'container ownership')
            if case == 'forbidden-bind':
                with pytest.raises(RuntimeError, match='forbidden bind'):
                    settings(observed, True)
                rows.append({'case': case, 'observations': [{'negative': 'actual synthetic bind refused'}]})
                continue
            settings(observed)
            rc, out, err = budget.command(['docker', 'start', '-a', name], min(90, case_end - time.monotonic()))
            need(rc == 0, 'cold actor unavailable: ' + err[-1000:] + out[-1000:])
            row = json.loads(out)
            need(row['case'] == case and time.monotonic() < case_end, 'cold case identity/deadline')
            rows.append(row)
    finally:
        cleanup = cleanup_owned(budget, containers, tags, nonce)
        failure_diagnostic(tmp / 'cold-diagnostic.json', {'identities': identities, 'cleanup': cleanup,
            'partial_cases': [{'case': r['case'], 'observations': len(r.get('observations', []))} for r in rows]})
    require_cleanup(cleanup)
    case_population(rows)
    report = {'scope': 'bounded cold installation and commands; native workflow unproven',
              'identities': identities, 'cases': rows, 'cleanup': cleanup, 'commands': budget.events}
    budget.publish(tmp / 'cold-report.json', report)
    return report


@pytest.mark.real_docker
@pytest.mark.xdist_group(name='real_docker')
@pytest.mark.timeout(1900)
@pytest.mark.skipif(os.environ.get('SKILLC_PROJECT_WAVE_COLD') != '1',
                    reason='opt-in physical combined-profile proof needs an operator Docker slot')
def test_bounded_cold_project_wave_commands(tmp_path: Path) -> None:
    cold_proof(tmp_path)


@pytest.mark.parametrize('fault', ['empty', 'missing', 'duplicate', 'skipped', 'observation'])
def test_population_controls_refuse_incomplete_proof(fault: str) -> None:
    rows: list[dict[str, Any]] = [{'case': name, 'observations': [{}] * EXPECTED[name]} for name in CASES]
    case_population(rows)
    if fault == 'empty':
        rows = []
    elif fault == 'missing':
        rows.pop()
    elif fault == 'duplicate':
        rows[-1] = rows[0]
    elif fault == 'skipped':
        rows[0]['skipped'] = True
    else:
        rows[0]['observations'].pop()
    with pytest.raises(RuntimeError):
        case_population(rows)


@pytest.mark.parametrize('rows', [[], [{'absent': False}], [{'absent': None}], [{}]])
def test_cleanup_opposites_cannot_publish_success(rows: list[dict[str, Any]]) -> None:
    require_cleanup([{'absent': True}])
    with pytest.raises(RuntimeError, match='cleanup'):
        require_cleanup(rows)
