"""Physical replay qualification via the existing real-Docker CI selection.

No host daemon/manual run is authorized by this file. No images are built or
pulled: the runner already provides python:3.12-slim. Fixture projects are
trusted authored controls, never live model output or fetched NHL data.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest

from skillc import nhl_rerun, nhl_rerun_control

pytestmark = [pytest.mark.real_docker,
              pytest.mark.skipif(shutil.which('docker') is None, reason='real-Docker CI lane only')]


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['docker', *args], capture_output=True, text=True, check=check, timeout=30)


def container_is_absent(name: str, inspected: subprocess.CompletedProcess[str]) -> bool:
    """The cleanup witness, also exercised without Docker by committed controls."""
    if inspected.returncode != 1:
        return False
    try:
        if json.loads(inspected.stdout) != []:
            return False
    except json.JSONDecodeError:
        return False
    missing = re.fullmatch(
        r'error(?: response from daemon)?:\s*no such (?:object|container):\s*(?P<name>[^\r\n]+)',
        inspected.stderr.strip(), re.IGNORECASE)
    return missing is not None and missing.group('name') == name


@pytest.mark.timeout(1200)
def test_physical_replay_controls_isolation_and_cleanup(tmp_path: Path) -> None:
    docker('info')  # Reachability failure is loud once selected on a Docker runner.
    inspected = json.loads(docker('image', 'inspect', 'python:3.12-slim').stdout)[0]
    assert inspected['RepoDigests'], 'runner preflight image lacks a content pin'
    image = inspected['RepoDigests'][0]
    cases = nhl_rerun.scenarios(*nhl_rerun_control.sample(tmp_path))
    token = 'nhl-witness-' + uuid.uuid4().hex
    witness_network, witness = token, token + '-server'
    docker('network', 'create', '--internal', witness_network)
    try:
        docker('run', '--detach', '--pull=never', '--network', witness_network,
               '--name', witness, '--entrypoint', 'python3', image,
               '-m', 'http.server', '8080')
        present = docker('inspect', witness)
        assert not container_is_absent(witness, present), present
        ip = docker('inspect', '--format', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', witness).stdout.strip()
        assert ip
        sentinel = tmp_path / 'controller-private' / 'sentinel.txt'
        sentinel.parent.mkdir()
        secret = uuid.uuid4().hex
        sentinel.write_text(secret)
        proved = False
        owned: set[str] = set()

        def run(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
            nonlocal proved
            result = nhl_rerun.run_command(args, timeout)
            if args[1] == 'create':
                owned.add(args[args.index('--name') + 1])
            # Probe after the real source-readiness command succeeds. The
            # exact same HTTP/read probes must first succeed on planted access.
            if not proved and args[1] == 'exec' and 'source server unavailable' in args[-1] and result.returncode == 0:
                candidate = args[2]
                http_probe = ('import urllib.request; '
                              f'assert urllib.request.urlopen("http://{ip}:8080",timeout=2).status == 200')
                docker('network', 'connect', witness_network, candidate)
                try:
                    docker('exec', candidate, 'python3', '-c', http_probe)
                finally:
                    docker('network', 'disconnect', witness_network, candidate)
                assert docker('exec', candidate, 'python3', '-c', http_probe, check=False).returncode != 0
                # Known-bad custody input: explicitly copied private file is
                # readable. Remove it, prove absence, then attempt a write at
                # that same absolute path; the controller's bytes must survive.
                parent = str(sentinel.parent)
                probe = f'from pathlib import Path;assert Path({str(sentinel)!r}).read_text()=={secret!r}'
                docker('exec', candidate, 'python3', '-c', f'from pathlib import Path;Path({parent!r}).mkdir(parents=True)')
                docker('cp', str(sentinel), f'{candidate}:{sentinel}')
                docker('exec', candidate, 'python3', '-c', probe)
                docker('exec', candidate, 'python3', '-c', f'from pathlib import Path;Path({str(sentinel)!r}).unlink()')
                assert docker('exec', candidate, 'python3', '-c', probe, check=False).returncode != 0
                docker('exec', candidate, 'python3', '-c', f'from pathlib import Path;Path({str(sentinel)!r}).write_text("candidate write")')
                assert sentinel.read_text() == secret
                proved = True
            return result

        selections = [('reference', case) for case in cases]
        selections += [('strict', cases[1]), ('drop-fields', cases[1])]
        selections += [('never-discrepancy', case) for case in cases[2:]]
        selections += [('alternate-date', cases[0])]
        for index, (mode, case) in enumerate(selections):
            project = tmp_path / f'project-{index}'
            adapter = nhl_rerun_control.materialize(project)
            command = f'CONTROL_MODE={mode} python3 project.py'
            (project / 'README.md').write_text(f'Set NHL_API_BASE then run:\n{command}\n')
            adapter['commands'] = [command]
            paths = ['/v1/schedule/' + ('2025-10-08' if mode == 'alternate-date' else '2025-10-07')]
            for identity in sorted(case['expected']):
                paths.extend(nhl_rerun.route(nhl_rerun.snapshot.endpoint(source, identity))
                             for source in nhl_rerun.snapshot.SOURCE_IDS)
            adapter['payloads'] = {path: f'payload-{i}.json' for i, path in enumerate(paths)}
            result = nhl_rerun.DockerReplay(image, image, timeout=120, run=run).execute(
                project, adapter, case, tmp_path / f'evidence-{index}')
            assert result['status'] == ('PASS' if mode in ('reference', 'alternate-date') else 'FAIL'), result
        assert proved, 'physical isolation probes never executed'
        docker('info')
        for name in owned:
            absent = docker('inspect', name, check=False)
            assert container_is_absent(name, absent), absent
        for path in tmp_path.glob('evidence-*/execution.json'):
            execution: dict[str, Any] = json.loads(path.read_text())
            network = execution['commands'][0]['stdout'].strip()
            absent = docker('network', 'inspect', network, check=False)
            assert absent.returncode != 0 and 'not found' in absent.stderr.lower(), absent
    finally:
        docker('rm', '-f', witness, check=False)
        docker('network', 'rm', witness_network, check=False)
