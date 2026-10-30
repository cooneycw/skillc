"""#568's Docker-only runtime oracle for exact captured remote-main files.

No untrusted source is executed here. The measured attempt image is reused in
an independent, offline, disposable container with no host mounts. Candidate
subprocesses run without privileges under the trusted parent driver.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import inventory_oracle_harness as harness
from . import step6_oracle as transport
from .docker_backend import OWNER_LABEL_KEY, OWNER_LABEL_VALUE, DockerBackend, _docker_env

CONTAINER_SECONDS = 480
MAX_OUTPUT_BYTES = 256 * 1024


def container_argv(docker_bin: Sequence[str], image: str, name: str) -> list[str]:
    return [*docker_bin, 'run', '--rm', '-i', '--name', name, '--network', 'none',
            '--read-only', '--ipc', 'none', '--tmpfs', '/dev/mqueue:ro', '--pull', 'never',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m,mode=1777', '--user', '0:0',
            '--cap-drop', 'ALL', '--cap-add', 'SETUID', '--cap-add', 'SETGID', '--cap-add', 'KILL',
            '--cap-add', 'DAC_OVERRIDE', '--security-opt', 'no-new-privileges',
            '--memory', '256m', '--memory-swap', '256m', '--pids-limit', '64', '--cpus', '1',
            '--label', f'{OWNER_LABEL_KEY}={OWNER_LABEL_VALUE}', '--label', 'skillc.purpose=inventory-oracle',
            '--entrypoint', '/usr/bin/python3', '--workdir', '/', image, '-I', '-S', '-B', '-c',
            Path(harness.__file__).read_text(encoding='utf-8')]


def run(files: Mapping[str, Mapping[str, Any]], backend: object, handle: object, *,
        task_root: Path) -> dict[str, Any]:
    if 'inventory.py' not in files:
        return {'status': 'missing-module'}
    if not isinstance(backend, DockerBackend):
        return {'status': 'unavailable', 'reason': 'inventory oracle requires a Docker backend; no host fallback'}
    captured_env = getattr(handle, 'env', None)
    env = dict(captured_env) if isinstance(captured_env, Mapping) else _docker_env()
    image = backend.image_id(handle)
    if not isinstance(image, str) or not image.startswith('sha256:'):
        return {'status': 'unavailable', 'reason': 'measured attempt image unavailable'}
    try:
        for path, row in files.items():
            if (path.startswith('/') or any(p in ('', '.', '..', '.git') for p in path.split('/'))
                    or row.get('mode') not in ('100644', '100755')):
                return {'status': 'unavailable', 'reason': 'unsupported captured path or mode'}
            base64.b64decode(row['data_b64'], validate=True)
        sources = {rel: base64.b64encode((task_root / rel).read_bytes()).decode('ascii')
                   for rel in ('fixture/inventory.py', 'candidates/reference.py', 'candidates/alternative.py',
                               'candidates/test_import.py', 'fixture/tests/test_legacy.py')}
        nonce = secrets.token_hex(16)
        name = f'skillc-inventory-oracle-{nonce[:12]}'
        job = json.dumps({'files': dict(files), 'engine': (task_root / 'oracle.py').read_text(),
                          'manifest': json.loads((task_root / 'controls.json').read_text()),
                          'sources': sources, 'nonce': nonce})
        argv = container_argv(tuple(backend.docker_bin), image, name)
        try:
            code, output, problem = transport._bounded(argv, job, timeout=CONTAINER_SECONDS,
                                                       limit=MAX_OUTPUT_BYTES, env=env)
        finally:
            subprocess.run([*backend.docker_bin, 'rm', '-f', name],
                           capture_output=True, text=True, timeout=30, check=False, env=env)
            absent = subprocess.run([*backend.docker_bin, 'inspect', name],
                                    capture_output=True, text=True, timeout=30, check=False, env=env)
        # --rm may have already removed the container. The query, not rm's
        # return code, proves absence; a daemon error proves nothing.
        error = absent.stderr.lower()
        confirmed = (absent.returncode != 0 and name in error
                     and ('no such container' in error or 'no such object' in error))
        if not confirmed:
            return {'status': 'unavailable', 'reason': 'oracle container absence unconfirmed'}
        if problem is not None or code != 0:
            return {'status': 'unavailable', 'reason': problem or f'oracle container exit {code}'}
        lines = [line[len(nonce):] for line in output.decode('utf-8').splitlines() if line.startswith(nonce)]
        if len(lines) != 1:
            return {'status': 'unavailable', 'reason': 'oracle result missing or ambiguous'}
        result = json.loads(lines[0])
        if not isinstance(result, dict) or not re.fullmatch(r'[a-z-]+', str(result.get('status'))):
            return {'status': 'unavailable', 'reason': 'malformed oracle result'}
        return result
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'status': 'unavailable', 'reason': f'{type(exc).__name__}: {exc}'}
