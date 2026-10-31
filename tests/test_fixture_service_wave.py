"""Project creation and wave issue mutations through the real fixture channel (#636)."""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_fixture_service import World, _git, ask
from test_fixture_service_channel import Harness

from skillc import fixture_service as fs
from skillc.decide_reply_channel import DecideReplyChannel

INVENTORY = Path(__file__).resolve().parent.parent / 'docs/specs/evaluation-facility/fixture-service-wave-gh-inventory.json'

@pytest.fixture(autouse=True)
def controller_umask() -> Iterator[None]:
    old = os.umask(0o022)
    yield
    os.umask(old)

@pytest.fixture
def wave(tmp_path: Path) -> Iterator[Harness]:
    world = World(tmp_path)
    service = world.service()
    with tempfile.TemporaryDirectory(prefix='wave-gh-') as short:
        sock = Path(short) / 'trigger.sock'
        channel = DecideReplyChannel(sock, fs.dispatch({'gh': (service.decide, fs.REQUEST_KEYS)}), 'attempt-1')
        channel.start()
        try:
            yield Harness(world, service, sock)
        finally:
            channel.stop_and_finalize()


def test_identity_available_before_origin_exists(wave: Harness, tmp_path: Path) -> None:
    result = wave.shim('api', 'user', cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['login'] == fs.SUBJECT_LOGIN
    assert wave.service.finalize('attempt-1').events[-1]['decision'] == 'read'


def test_issue_create_edit_stdin_and_label_are_controller_owned(wave: Harness) -> None:
    made_label = wave.shim('label', 'create', 'bug', '--color', 'd73a4a', '--description', 'Fixture bug')
    assert made_label.returncode == 0, made_label.stderr
    labels = wave.shim('label', 'list', '--json', 'name,color,description', '--limit', '100')
    assert {'name': 'bug', 'color': 'd73a4a', 'description': 'Fixture bug'} in json.loads(labels.stdout)
    made = wave.shim('issue', 'create', '--title', 'T001: fixture', '--body', 'original', '--label', 'bug')
    assert made.returncode == 0, made.stderr
    assert made.stdout.endswith('/issues/4\n')
    edit = wave.shim('issue', 'edit', '4', '--body-file', '-', stdin='original\n\nBlocked by #3\n')
    assert edit.returncode == 0, edit.stderr
    view = wave.shim('issue', 'view', '4', '--json', 'number,title,body,labels')
    assert json.loads(view.stdout) == {'number': 4, 'title': 'T001: fixture',
        'body': 'original\n\nBlocked by #3\n', 'labels': [{'name': 'bug'}]}
    record = wave.service.finalize('attempt-1')
    assert [e['op'] for e in record.events] == ['label.create', 'label.list', 'issue.create', 'issue.edit', 'issue.view']
    assert [e['decision'] for e in record.events] == ['applied', 'read', 'applied', 'applied', 'read']
    assert record.events[2]['effect']['number'] == 4
    assert record.events[2]['state_before'] != record.events[2]['state_after']
    assert record.events[3]['reply']['stdout'] == edit.stdout


def test_created_issue_does_not_escape_attempt(wave: Harness) -> None:
    made = wave.shim('issue', 'create', '--title', 'private attempt issue', '--body', 'one')
    assert made.returncode == 0, made.stderr
    other = fs.FixtureService(wave.world.declaration(), wave.world.remote, 'attempt-2')
    result = ask(other, 'issue', 'view', '4', '--json', 'title')
    assert result['exit_code'] != 0
    assert other.finalize('attempt-2').events[-1]['reason'] == 'not-found'
    assert '4' in wave.service.finalize('attempt-1').final_state['issues']


def test_issue_unknown_label_refuses_without_consuming_number(wave: Harness) -> None:
    bad = wave.shim('issue', 'create', '--title', 'unknown label', '--body', 'x', '--label', 'missing')
    assert bad.returncode != 0
    good = wave.shim('issue', 'create', '--title', 'plain', '--body', 'x')
    assert good.returncode == 0, good.stderr
    assert good.stdout.endswith('/issues/4\n')
    events = wave.service.finalize('attempt-1').events
    assert events[0]['reason'] == 'unknown-label'
    assert events[0]['state_before'] == events[0]['state_after']


def test_pinned_merge_refuses_stale_head_without_mutation(wave: Harness) -> None:
    assert wave.shim('pr', 'create', '--title', 'fixture', '--body', 'Refs #3').returncode == 0
    bad = wave.shim('pr', 'merge', '4', '--squash', '--match-head-commit', '0' * 40)
    assert bad.returncode != 0
    event = wave.service._events[-1]
    assert event['reason'] == 'head-mismatch'
    assert event['state_before'] == event['state_after']
    head = _git(wave.world.work, 'rev-parse', 'HEAD')
    good = wave.shim('pr', 'merge', '4', '--squash', '--match-head-commit', head)
    assert good.returncode == 0, good.stderr
    assert wave.service.finalize('attempt-1').remote_integrity == 'SATISFIED'


@pytest.mark.parametrize('argv', [
    ['issue', 'create', '--title', 'x', '--unknown-option'],
    ['label', 'create', 'bug', '--unknown-option'],
    ['repo', 'create', 'widget', '--private', '--unknown-option'],
    ['release', 'create', 'v1'],
])
def test_unknown_flags_and_operations_are_recorded(wave: Harness, argv: list[str]) -> None:
    assert wave.shim(*argv).returncode != 0
    record = wave.service.finalize('attempt-1')
    assert not record.coverage_complete
    assert record.events[-1]['decision'] == 'unsupported'
    assert record.events[-1]['state_before'] == record.events[-1]['state_after']


def test_pending_repository_create_pushes_real_source_and_records_observed_head(tmp_path: Path) -> None:
    bare = tmp_path / 'remote.git'
    bare.mkdir()
    _git(bare, 'init', '--bare', '-q')
    source = tmp_path / 'source'
    source.mkdir()
    _git(source, 'init', '-q')
    (source / 'README').write_text('created project\n')
    _git(source, 'add', 'README')
    _git(source, 'commit', '-qm', 'initial')
    head = _git(source, 'rev-parse', 'HEAD')
    declaration: dict[str, Any] = {
        'fixture_service_schema': 1,
        'repository': {'name_with_owner': 'fixture/widget', 'default_branch': 'main',
            'remote_urls': [str(bare)], 'exists': False, 'creation_transport_url': str(bare)},
        'authority': list(fs.OPS), 'clock': {'start': '2026-10-17T00:00:00Z'},
    }
    service = fs.FixtureService(declaration, fs.LocalGitRemote(bare), 'attempt-1')
    with tempfile.TemporaryDirectory(prefix='create-gh-') as short:
        sock = Path(short) / 'trigger.sock'
        channel = DecideReplyChannel(sock, fs.dispatch({'gh': (service.decide, fs.REQUEST_KEYS)}), 'attempt-1')
        channel.start()
        try:
            # Harness uses only .work for cwd; no World setup may seed this empty remote.
            world = object.__new__(World)
            world.work = source
            h = Harness(world, service, sock)
            wrong = h.shim('repo', 'create', 'other', '--private', '--source=.', '--push')
            assert wrong.returncode != 0
            assert service._remote.resolve('refs/heads/main') is None
            made = h.shim('repo', 'create', 'widget', '--private', '--source=.', '--push')
            assert made.returncode == 0, made.stderr
            assert _git(source, 'config', '--get', 'remote.origin.url') == str(bare)
            assert _git(source, 'rev-parse', '--abbrev-ref', '@{upstream}') == 'origin/main'
            assert service._remote.resolve('refs/heads/main') == head
            duplicate = h.shim('repo', 'create', 'widget', '--private', '--source=.', '--push')
            assert duplicate.returncode != 0
        finally:
            channel.stop_and_finalize()
    record = service.finalize('attempt-1')
    applied = [e for e in record.events if e['decision'] == 'applied']
    assert len(applied) == 1
    assert applied[0]['op'] == 'repo.create'
    assert applied[0]['effect']['head_oid'] == head
    assert record.remote_integrity == 'SATISFIED'
    assert record.final_state['repository']['exists'] is True


@pytest.mark.skipif(fs.measure_jq()[0] is None, reason='jq 1.7.x unavailable')
def test_new_pinned_converter_filter_evaluates_actual_body(wave: Harness) -> None:
    inv = json.loads(INVENTORY.read_text())
    argv = next(c['argv'] for c in inv['extension_cases'] if c['source'] == 'scripts/speckit-tasks-to-issues.sh:369')
    result = wave.shim(*argv)
    assert result.returncode == 0, result.stderr
    assert all(len(row.split('\x1f')) == 5 for row in result.stdout.splitlines())
    assert {row.split('\x1f')[0] for row in result.stdout.splitlines()} == {'1', '3'}


def test_pinned_converter_creates_dependencies_and_reruns_without_duplicates(wave: Harness, tmp_path: Path) -> None:
    import hashlib
    import shutil
    import subprocess
    import sys
    fixture = Path(__file__).parent / 'fixtures/fixture-service-wave-87ecb097'
    provenance = json.loads((fixture / 'provenance.json').read_text())
    for name, digest in provenance['files'].items():
        assert hashlib.sha256((fixture / name).read_bytes()).hexdigest() == digest
    # Its URL guard sees a GitHub-shaped logical URL; no command may use that URL
    # for transport. gh resolves explicitly to the controller's one repository.
    _git(wave.world.work, 'remote', 'set-url', 'origin', 'https://github.com/fixture/widget.git')
    tasks = wave.world.work / '.specify/specs/widget/tasks.md'
    tasks.parent.mkdir(parents=True)
    tasks.write_text('# Tasks\n\n- [ ] T001 Implement first task\n- [ ] T002 Implement second task (depends on T001)\n')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    from test_fixture_service_channel import SHIM
    shim = bin_dir / 'gh'
    shim.write_text('#!' + sys.executable + '\n' + SHIM.read_text().split('\n', 1)[1])
    shim.chmod(0o755)
    env = {'PATH': str(bin_dir) + ':/usr/bin:/bin', 'SKILLC_TRIGGER_SOCKET': str(wave.socket_path),
           'HOME': str(wave.world.work), 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
    runtime = tmp_path / 'converter'
    runtime.mkdir()
    shutil.copy2(fixture / 'scripts/speckit-tasks-to-issues.sh', runtime)
    helper = Path(__file__).parent.parent / provenance['context_helper']['fixture_path']
    assert hashlib.sha256(helper.read_bytes()).hexdigest() == provenance['context_helper']['sha256']
    shutil.copy2(helper, runtime / 'speckit-context.py')
    argv = ['bash', str(runtime / 'speckit-tasks-to-issues.sh'),
            '--tasks', str(tasks), '--repo', 'fixture/widget']
    for _ in range(2):
        run = subprocess.run(argv, cwd=wave.world.work, env=env, capture_output=True,
                             text=True, timeout=30, check=False)
        assert run.returncode == 0, run.stdout + run.stderr
    record = wave.service.finalize('attempt-1')
    creates = [e for e in record.events if e['op'] == 'issue.create' and e['decision'] == 'applied']
    assert len(creates) == 2
    assert 'Blocked by #4' in record.final_state['issues']['5']['body']
    assert any(e['op'] == 'issue.edit' and e['decision'] == 'applied' for e in record.events)
    assert record.coverage_complete


@pytest.fixture
def pending(tmp_path: Path) -> Iterator[Harness]:
    bare = tmp_path / 'empty.git'
    bare.mkdir()
    _git(bare, 'init', '--bare', '-q')
    source = tmp_path / 'new-project'
    source.mkdir()
    _git(source, 'init', '-q')
    (source / 'README').write_text('new project\n')
    _git(source, 'add', '.')
    _git(source, 'commit', '-qm', 'initial')
    declaration = {'fixture_service_schema': 1,
        'repository': {'name_with_owner': 'fixture/widget', 'default_branch': 'main',
            'remote_urls': [str(bare)], 'exists': False, 'creation_transport_url': str(bare)},
        'authority': list(fs.OPS), 'clock': {'start': '2026-10-17T00:00:00Z'}}
    service = fs.FixtureService(declaration, fs.LocalGitRemote(bare), 'attempt-1')
    world = object.__new__(World)
    world.work, world.bare = source, bare
    with tempfile.TemporaryDirectory(prefix='pending-gh-') as short:
        sock = Path(short) / 'trigger.sock'
        channel = DecideReplyChannel(sock, fs.dispatch({'gh': (service.decide, fs.REQUEST_KEYS)}), 'attempt-1')
        channel.start()
        try:
            yield Harness(world, service, sock)
        finally:
            channel.stop_and_finalize()


def test_source_configuration_failure_never_records_creation(pending: Harness) -> None:
    _git(pending.world.work, 'remote', 'add', 'origin', '/different/fixture.git')
    result = pending.shim('repo', 'create', 'widget', '--private', '--source=.', '--push')
    assert result.returncode != 0
    record = pending.service.finalize('attempt-1')
    assert [e['decision'] for e in record.events] == ['read', 'refused']
    assert record.events[-1]['reason'] == 'source-push-failed'
    assert not record.final_state['repository']['exists']
    assert record.remote_integrity == 'SATISFIED'


def test_unprepared_creation_cannot_adopt_unrecorded_push(pending: Harness) -> None:
    head = _git(pending.world.work, 'rev-parse', 'HEAD')
    _git(pending.world.work, 'push', str(pending.world.bare), 'HEAD:refs/heads/main')
    reply = pending.raw({'op': 'gh', 'argv': ['repo', 'create', 'widget', '--private', '--source=.', '--push'],
        'context': {'source_head': head, 'creation_phase': 'complete'}})
    assert reply['result']['exit_code'] != 0
    record = pending.service.finalize('attempt-1')
    assert record.events[-1]['reason'] == 'creation-not-prepared'
    assert not record.final_state['repository']['exists']
    assert record.remote_integrity == 'VIOLATED'


def test_creation_completion_requires_observed_ref(pending: Harness) -> None:
    argv = ['repo', 'create', 'widget', '--private', '--source=.', '--push']
    context = {'source_head': _git(pending.world.work, 'rev-parse', 'HEAD'), 'creation_phase': 'prepare'}
    assert pending.raw({'op': 'gh', 'argv': argv, 'context': context})['result']['exit_code'] == 0
    context['creation_phase'] = 'complete'
    assert pending.raw({'op': 'gh', 'argv': argv, 'context': context})['result']['exit_code'] != 0
    record = pending.service.finalize('attempt-1')
    assert record.events[-1]['reason'] == 'source-not-pushed'
    assert not record.final_state['repository']['exists']
    assert record.events[-1]['state_before'] == record.events[-1]['state_after']


def test_new_mutations_require_declared_authority(wave: Harness) -> None:
    service = fs.FixtureService(wave.world.declaration(authority=['issue.view']), wave.world.remote, 'limited')
    for argv in [('issue', 'create', '--title', 'x', '--body', 'x'),
                 ('issue', 'edit', '1', '--body', 'changed'), ('label', 'create', 'bug')]:
        assert ask(service, *argv)['exit_code'] != 0
    record = service.finalize('limited')
    assert all(e['reason'] == 'unauthorized' for e in record.events)
    assert all(e['state_before'] == e['state_after'] for e in record.events)


def test_lost_create_reply_leaves_one_controller_issue(wave: Harness) -> None:
    service = wave.world.service(faults=[{'kind': 'lost-response', 'op': 'issue.create'}])
    reply = ask(service, 'issue', 'create', '--title', 'x', '--body', 'x')
    assert reply['exit_code'] != 0
    viewed = ask(service, 'issue', 'view', '4', '--json', 'title')
    assert json.loads(viewed['stdout']) == {'title': 'x'}
    record = service.finalize('attempt-1')
    assert record.events[0]['decision'] == 'applied'
    assert record.events[0]['fault'] == 'lost-response'
    assert record.events[0]['effect']['number'] == 4
