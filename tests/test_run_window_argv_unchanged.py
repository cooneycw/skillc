"""The launch-identity capture is read-only (#797 A-2, owner-review condition).

- `compose_run_argv` (which `_keepalive_run_argv` composes) is compared with a
  REVIEWED literal baseline, so a permanent change to the closed flag set
  (C12) fails here, as well as a change made by the capture.
- `docker_backend` must not reference the teardown module.
- The Docker reader issues only `inspect` and `ps`, with the handle's own
  environment, and refuses any other verb before a process starts.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import docker_backend as db

IMAGE = 'sha256:' + 'b' * 64
ARGS: dict[str, Any] = {'docker_bin': ['docker'], 'image': IMAGE, 'name': 'skillc-attempt-x',
                        'attempt_id': 'x', 'subject_argv': ['true'], 'env': {'A': '1'},
                        'network': 'none', 'memory': '1g', 'pids_limit': '64', 'cpus': '1',
                        'shm_size': '64m', 'container_user': '1000:1000', 'disk_limit': None}
#: Reviewed by hand against compose_run_argv at the A-2 base. Update only with
#: a reviewed C12 change.
BASELINE = ['docker', 'run', '--rm', '-i', '--name', 'skillc-attempt-x',
            '--label', 'skillc.managed=true', '--label', 'skillc.attempt-id=x',
            '--network', 'none', '--user', '1000:1000', '--hostname', 'skillc-trial', '--init',
            '--memory', '1g', '--memory-swap', '1g', '--pids-limit', '64', '--cpus', '1', '--shm-size', '64m',
            '-w', '/work', '-e', 'HOME=/home/candidate', '-e', 'A=1', '--', IMAGE, 'true']


def test_compose_run_argv_matches_the_reviewed_baseline_with_capture() -> None:
    assert db.compose_run_argv(**ARGS) == BASELINE
    from test_run_window_teardown import FakeDocker, container_proc

    from skillc import run_window_teardown as rt

    ident = rt.capture_launch_identity('skillc-attempt-x', generation=object(), docker=FakeDocker(),
                                       proc=container_proc())
    assert ident.usable
    assert db.compose_run_argv(**ARGS) == BASELINE
    assert 'run_window' not in Path(db.__file__).read_text()


def test_real_docker_reader_issues_only_inspect_and_ps(monkeypatch: pytest.MonkeyPatch) -> None:
    from skillc import run_window_teardown as rt

    calls: list[tuple[list[str], Any]] = []

    def recording(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), kwargs.get('env')))
        return subprocess.CompletedProcess(argv, 0, stdout='[{"Id": "x"}]', stderr='')

    monkeypatch.setattr(rt.subprocess, 'run', recording)
    reader = rt.RealDocker(['docker'], env={'DOCKER_HOST': 'unix:///handle.sock'})
    reader.inspect('skillc-attempt-x')
    reader.present('c' * 64)
    assert [c[0][:2] for c in calls] == [['docker', 'inspect'], ['docker', 'ps']]
    assert calls[0][0] == ['docker', 'inspect', '--type', 'container', '--', 'skillc-attempt-x']
    assert calls[1][0] == ['docker', 'ps', '-a', '-q', '--no-trunc', '--filter', 'id=' + 'c' * 64]
    assert all(env == {'DOCKER_HOST': 'unix:///handle.sock'} for _, env in calls)
    with pytest.raises(OSError):
        reader._run('rm', '-f', 'x')
    assert len(calls) == 2  # The refused verb never reached subprocess.


def test_teardown_module_never_builds_run_argv() -> None:
    import skillc.run_window_teardown as rt
    text = Path(rt.__file__).read_text()
    for forbidden in ('compose_run_argv', '_keepalive_run_argv', "'run'", "'create'", "'start'", "'exec'",
                      "'rm'", "'kill'", "'stop'"):
        assert forbidden not in text
