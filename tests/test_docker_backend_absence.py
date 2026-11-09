"""Target-specific Docker confirmation controls; all CLI replies are synthetic."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import docker_backend as db
from skillc.backend import Confirmation

CASES = json.loads((Path(__file__).resolve().parents[1] / 'controls/docker-object-absence/cases.json').read_text())
TARGET = 'CaseSensitiveTarget'
ENV = {'SYNTHETIC_DAEMON': 'fixed'}
FORMATTED = [c for c in CASES['cases'] if c['kind'] == 'container']


def reply(case: dict[str, Any], argv: list[str], formatted: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, case['code'], case['format_out' if formatted else 'plain_out'],
                                       case['stderr'].format(target=TARGET))


def backend(tmp_path: Path) -> db.DockerBackend:
    return db.DockerBackend('fake-image', tmp_path, docker_bin=('fake-docker',), daemon_timeout=1)


@pytest.mark.parametrize('case', FORMATTED, ids=lambda c: c['name'])
@pytest.mark.parametrize('operation', ['inspect', 'absent', 'stopped'])
def test_main_container_confirmation(
    case: dict[str, Any], operation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs['env'] is ENV and kwargs['timeout'] == 1 and kwargs['text']
        calls.append(argv)
        return reply(case, argv, True)

    monkeypatch.setattr(subprocess, 'run', run)
    b = backend(tmp_path)
    handle = db._Handle('synthetic-attempt', TARGET, ENV)
    expected = {'ABSENT': (True, True, None), 'UNKNOWN': (False, False, None),
                'PRESENT': (True, False, case['format_out'].strip())}[case['formatted']]
    public = {'ABSENT': Confirmation.CONFIRMED, 'UNKNOWN': Confirmation.UNKNOWN,
              'PRESENT': Confirmation.NOT_CONFIRMED}[case['formatted']]
    stopped = (Confirmation.CONFIRMED if case['formatted'] == 'PRESENT'
               and case['format_out'].strip() in ('exited', 'dead') else public)
    if operation == 'inspect':
        assert b._inspect(handle) == expected
    elif operation == 'absent':
        assert b.confirm_absent(handle) is public
    else:
        assert b.confirm_stopped(handle) is stopped
    assert calls == [['fake-docker', 'inspect', '--format', '{{.State.Status}}', TARGET]]


def check_auxiliary(case: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                    *, operation: str = 'public') -> None:
    calls = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs['env'] is ENV and kwargs['timeout'] == 1 and kwargs['text']
        calls.append(argv)
        if argv[-1] == 'main-target':
            return subprocess.CompletedProcess(argv, 1, '', 'error: no such object: main-target')
        return reply(case, argv, False)

    monkeypatch.setattr(subprocess, 'run', run)
    b = backend(tmp_path)
    expected = {'ABSENT': True, 'UNKNOWN': None, 'PRESENT': False}[case['plain']]
    handle = db._Handle('synthetic-attempt', 'main-target', ENV,
                        egress_proxy=TARGET if case['kind'] == 'container' else None,
                        egress_network=TARGET if case['kind'] == 'network' else None)
    public = {'ABSENT': Confirmation.CONFIRMED, 'UNKNOWN': Confirmation.UNKNOWN,
              'PRESENT': Confirmation.NOT_CONFIRMED}[case['plain']]
    argv = ['fake-docker', *(['network', 'inspect'] if case['kind'] == 'network' else ['inspect']), TARGET]
    if operation == 'object':
        assert b._object_absent(case['kind'], TARGET, ENV) is expected
        assert calls == [argv]
    else:
        assert b.confirm_absent(handle) is public
        assert calls == [['fake-docker', 'inspect', '--format', '{{.State.Status}}', 'main-target'], argv]


@pytest.mark.parametrize('case', CASES['cases'], ids=lambda c: c['name'])
@pytest.mark.parametrize('operation', ['object', 'public'])
def test_auxiliary_resource_confirmation(
    case: dict[str, Any], operation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_auxiliary(case, tmp_path, monkeypatch, operation=operation)


@pytest.mark.parametrize('failure', ['oserror', 'timeout'])
def test_observation_failure_is_unknown(failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def run(argv: list[str], **_kwargs: Any) -> Any:
        if failure == 'oserror':
            raise OSError('synthetic unavailable CLI')
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(subprocess, 'run', run)
    b = backend(tmp_path)
    h = db._Handle('synthetic-attempt', TARGET, ENV)
    assert b.confirm_stopped(h) is Confirmation.UNKNOWN
    assert b.confirm_absent(h) is Confirmation.UNKNOWN
    assert b._object_absent('container', TARGET, ENV) is None
    assert b._object_absent('network', TARGET, ENV) is None


@pytest.mark.parametrize('control', CASES['qualification_controls'], ids=lambda c: c['predicate'])
def test_absence_predicate_mutants_are_refused(
    control: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    witness = next(c for c in CASES['cases'] if c['name'] == control['witness'])

    def blind(kind: str, name: str, code: int, out: str, err: str, *, formatted: bool) -> bool:
        if control['predicate'] == 'always-absent':
            return True
        return code != 0 and ('no such' in err.lower() or 'not found' in err.lower())

    monkeypatch.setattr(db, '_missing_inspect_reply', blind)
    with pytest.raises(AssertionError):
        check_auxiliary(witness, tmp_path, monkeypatch)


def test_committed_population_is_complete() -> None:
    expected = {'container-legacy', 'container-docker29', 'container-empty-envelope',
                'network-legacy-synthetic', 'network-lowercase-synthetic', 'network-empty-envelope-synthetic',
                'present-running', 'present-exited', 'connect-no-such-file', 'connect-context-not-found',
                'network-context-not-found', 'network-connect-no-such-file', 'missing-certificate',
                'missing-context', 'tls-failure', 'permission-denied', 'daemon-unreachable', 'wrong-target',
                'target-prefix', 'target-suffix', 'wrong-target-case', 'wrong-resource-kind', 'network-wrong-kind',
                'network-wrong-target-case', 'embedded-message', 'multiple-diagnostics', 'quoted-target',
                'conflicting-stdout', 'malformed-stdout', 'array-on-formatted-query', 'signal-ended',
                'unsupported-error-exit', 'zero-is-not-absence'}
    assert len(CASES['cases']) == len(expected) and {c['name'] for c in CASES['cases']} == expected
