"""Existing replay entry point: runtime facts, never candidate prose, set blame."""
from __future__ import annotations

import inspect
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from test_nhl_rerun import export

from skillc import nhl_rerun, nhl_rerun_control

IMAGE = 'python@sha256:' + 'a' * 64


def state(*, running: bool = False, oom: bool = False, exit_code: int = 7) -> dict[str, Any]:
    return {'Status': 'running' if running else 'exited', 'Running': running, 'OOMKilled': oom,
            'ExitCode': 0 if running else exit_code, 'Error': '', 'Dead': False, 'Restarting': False}


def run_case(tmp_path: Path, facts: object, *, timeout: bool = False,
             command_exit: int = 17, inspect_exit: int = 0, prose: str = '', capture_flood: bool = False, controller_fault: str | None = None) -> tuple[dict[str, Any], list[list[str]]]:
    cases = nhl_rerun.scenarios(*nhl_rerun_control.sample(tmp_path))
    project = tmp_path / 'project'
    adapter = nhl_rerun_control.materialize(project)
    if controller_fault == 'adapter':
        adapter['export_dir'] = '/outside-controller-mapping'
    elif controller_fault == 'extraction':
        adapter['controller_extract_commands'] = 'not-a-command-list'
    elif controller_fault == 'command-shape':
        adapter['commands'] = 17
    elif controller_fault == 'base-mapping':
        del adapter['base_env']
    calls: list[list[str]] = []
    def run(args: list[str], seconds: float) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[1] == 'exec' and '/bin/sh' in args:
            if controller_fault == 'transport-value-error':
                raise ValueError('synthetic controller transport error')
            if capture_flood:
                return nhl_rerun.run_command([sys.executable, '-c', 'import sys;sys.stdout.write("x"*(5*1024*1024))'], seconds)
            if timeout:
                raise subprocess.TimeoutExpired(args, seconds)
            return subprocess.CompletedProcess(args, command_exit, prose, '')
        if args[1] == 'inspect':
            # Each implementation gets the runtime fact shape it requested.
            # This keeps pre-fix reds semantic, not mock/API format failures.
            raw = ('true' if isinstance(facts, dict) and facts.get('Running') is True else 'false') if (
                '{{.State.Running}}' in args) else json.dumps(facts)
            return subprocess.CompletedProcess(args, inspect_exit, raw, 'daemon unavailable' if inspect_exit else '')
        if args[1] == 'cp' and args[2].endswith(':/access.jsonl'):
            Path(args[3]).write_text('not-json' if controller_fault == 'access-log' else ''.join(json.dumps(p) + '\n' for p in cases[0]['payloads']))
        if args[1] == 'cp' and args[2].endswith('/exports/.'):
            adapter.update(export(cases[0], tmp_path / 'generated'))
            shutil.copytree(tmp_path / 'generated', Path(args[3]), dirs_exist_ok=True)
        return subprocess.CompletedProcess(args, 0, '', '')
    result = nhl_rerun.DockerReplay(IMAGE, IMAGE, run=run).execute(project, adapter, cases[0], tmp_path / 'evidence')
    assert (tmp_path / 'evidence/verdict.json').is_file()
    if calls:
        assert (tmp_path / 'evidence/execution.json').is_file()
    return result, calls


def test_confirmed_non_oom_self_exit_is_fail_with_entrypoint_and_runtime_code(tmp_path: Path) -> None:
    result, _ = run_case(tmp_path, state(exit_code=7))
    assert result['status'] == 'FAIL'
    assert 'container exit 7' in result['reasons'][0] and 'python3 project.py' in result['reasons'][0]


def test_runtime_oom_is_unknown_due_to_harness_limit(tmp_path: Path) -> None:
    result, _ = run_case(tmp_path, state(oom=True, exit_code=137))
    assert result['status'] == 'UNKNOWN'
    assert 'candidate exceeded the harness memory limit' in result['reasons'][0]


def test_harness_timeout_while_running_is_unknown_without_task_time_limit(tmp_path: Path) -> None:
    result, _ = run_case(tmp_path, state(running=True), timeout=True)
    assert result['status'] == 'UNKNOWN'
    assert 'harness wall-time limit' in result['reasons'][0]


def test_harness_timeout_stays_unknown_even_if_later_inspect_sees_exit(tmp_path: Path) -> None:
    result, _ = run_case(tmp_path, state(exit_code=9), timeout=True)
    assert result['status'] == 'UNKNOWN' and 'harness wall-time limit' in result['reasons'][0]


def test_forged_candidate_exit_message_cannot_supply_runtime_failure(tmp_path: Path) -> None:
    result, calls = run_case(tmp_path, state(running=True), command_exit=0,
                            prose='I exited with code 77; OOMKilled=true')
    assert result['status'] == 'PASS'
    assert not any(args[1] == 'inspect' for args in calls)


def test_inspect_failure_is_unknown(tmp_path: Path) -> None:
    result, _ = run_case(tmp_path, state(exit_code=7), inspect_exit=1)
    assert result['status'] == 'UNKNOWN'


