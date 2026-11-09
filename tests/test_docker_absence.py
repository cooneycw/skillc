"""Docker wording regression controls, with every subprocess intercepted."""
from __future__ import annotations

import builtins
import json
import subprocess
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ci import load_harness
from skillc import reap, trial_bootstrap
from skillc.docker_backend import DockerBackend

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'controls/docker-absence/cases.json').read_text())
ID = 'a' * 64


@pytest.mark.parametrize('case', CASES['inspect'], ids=lambda c: c['name'])
def test_target_presence_reply(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        assert kwargs['capture_output'] and kwargs['text'] and kwargs['timeout'] == 1
        return subprocess.CompletedProcess(argv, case['code'], case['stdout'].format(id=ID),
                                           case['stderr'].format(id=ID))

    monkeypatch.setattr(subprocess, 'run', run)
    assert reap._target_present(('fake-docker',), case['kind'], ID, {}, 1) is case['present']
    expected = ['fake-docker', *(['network', 'inspect'] if case['kind'] == 'network' else ['inspect']),
                '--format', '{{.Id}}', ID]
    assert calls == [expected]


@pytest.mark.parametrize('case', CASES['inspect'], ids=lambda c: c['name'])
def test_public_reap_preserves_absence_vs_unknown(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    # A complete initial inventory selects exactly this immutable target. The
    # final label inventory is empty; the independent target check is decisive.
    inventories: Iterator[tuple[dict[str, dict[str, tuple[str, ...]]], set[str], bool]] = iter([
                        ({'selected': {'container': (ID,) if case['kind'] == 'container' else (),
                                       'network': (ID,) if case['kind'] == 'network' else ()}}, set(), True),
                        ({'selected': {'container': (), 'network': ()}}, set(), True)])
    monkeypatch.setattr(reap, '_inventory', lambda *_a: next(inventories))
    actions = []

    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if 'rm' in argv:
            actions.append(argv)
            return subprocess.CompletedProcess(argv, 0, ID + '\n', '')
        return subprocess.CompletedProcess(argv, case['code'], case['stdout'].format(id=ID),
                                           case['stderr'].format(id=ID))

    monkeypatch.setattr(subprocess, 'run', run)
    report = reap.reap(('fake-docker',), ['selected'], timeout=1)
    assert len(actions) == 1
    assert report.daemon_reachable is (case['present'] is not None)
    expected = ('unknown' if case['present'] is None else 'reaped' if not case['present'] else
                'left-running' if case['kind'] == 'container' else 'left-present')
    assert report.outcome_for('selected') == expected


@pytest.mark.parametrize('site', ['backend', 'probe', 'harness'])
@pytest.mark.parametrize('case', CASES['remove'], ids=lambda c: c['name'])
def test_cleanup_missing_container_wording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, site: str, case: dict[str, Any],
) -> None:
    calls = []
    listings = iter([ID + '\n', '', '', ''])

    def run(argv: list[str], **kwargs: Any) -> Any:
        calls.append(argv)
        if 'ps' in argv:
            return subprocess.CompletedProcess(argv, 0, next(listings), '')
        assert argv == ['fake-docker', 'rm', '-f', ID] or argv == ['docker', 'rm', '-f', ID]
        message = case['stderr'].format(id=ID)
        return subprocess.CompletedProcess(argv, case['code'], '' if kwargs.get('text') else b'',
                                           message if kwargs.get('text') else message.encode())

    monkeypatch.setattr(subprocess, 'run', run)
    if site == 'backend':
        result = DockerBackend('fake-image', tmp_path, docker_bin=('fake-docker',))._best_effort_rm(ID, {})
    elif site == 'probe':
        result = trial_bootstrap._remove_probe_container(('fake-docker',), ID, 1)
    else:
        # Exercise the actual embedded cleanup body, with a local clock that
        # skips sleeps. No load workers, real docker client or host action runs.
        def importer(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == 'time':
                return types.SimpleNamespace(monotonic=lambda: 0, sleep=lambda _t: None)
            return builtins.__import__(name, *args, **kwargs)

        namespace: dict[str, Any] = {'__builtins__': {**vars(builtins), '__import__': importer}}
        exec(load_harness._CLEANUP_SRC, namespace)  # noqa: S102 - repository-owned constant, fake I/O only
        result = namespace['cleanup']({'docker': True, 'label': 'synthetic', 'docker_settle': 0, 'iodir': None})
        assert len([c for c in calls if 'ps' in c]) == 4
    assert bool(result) is not case['clean']
