"""Model-free controls for arm-neutral controller wake and opaque snapshots."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skillc.backend import Confirmation, ExecuteResult
from skillc.completion import CompletionDeadline
from skillc.wave_snapshot import SnapshotUnavailable, directory_digest, snapshot
from skillc.wave_wake import Revision, WakePolicy, WakeState, drive

SID = '00000000-0000-0000-0000-000000000001'
BASE = Revision('sha256:' + '0' * 64, 'sha256:' + '0' * 64)
FILE = Revision('sha256:' + '1' * 64, BASE.refs)
REF = Revision(BASE.files, 'sha256:' + '1' * 64)
CASES = Path(__file__).resolve().parents[1] / 'controls/wave-wake/cases.json'


class PolicyClock:
    """Causal policy endpoint; real watchdog makes a blind fixture still fail."""

    def __init__(self) -> None:
        self.value = 0.
        self.watchdog = time.monotonic() + 3

    def __call__(self) -> float:
        return 1. if time.monotonic() >= self.watchdog else self.value


def policy(**kwargs: Any) -> WakePolicy:
    return WakePolicy(**{'literal': 'Read the shared work and continue.', 'poll_seconds': .001,
                         'min_spacing_seconds': 0., 'max_pokes': 1, **kwargs})


@pytest.mark.parametrize('case', json.loads(CASES.read_text()), ids=lambda c: c['name'])
def test_committed_wake_conditions(case: dict[str, Any]) -> None:
    state = WakeState(policy(), ('worker-a',))
    result = ExecuteResult(case.get('reason', 'exited'), case.get('exit_code', 0))
    state.ended('worker-a', None if case.get('no_session') else SID, result, BASE, 0)
    if case.get('phase'):
        state.slots['worker-a'].phase = case['phase']
    changed = {'none': BASE, 'files': FILE, 'refs': REF}[case['change']]
    poke = state.offer('worker-a', changed, 1)
    allowed = False
    if poke is not None:
        allowed = state.dispatch(poke, BASE if case.get('stale_revision') else changed,
            current_role=case.get('current_role', 'worker-a'), current_session=case.get('current_session', SID),
            idle=case.get('idle', True), live=case.get('live', True), now=1)
    assert allowed is case['expected']
    if poke is not None and not allowed:
        assert state.events[-1]['event'] == 'poke-refused'
    assert state.report('MODEL')['poke_count'] == int(allowed)


def test_literal_and_every_policy_axis_are_bound_to_digest() -> None:
    original = policy()
    assert policy().digest == original.digest
    axes: dict[str, Any] = {'literal': 'A different literal.', 'poll_seconds': .5,
                         'min_spacing_seconds': 1., 'max_pokes': 2,
                         'max_files': 8, 'max_bytes': 32}
    for field, value in axes.items():
        assert replace(original, **{field: value}).digest != original.digest


@pytest.mark.parametrize('changes', [{'literal': ''}, {'literal': '-unsafe'}, {'poll_seconds': 0},
    {'poll_seconds': True}, {'min_spacing_seconds': -1}, {'max_pokes': True}, {'max_pokes': 65},
    {'after_failure': 'resume'}, {'after_cap': 'pass'}, {'max_files': 0}])
def test_policy_refuses_undeclared_or_invalid_behavior(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        policy(**changes)


def test_spacing_watermark_and_attempts_are_distinct_from_receipt() -> None:
    state = WakeState(policy(max_pokes=3, min_spacing_seconds=2), ('worker-a',))
    state.ended('worker-a', SID, ExecuteResult('exited', 0), BASE, 0)
    poke = state.offer('worker-a', FILE, 1)
    assert poke is not None and state.dispatch(poke, FILE, current_role='worker-a', current_session=SID,
                                              idle=True, live=True, now=1)
    state.suppressed(poke, 1)
    assert state.offer('worker-a', FILE, 10) is None  # No second attempt for unchanged state.
    assert state.offer('worker-a', REF, 2) is None  # New state still observes spacing.
    assert state.offer('worker-a', REF, 3) is not None
    assert [e['event'] for e in state.events] == ['turn-ended', 'poke-attempt', 'poke-unconfirmed']


def test_cap_ends_role_and_forged_role_does_not_consume_legitimate_token() -> None:
    state = WakeState(policy(), ('worker-a', 'worker-b'))
    state.ended('worker-a', SID, ExecuteResult('exited', 0), BASE, 0)
    poke = state.offer('worker-a', FILE, 1)
    assert poke is not None
    assert not state.dispatch(replace(poke, role='worker-b'), FILE, current_role='worker-b',
                              current_session=SID, idle=True, live=True, now=1)
    assert state.dispatch(poke, FILE, current_role='worker-a', current_session=SID, idle=True, live=True, now=1)
    state.ended('worker-a', SID, ExecuteResult('exited', 0), FILE, 2)
    assert state.slots['worker-a'].end == 'max-pokes'
    assert state.offer('worker-a', REF, 3) is None


def git(root: Path, *args: str) -> None:
    subprocess.run(['git', *args], cwd=root, check=True, capture_output=True, timeout=10)


def test_snapshot_finds_file_ref_and_permission_changes_without_parsing_messages(tmp_path: Path) -> None:
    shared, remote = tmp_path / 'shared', tmp_path / 'remote'
    shared.mkdir(); remote.mkdir()
    git(remote, 'init', '-b', 'main')
    first = snapshot(str(shared), str(remote / '.git'))
    (shared / 'arbitrary').write_bytes(b'not-json\x00\xff')
    second = snapshot(str(shared), str(remote / '.git'))
    assert second['files'] != first['files'] and second['refs'] == first['refs']
    assert second == snapshot(str(shared), str(remote / '.git'))
    (shared / 'arbitrary').chmod(0o600)
    assert snapshot(str(shared), str(remote / '.git'))['files'] != second['files']
    git(remote, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-m', 'ref')
    assert snapshot(str(shared), str(remote / '.git'))['refs'] != first['refs']


def test_snapshot_does_not_follow_links_and_refuses_missing_or_over_budget(tmp_path: Path) -> None:
    shared, outside = tmp_path / 'shared', tmp_path / 'outside'
    shared.mkdir(); outside.mkdir()
    (outside / 'secret').write_text('first')
    (shared / 'file-link').symlink_to(outside / 'secret')
    (shared / 'dir-link').symlink_to(outside, target_is_directory=True)
    before = directory_digest(str(shared), 10, 100)
    (outside / 'secret').write_text('other content')
    assert directory_digest(str(shared), 10, 100) == before
    (shared / 'plain').write_bytes(b'x' * 101)
    with pytest.raises(SnapshotUnavailable, match='budget'):
        directory_digest(str(shared), 10, 100)
    with pytest.raises(SnapshotUnavailable):
        snapshot(str(tmp_path / 'missing'), str(outside))
    os.mkfifo(shared / 'fifo')
    (shared / 'plain').unlink()
    with pytest.raises(SnapshotUnavailable, match='unsupported'):
        directory_digest(str(shared), 10, 100)


class ScriptedWave:
    """Trusted deterministic controller double; no untrusted host execution."""

    def __init__(self, root: Path, arm: str) -> None:
        self.root = root
        self.attempt_id = 'model-wave'
        root.mkdir()
        self.shared = root / 'shared'
        self.shared.mkdir()
        self.diagnostic_reads = 0
        self.arm = arm  # Diagnostic only; there is no arm argument to wake policy.
        self.roles = [SimpleNamespace(name=n, resume_texts=()) for n in ('worker-a', 'worker-b')]
        self.states = {r.name: SimpleNamespace(session_id=None, busy=threading.Lock(), unknown=[],
            handle=None, backend=SimpleNamespace(end_attempt=lambda handle: None,
                confirm_stopped=lambda handle: Confirmation.NOT_CONFIRMED))
                       for r in self.roles}
        self.closed = self._prepared = False
        self.deadline = CompletionDeadline.after(2)
        self.release = threading.Event()
        self.revisions: list[Revision] = []
        self.calls: list[tuple[str, str | None, str | None]] = []

    def _write(self, name: str, payload: object) -> None:
        (self.root / name).write_text(json.dumps(payload))

    def prepare(self) -> None:
        self._prepared = True

    def turn(self, role: str, text: str | None = None, *, expected_session: str | None = None) -> ExecuteResult:
        state = self.states[role]
        with state.busy:
            if expected_session is not None and expected_session != state.session_id:
                from skillc.controller_turns import TurnsRefused
                raise TurnsRefused('planted session replacement under dispatch lock')
            self.calls.append((role, text, expected_session))
            if text is None:
                state.session_id = SID if role == 'worker-a' else SID[:-1] + '2'
                if role == 'worker-b':
                    assert self.release.wait(3)
                    if self.closed:
                        return ExecuteResult('operator-cancelled', None)
                    (self.shared / 'message').write_bytes(b'first opaque message')
                    self.revisions.append(self.current_revision())
            else:
                assert expected_session == state.session_id
                if role == 'worker-a':
                    (self.shared / 'message').write_bytes(b'second opaque message')
                    self.revisions.append(self.current_revision())
            return ExecuteResult('exited', 0)

    def read(self) -> Revision:
        revision = self.current_revision()
        if self.arm == 'cpp-diagnostic':
            self.diagnostic_reads += 1
            self._write('cpp-diagnostic-only.json', {'outbox_revision': self.diagnostic_reads})
        journal = self.root / 'wake-events.json'
        if journal.exists():
            events = json.loads(journal.read_text())
            if any(e['event'] == 'turn-ended' and e['role'] == 'worker-a' for e in events):
                self.release.set()
        return revision

    def current_revision(self) -> Revision:
        return Revision(directory_digest(str(self.shared), 8, 1024), BASE.refs)

    def close(self) -> dict[str, Any]:
        self.closed = True
        self.release.set()
        for state in self.states.values():
            with state.busy:
                pass
        return {'scope': 'model-only', 'completion': {
            'cleanup_confirmed': True, 'on_time': True}}


@pytest.mark.parametrize('arm', ['plain-files', 'cpp-diagnostic'])
def test_scripted_arms_receive_identical_controller_pokes(tmp_path: Path, arm: str) -> None:
    wave = ScriptedWave(tmp_path / 'wave', arm)
    report = drive(wave, policy(), read_revision=wave.read)
    assert report['outcome'] == 'STOPPED'
    assert report['poke_count'] == 2
    attempts = [e for e in report['events'] if e['event'] == 'poke-attempt']
    assert [(e['role'], e['revision']) for e in attempts] == [
        ('worker-a', wave.revisions[0].identity), ('worker-b', wave.revisions[1].identity)]
    assert all(poke['result']['exit_code'] == 0 for poke in report['pokes'])
    assert all(slot['end'] == 'max-pokes' for slot in report['roles'].values())
    assert wave.calls[2:] == [('worker-a', policy().literal, SID), ('worker-b', policy().literal, SID[:-1] + '2')]
    assert (wave.root / 'wake-report.json').is_file() and wave.closed


def test_suppressed_poke_reaches_original_deadline_never_pass(tmp_path: Path) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    clock = PolicyClock()
    wave.deadline = CompletionDeadline.after(1, clock)

    def suppressed(poke: Any) -> bool:
        clock.value = 1
        return False

    report = drive(wave, policy(), read_revision=wave.read, deliver=suppressed, clock=clock)
    assert report['outcome'] == 'DEADLINE' and report['poke_count'] == 1
    assert any(e['event'] == 'poke-unconfirmed' for e in report['events'])
    assert all(text is None for _, text, _ in wave.calls)


def test_shipped_isolated_snapshot_source_and_missing_remote_control(tmp_path: Path) -> None:
    import sys

    from skillc import wave_snapshot

    shared, remote = tmp_path / 'shared', tmp_path / 'repo'
    shared.mkdir(); remote.mkdir()
    (shared / 'payload').write_bytes(b'opaque\x00bytes')
    git(remote, 'init', '--bare')
    source = Path(wave_snapshot.__file__).read_text()
    run = subprocess.run([sys.executable, '-I', '-S', '-c', source,
                          str(shared), str(remote), '8', '1024'], capture_output=True, check=False, timeout=10)
    assert run.returncode == 0
    assert json.loads(run.stdout) == snapshot(str(shared), str(remote), 8, 1024)
    bad = subprocess.run([sys.executable, '-I', '-S', '-c', source,
                          str(shared), str(remote / 'absent'), '8', '1024'], capture_output=True,
                         check=False, timeout=10)
    assert bad.returncode == 2 and not bad.stdout


@pytest.mark.parametrize('payload', [b'', b'{}', b'null', b'{"files":"claimed"}', b'{"files":null,"refs":null}'])
def test_observer_refuses_incomplete_claims_instead_of_empty_revisions(payload: bytes) -> None:
    from skillc.backend import BackendUnavailable
    from skillc.wave_wake import observe

    calls = []

    def call(argv: Any) -> bytes:
        calls.append(argv)
        return payload

    wave = SimpleNamespace(remote=object(), _name=lambda handle: 'controller-helper',
                           _call=call)
    with pytest.raises(BackendUnavailable):
        observe(wave, policy())
    assert calls[0][:8] == ['exec', '-u', '0', '--', 'controller-helper', 'python3', '-I', '-S']
    assert calls[0][-4:] == ['/run/skillc-wave', '/fixture/repo.git', '4096', '4194304']


def test_unavailable_observation_retries_without_fabricating_empty_revision(tmp_path: Path) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    calls = 0

    def read() -> Revision:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise SnapshotUnavailable('planted incomplete observation')
        return wave.read()

    report = drive(wave, policy(), read_revision=read)
    assert report['outcome'] == 'STOPPED' and report['poke_count'] == 2
    recovered = [e for e in report['events'] if e['event'] == 'observation-restored']
    assert recovered[0]['missed'] == 2


def test_permanent_observation_loss_reaches_deadline_without_starting_subject(tmp_path: Path) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    clock = PolicyClock()
    wave.deadline = CompletionDeadline.after(.005, clock)

    def missing() -> Revision:
        raise SnapshotUnavailable('planted unavailable observer')

    def advance(seconds: float) -> None:
        clock.value += seconds

    report = drive(wave, policy(), read_revision=missing, clock=clock, sleep=advance)
    assert report['outcome'] == 'DEADLINE' and report['poke_count'] == 0
    assert wave.closed and not wave.calls
    assert report['unavailable_samples_at_end'] > 0


@pytest.mark.parametrize(('confirmed', 'on_time', 'expected'), [
    (False, True, 'UNKNOWN'), (True, False, 'DEADLINE'),
])
def test_cleanup_loss_or_lateness_prevents_clean_driver_outcome(
    tmp_path: Path, confirmed: bool, on_time: bool, expected: str,
) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    close = wave.close

    def result() -> dict[str, Any]:
        close()
        return {'completion': {'cleanup_confirmed': confirmed, 'on_time': on_time}}

    wave.close = result  # type: ignore[method-assign]
    report = drive(wave, policy(), read_revision=wave.read)
    assert report['outcome'] == expected


@pytest.mark.parametrize('failure_point', ['wake-declaration.json', 'wake-events.json'])
def test_publication_error_still_stops_owned_roles_and_keeps_original_error(
    tmp_path: Path, failure_point: str,
) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    original = wave._write
    attempts = 0

    def write(name: str, payload: object) -> None:
        nonlocal attempts
        if name == failure_point:
            attempts += 1
            raise OSError('original failure' if attempts == 1 else 'secondary failure')
        original(name, payload)

    wave._write = write  # type: ignore[method-assign]
    with pytest.raises(OSError, match='original failure'):
        drive(wave, policy(), read_revision=wave.read)
    assert wave.closed
    assert json.loads((wave.root / 'wake-report.json').read_text())['outcome'] == 'UNKNOWN'


def test_running_blocking_role_is_not_poked_while_sibling_activity_changes(tmp_path: Path) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    clock = PolicyClock()
    wave.deadline = CompletionDeadline.after(1, clock)
    release = threading.Event()
    closed = wave.close
    changed = False

    def turn(role: str, text: str | None = None, *, expected_session: str | None = None) -> ExecuteResult:
        state = wave.states[role]
        with state.busy:
            wave.calls.append((role, text, expected_session))
            state.session_id = SID if role == 'worker-a' else SID[:-1] + '2'
            if role == 'worker-a':
                assert release.wait(2)
                return ExecuteResult('operator-cancelled', None)
            return ExecuteResult('exited', 0)

    def read() -> Revision:
        nonlocal changed
        value = wave.current_revision()
        if changed:
            clock.value = 1
        journal = wave.root / 'wake-events.json'
        if journal.exists() and not changed:
            events = json.loads(journal.read_text())
            if any(e['event'] == 'turn-ended' and e['role'] == 'worker-b' for e in events):
                (wave.shared / 'message').write_bytes(b'changed while worker-a waits')
                changed = True
        return value

    def close() -> dict[str, Any]:
        release.set()
        return closed()

    wave.turn = turn  # type: ignore[method-assign]
    wave.close = close  # type: ignore[method-assign]
    report = drive(wave, policy(), read_revision=read, clock=clock)
    assert report['outcome'] == 'DEADLINE' and changed
    assert not any(role == 'worker-a' and text is not None for role, text, _ in wave.calls)


def test_cap_also_refuses_a_second_revision_after_an_unconfirmed_attempt() -> None:
    state = WakeState(policy(), ('worker-a',))
    state.ended('worker-a', SID, ExecuteResult('exited', 0), BASE, 0)
    poke = state.offer('worker-a', FILE, 1)
    assert poke is not None
    assert state.dispatch(poke, FILE, current_role='worker-a', current_session=SID,
                          idle=True, live=True, now=1)
    state.suppressed(poke, 1)
    assert state.offer('worker-a', REF, 2) is None
    assert state.slots['worker-a'].end == 'max-pokes'
    assert state.report('STOPPED')['pokes'][0]['result'] is None


def test_count_projection_has_explicit_session_binding_and_unobserved_null() -> None:
    state = WakeState(policy(), ('worker-a', 'worker-b'))
    assert state.report('UNKNOWN')['poke_counts'] == [
        {'role': 'worker-a', 'session_id': None, 'pokes': None},
        {'role': 'worker-b', 'session_id': None, 'pokes': None}]
    state.ended('worker-a', SID, ExecuteResult('exited', 0), BASE, 0)
    assert state.report('MODEL')['poke_counts'][0] == {'role': 'worker-a', 'session_id': SID, 'pokes': 0}
    poke = state.offer('worker-a', FILE, 1)
    assert poke is not None and state.dispatch(poke, FILE, current_role='worker-a', current_session=SID,
                                              idle=True, live=True, now=1)
    state.suppressed(poke, 1)
    assert state.report('DEADLINE')['poke_counts'][0] == {'role': 'worker-a', 'session_id': SID, 'pokes': 1}
    state.ended('worker-b', '', ExecuteResult('exited', 0), BASE, 2)
    assert state.report('MODEL')['poke_counts'][1]['pokes'] is None


def test_incompatible_capture_session_does_not_relabel_poke_count(tmp_path: Path) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    original = wave.close

    def close() -> dict[str, Any]:
        value = original()
        wave.states['worker-a'].session_id = SID[:-1] + '9'
        return value

    wave.close = close  # type: ignore[method-assign]
    report = drive(wave, policy(), read_revision=wave.read)
    row = next(row for row in report['poke_counts'] if row['role'] == 'worker-a')
    assert row['session_id'] == SID and row['pokes'] is None


def test_session_change_between_offer_and_execution_is_fenced_and_recorded(tmp_path: Path) -> None:
    wave = ScriptedWave(tmp_path / 'wave', 'plain-files')
    clock = PolicyClock()
    wave.deadline = CompletionDeadline.after(1, clock)

    def replace_session(poke: Any) -> bool:
        wave.states[poke.role].session_id = SID[:-1] + '9'
        clock.value = 1
        return True

    report = drive(wave, policy(), read_revision=wave.read, deliver=replace_session, clock=clock)
    assert report['outcome'] == 'DEADLINE'
    assert report['pokes'][0]['result'] is None
    assert report['pokes'][0]['refusal']['reason'] == 'turn-fenced'
    assert all(text is None for _, text, _ in wave.calls)
    assert report['poke_counts'][0]['pokes'] is None