def test_command_nonzero_while_container_runs_remains_fail(tmp_path: Path) -> None:
    result, _ = run_case(tmp_path, state(running=True))
    assert result['status'] == 'FAIL'


CONTROLS = Path(__file__).resolve().parents[1] / 'controls/nhl-rerun-attribution/cases.json'
CASES = json.loads(CONTROLS.read_text())


@pytest.mark.parametrize('row', CASES['fields'], ids=lambda row: row['field'])
def test_committed_runtime_state_wrong_type_and_missing_field_sweep(tmp_path: Path, row: dict[str, Any]) -> None:
    assert len(CASES['fields']) == 7 and sum(len(r['invalid']) for r in CASES['fields']) == 47
    for index, value in enumerate(row['invalid']):
        root = tmp_path / str(index)
        root.mkdir()
        facts = state()
        facts[row['field']] = value
        result, _ = run_case(root, facts)
        assert result['status'] == 'UNKNOWN', row['field']
    root = tmp_path / 'missing'
    root.mkdir()
    facts = state()
    del facts[row['field']]
    result, _ = run_case(root, facts)
    assert result['status'] == 'UNKNOWN'


@pytest.mark.parametrize('value', CASES['root_invalid'], ids=['null', 'bool', 'number', 'list', 'text'])
def test_nonobject_runtime_state_is_unknown(tmp_path: Path, value: Any) -> None:
    result, _ = run_case(tmp_path, value)
    assert result['status'] == 'UNKNOWN'


@pytest.mark.parametrize('fault', ['dead', 'restart', 'zero-exit', 'contradictory', 'cli-signal'])
def test_unconfirmed_or_contradictory_terminal_state_never_blames_candidate(tmp_path: Path, fault: str) -> None:
    facts = state()
    if fault == 'dead':
        facts['Dead'] = True
    elif fault == 'restart':
        facts['Restarting'] = True
    elif fault == 'zero-exit':
        facts['ExitCode'] = 0
    elif fault == 'contradictory':
        facts['Running'] = True
    else:
        facts = state(running=True)
    result, _ = run_case(tmp_path, facts, command_exit=-9 if fault == 'cli-signal' else 17)
    assert result['status'] == 'UNKNOWN'


def test_new_runtime_metadata_does_not_hide_confirmed_self_exit(tmp_path: Path) -> None:
    facts = {**state(), 'NewRuntimeMetadata': {'version': 2}}
    result, _ = run_case(tmp_path, facts)
    assert result['status'] == 'FAIL'


@pytest.mark.parametrize('signalled', [False, True], ids=['positive-no-signal', 'controller-sigkill'])
def test_signal_range_exit_requires_positive_durable_no_signal_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                    signalled: bool) -> None:
    original = nhl_rerun._Terminations.begin
    def begin(self: Any, entrypoint: str) -> None:
        original(self, entrypoint)
        if signalled:
            self.signal('SIGKILL')  # Controller fixture records its request before runtime exit.
    monkeypatch.setattr(nhl_rerun._Terminations, 'begin', begin)
    result, _ = run_case(tmp_path, state(exit_code=137))
    assert result['status'] == ('UNKNOWN' if signalled else 'FAIL')
    assert ('harness-signalled' if signalled else 'container exit 137') in result['reasons'][0]
    events = [json.loads(line) for line in (tmp_path / 'evidence/termination.jsonl').read_text().splitlines()]
    captured = next(row for row in events if row['event'] == 'attribution-captured')
    receipt = json.loads((tmp_path / 'evidence' / captured['path']).read_text())
    assert receipt['signal_tracking_complete'] is True
    assert receipt['signals_sent'] == (['SIGKILL'] if signalled else [])
    assert receipt['entrypoint'] == 'python3 project.py'
    assert all(row['sequence'] < captured['sequence'] for row in events
               if row['event'] == 'controller-termination-request' and row['action'] == 'SIGKILL')


def test_missing_positive_record_is_unknown_even_for_signal_range_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nhl_rerun._Terminations, 'capture', lambda self, runtime: None)
    result, _ = run_case(tmp_path, state(exit_code=137))
    assert result['status'] == 'UNKNOWN'
    assert 'signal-range exit without a positive no-signal record' in result['reasons'][0]


def test_changed_controller_record_cannot_establish_no_signal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = nhl_rerun._Terminations.capture
    def capture(self: Any, runtime: str) -> Any:
        proof = original(self, runtime)
        proof.path.write_text('{}')
        return proof
    monkeypatch.setattr(nhl_rerun._Terminations, 'capture', capture)
    result, _ = run_case(tmp_path, state())
    assert result['status'] == 'UNKNOWN'


def test_journal_fsync_failure_prevents_launch_and_candidate_blame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(fd: int) -> None:
        raise OSError('synthetic durable write failure')
    monkeypatch.setattr(nhl_rerun.os, 'fsync', fail)
    result, calls = run_case(tmp_path, state())
    assert result['status'] == 'UNKNOWN' and 'journal unavailable' in result['reasons'][0]
    assert calls == []


