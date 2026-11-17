"""Floor-certified cold combined-profile installation; main CI only, no model."""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from profile_project_wave_cold import helper_paths
from profile_project_wave_support import ROOT, inventory

pytestmark = [pytest.mark.real_docker,
              pytest.mark.skipif(shutil.which('docker') is None, reason='main real-Docker CI only'),
              pytest.mark.timeout(600)]


def test_cold_combined_profile_and_missing_helper_control(tmp_path: Path) -> None:
    tag = 'skillc-625-cold:' + uuid.uuid4().hex
    name = 'skillc-625-cold-' + uuid.uuid4().hex
    context = tmp_path / 'context'
    context.mkdir()
    paths = ['skillc', 'tests/profile_project_wave_support.py', 'tests/profile_project_wave_cold.py',
             'tests/fixtures/profile-cpp-codex-flow-auto-87ecb097',
             'tests/fixtures/profile-project-wave-auto-87ecb097-extra',
             'evals/subjects/cpp-codex-project-wave-auto-87ecb097',
             'docker/profile-project-wave-625.Dockerfile']
    for path in paths:
        assert not subprocess.check_output(['git', 'status', '--porcelain', '--', path], cwd=ROOT)
    archive = subprocess.check_output(['git', 'archive', 'HEAD', *paths], cwd=ROOT)
    # Archive paths are the fixed tracked public source list above; no host tree copy.
    subprocess.run(['tar', '-x', '-C', str(context)], input=archive, check=True)
    try:
        subprocess.run(['docker', 'build', '-t', tag, '-f',
                        str(context / 'docker/profile-project-wave-625.Dockerfile'), str(context)],
                       capture_output=True, check=True, timeout=300)
        subprocess.run(['docker', 'create', '--name', name, '--network', 'none', '--read-only',
                        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '64',
                        '--memory', '512m', '--memory-swap', '512m', '--cpus', '1',
                        '--tmpfs', '/proof:rw,nosuid,nodev,size=64m,mode=1777',
                        '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m,mode=1777', tag],
                       capture_output=True, check=True, timeout=30)
        info = json.loads(subprocess.check_output(['docker', 'inspect', name], timeout=30))[0]
        host = info['HostConfig']
        assert not info['Mounts'] and host['NetworkMode'] == 'none' and host['ReadonlyRootfs']
        assert info['Config']['User'] == '65532:65532'
        result = subprocess.run(['docker', 'start', '-a', name], capture_output=True, text=True,
                                check=True, timeout=180)
        row = json.loads(result.stdout)
        inv, _ = inventory()
        assert row['status'] == 'PASS' and row['full_workflow_proven'] is False
        assert [r['helper'] for r in row['helpers']] == helper_paths(inv)
        assert row['missing_helper_control']['result'] == 'FAIL'
        assert row['register_step']['status'] == 'PASS'
        assert len(row['register_step']['helpers']) == 6
        assert row['missing_register_control']['result'] == 'FAIL'
        (tmp_path / 'cold-result.json').write_text(json.dumps(row, indent=2) + '\n')
    finally:
        # Unique names belong solely to this test. Cleanup failure cannot be a green.
        removed = subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30, check=False)
        if removed.returncode:
            listed = subprocess.check_output(['docker', 'ps', '-aq', '--filter', 'name=^/' + name + '$'], timeout=30)
            assert not listed.strip(), 'owned container cleanup unconfirmed'
        subprocess.run(['docker', 'image', 'rm', '-f', tag], capture_output=True, timeout=30, check=True)
