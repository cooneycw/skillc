"""The launch-identity capture is read-only (#797 A-2, owner-review condition).

`compose_run_argv` (which `_keepalive_run_argv` composes) must be
byte-identical with and without the teardown module in play, `docker_backend`
must not reference it, and the capture must issue no Docker
verb beyond `inspect` and `ps`. A mutating verb is refused before any process
starts.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import docker_backend as db

ARGS: dict[str, Any] = dict(docker_bin=['docker'], image='sha256:' + 'b' * 64, name='skillc-attempt-x',
                            attempt_id='x', subject_argv=['true'], env={'A': '1'}, network='none',
                            memory='1g', pids_limit='64', cpus='1', shm_size='64m', container_user='1000:1000',
                            disk_limit=None)


def test_compose_run_argv_is_byte_identical_with_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    before = db.compose_run_argv(**ARGS)
    from skillc import run_window_teardown as rt
    from test_run_window_teardown import FakeDocker, container_proc

    ident = rt.capture_launch_identity('skillc-attempt-x', generation=object(), docker=FakeDocker(),
                                       proc=container_proc())
    assert ident.usable
    assert db.compose_run_argv(**ARGS) == before
    assert 'run_window' not in Path(db.__file__).read_text()


def test_real_docker_reader_issues_only_inspect_and_ps(monkeypatch: pytest.MonkeyPatch) -> None:
    from skillc import run_window_teardown as rt

    calls: list[list[str]] = []

    def recording(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout='[{"Id": "x"}]', stderr='')

    monkeypatch.setattr(rt.subprocess, 'run', recording)
    reader = rt.RealDocker(['docker'], env={})
    reader.inspect('skillc-attempt-x')
    reader.present('c' * 64)
    assert [c[1] for c in calls] == ['inspect', 'ps']
    with pytest.raises(OSError):
        reader._run('rm', '-f', 'x')
    assert len(calls) == 2  # The refused verb never reached subprocess.


def test_teardown_module_never_builds_run_argv() -> None:
    import skillc.run_window_teardown as rt
    text = Path(rt.__file__).read_text()
    for forbidden in ('compose_run_argv', '_keepalive_run_argv', "'run'", "'create'", "'start'", "'exec'"):
        assert forbidden not in text