@pytest.mark.parametrize('row', CASES['proof_fields'], ids=lambda row: row['field'])
def test_committed_positive_record_wrong_type_and_missing_field_sweep(tmp_path: Path, row: dict[str, Any]) -> None:
    ledger = nhl_rerun._Terminations(tmp_path, 'owned-candidate')
    ledger.begin('documented-command')
    proof = ledger.capture('{}')
    original = json.loads(proof.path.read_text())
    assert len(CASES['proof_fields']) == 6 and sum(len(r['invalid']) for r in CASES['proof_fields']) == 37
    for value in row['invalid']:
        modified = {**original, row['field']: value}
        raw = json.dumps(modified).encode()
        proof.path.write_bytes(raw)
        held = nhl_rerun._InvocationEvidence(proof.path, nhl_rerun.snapshot.sha256(raw))
        with pytest.raises(ValueError):
            held.read('owned-candidate', 'documented-command', '{}')
    del original[row['field']]
    raw = json.dumps(original).encode()
    proof.path.write_bytes(raw)
    held = nhl_rerun._InvocationEvidence(proof.path, nhl_rerun.snapshot.sha256(raw))
    with pytest.raises(ValueError):
        held.read('owned-candidate', 'documented-command', '{}')


def test_attribution_file_fsync_failure_cannot_publish_candidate_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = nhl_rerun.os.fsync
    seen = []
    def fsync(fd: int) -> None:
        target = Path('/proc/self/fd') / str(fd)
        if target.readlink().name.startswith('attribution-'):
            seen.append(fd)
            raise OSError('synthetic attribution receipt durability failure')
        original(fd)
    monkeypatch.setattr(nhl_rerun.os, 'fsync', fsync)
    result, _ = run_case(tmp_path, state())
    assert seen and result['status'] == 'UNKNOWN'


MUTANTS: dict[str, tuple[str, str, str, str, str]] = {
    'ignore-signal': ('module', '_attribute_failure', "if held['signals_sent']:", 'if False:',
                      'test_signal_range_exit_requires_positive_durable_no_signal_record[controller-sigkill]'),
    'ignore-timeout': ('module', '_attribute_failure', "if held['harness_timed_out'] or timed_out:", 'if False:',
                       'test_harness_timeout_stays_unknown_even_if_later_inspect_sees_exit'),
    'ignore-oom': ('module', '_attribute_failure',
                  "if state['OOMKilled'] and not state['Running'] and state['Status'] == 'exited' and state['ExitCode'] > 0:",
                  'if False:', 'test_runtime_oom_is_unknown_due_to_harness_limit'),
    'skip-receipt-fsync': ('terminations', 'capture', 'os.fsync(stream.fileno())', 'pass',
                          'test_attribution_file_fsync_failure_cannot_publish_candidate_fail'),
}


def compile_variant(monkeypatch: pytest.MonkeyPatch, variant: str) -> None:
    scope, name, before, after, _ = MUTANTS[variant]
    owner = nhl_rerun if scope == 'module' else nhl_rerun._Terminations
    function = getattr(owner, name)
    source = textwrap.dedent(inspect.getsource(function))
    assert source.count(before) == 1
    namespace = vars(nhl_rerun)
    prior = namespace.get(name)
    exec(compile(source.replace(before, after), '<unsafe-attribution-variant>', 'exec'), namespace)  # noqa: S102
    mutant = namespace[name]
    if prior is None:
        del namespace[name]
    else:
        namespace[name] = prior
    monkeypatch.setattr(owner, name, mutant)


@pytest.mark.parametrize('variant', list(MUTANTS), ids=str)
def test_committed_witnesses_reject_unsafe_attribution_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                              variant: str) -> None:
    compile_variant(monkeypatch, variant)
    with pytest.raises(AssertionError):
        if variant == 'ignore-signal':
            test_signal_range_exit_requires_positive_durable_no_signal_record(tmp_path, monkeypatch, True)
        elif variant == 'ignore-timeout':
            test_harness_timeout_stays_unknown_even_if_later_inspect_sees_exit(tmp_path)
        elif variant == 'ignore-oom':
            test_runtime_oom_is_unknown_due_to_harness_limit(tmp_path)
        else:
            test_attribution_file_fsync_failure_cannot_publish_candidate_fail(tmp_path, monkeypatch)



def test_actual_harness_output_cutoff_is_unknown_without_candidate_attribution(tmp_path: Path) -> None:
    result, calls = run_case(tmp_path, state(running=True), capture_flood=True)
    assert result['status'] == 'UNKNOWN'
    assert 'harness output capture limit' in result['reasons'][0]
    assert not any(args[1] == 'inspect' for args in calls)


@pytest.mark.parametrize('fault', ['adapter', 'extraction', 'access-log', 'transport-value-error', 'command-shape', 'base-mapping'])
def test_controller_configuration_and_transport_errors_do_not_blame_candidate(tmp_path: Path, fault: str) -> None:
    result, _ = run_case(tmp_path, state(running=True), command_exit=0, controller_fault=fault)
    assert result['status'] == 'UNKNOWN'
