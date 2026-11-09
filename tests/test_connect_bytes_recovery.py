"""Public recovery cannot promote checkpoint claims over retained raw evidence."""
from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from test_connect_bytes_behavior import DIGEST, protected_capture, records, wire
from test_connect_bytes_shapes import (
    test_every_new_wire_input_level_is_unknown_not_an_exception as run_shape,
)
from test_nhl_egress_behavior import run_control

from skillc import calibration, trial
from skillc import calibration_run as cr
from skillc import egress_bytes as eb


@pytest.mark.parametrize('capture', ['absent', 'no-trailer', 'object-modified', 'same-size-valid-swap', 'object-absent',
                                    'wrong-attempt', 'wrong-policy', 'wrong-size', 'duplicate'])
def test_outcomes_only_complete_forgery_stays_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture: str,
) -> None:
    observed = {'status': 'read', **eb_policy_summary(wire(records(), trailer=False))}
    experiment, _outcomes, calls = run_control(tmp_path, monkeypatch, observed)
    attempt = calls[0]
    if capture != 'absent':
        raw = wire(records(), trailer=capture != 'no-trailer')
        entry = protected_capture(experiment, attempt, raw)
        if capture in ('object-modified', 'same-size-valid-swap'):
            replacement = b'changed' if capture == 'object-modified' else wire(records(8, 12))
            if capture == 'same-size-valid-swap':
                assert len(replacement) == len(raw)
            target = experiment.object_path(entry['digest'])
            target.chmod(0o600)
            target.write_bytes(replacement)
        elif capture == 'object-absent':
            experiment.object_path(entry['digest']).unlink()
        elif capture in ('wrong-attempt', 'wrong-policy', 'wrong-size'):
            key = {'wrong-attempt': 'attempt', 'wrong-policy': 'policy_digest', 'wrong-size': 'size'}[capture]
            entry[key] = {'wrong-attempt': 'different-attempt', 'wrong-policy': 'sha256:' + 'cd' * 32,
                          'wrong-size': len(raw) + 1}[capture]
            replace_binding(experiment, attempt, entry)
        elif capture == 'duplicate':
            protected_capture(experiment, attempt, raw)
    path = tmp_path / 'run' / 'outcomes.json'
    checkpoint = json.loads(path.read_text())
    claimed = eb.summarize(wire(records()), DIGEST)
    checkpoint['outcomes'][0]['record']['observation']['egress']['bytes_observed'] = claimed
    path.write_text(json.dumps(checkpoint))
    report = recover(experiment, tmp_path / 'run')
    entries = report['attempts']
    assert isinstance(entries, list)
    value = entries[0]['bytes_observed']
    assert value['status'] == 'UNKNOWN' and value['client_to_upstream'] is None


def eb_policy_summary(raw: bytes) -> dict[str, object]:
    from skillc import nhl_egress_policy
    return nhl_egress_policy.summarize_log(raw)


def replace_binding(experiment: trial.Experiment, attempt: str, entry: dict[str, Any]) -> None:
    rows = experiment.events(attempt)
    rows = [entry if row.get('event') == 'egress-bytes-retained' else row for row in rows]
    experiment.journal(attempt).write_text(''.join(json.dumps(row) + '\n' for row in rows))


def test_valid_retained_capture_wins_over_edited_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {'status': 'read', **eb_policy_summary(wire(records(), trailer=False))}
    experiment, _outcomes, calls = run_control(tmp_path, monkeypatch, observed)
    protected_capture(experiment, calls[0], wire(records()))
    path = tmp_path / 'run' / 'outcomes.json'
    checkpoint = json.loads(path.read_text())
    checkpoint['outcomes'][0]['record']['observation']['egress']['bytes_observed'] = eb.unknown('checkpoint changed')
    path.write_text(json.dumps(checkpoint))
    report = recover(experiment, tmp_path / 'run')
    entries = report['attempts']
    assert isinstance(entries, list)
    assert entries[0]['bytes_observed']['status'] == 'COMPLETE'
    assert entries[0]['bytes_observed']['client_to_upstream'] == 7


def test_shape_table_itself_detects_a_generation_blind_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    source = inspect.getsource(eb._summarize)
    anchor = "row['generation'] != generation or "
    assert source.count(anchor) == 1
    source = source.replace(anchor, '')
    namespace = dict(vars(eb))
    exec(compile(source, '<generation-blind-byte-parser>', 'exec'), namespace)  # noqa: S102
    monkeypatch.setattr(eb, '_summarize', namespace['_summarize'])
    # A blind parser must make the table's intended generation assertion fail.
    with pytest.raises(AssertionError):
        run_shape(['connection', 'generation'], None)


RETAINED = json.loads((Path(__file__).resolve().parents[1] / 'controls/connect-bytes/retained-shapes.json').read_text())


@pytest.mark.parametrize('case', RETAINED, ids=lambda row: row['field'])
def test_retained_binding_field_types_and_missing_extra_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: dict[str, Any],
) -> None:
    observed = {'status': 'read', **eb_policy_summary(wire(records()))}
    experiment, _outcomes, calls = run_control(tmp_path, monkeypatch, observed)
    attempt = calls[0]
    entry = protected_capture(experiment, attempt, wire(records()))
    assert eb.from_capture(experiment, attempt, DIGEST)['status'] == 'COMPLETE'
    for value in case['invalid']:
        changed = {**entry, case['field']: value}
        replace_binding(experiment, attempt, changed)
        assert eb.from_capture(experiment, attempt, DIGEST)['status'] == 'UNKNOWN'
        # Restore even a malformed event name, which a named replace cannot find.
        experiment.journal(attempt).write_text(json.dumps(entry) + '\n')
    for field in [*entry, 'extra']:
        changed = copy.deepcopy(entry)
        if field == 'extra':
            changed['extra'] = None
        else:
            del changed[field]
        experiment.journal(attempt).write_text(json.dumps(changed) + '\n')
        assert eb.from_capture(experiment, attempt, DIGEST)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('value', [None, False, 0, 1.5, [], {}, '', 'missing'])
def test_retained_reader_root_and_identity_shapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: Any,
) -> None:
    experiment, _outcomes, calls = run_control(tmp_path, monkeypatch, {'status': 'read', **eb_policy_summary(wire(records()))})
    attempt = calls[0]
    protected_capture(experiment, attempt, wire(records()))
    assert eb.from_capture(value, attempt, DIGEST)['status'] == 'UNKNOWN'
    assert eb.from_capture(experiment, value, DIGEST)['status'] == 'UNKNOWN'
    assert eb.from_capture(experiment, attempt, value)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('damage', ['journal-root', 'journal-symlink', 'object-symlink', 'objects-symlink',
                                  'object-directory', 'duplicate-key', 'empty-journal', 'nested-json'])
def test_retained_raw_file_shapes_are_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str,
) -> None:
    experiment, _outcomes, calls = run_control(tmp_path, monkeypatch, {'status': 'read', **eb_policy_summary(wire(records()))})
    attempt = calls[0]
    entry = protected_capture(experiment, attempt, wire(records()))
    journal = experiment.journal(attempt)
    if damage == 'journal-root':
        journal.write_text('null\n')
    elif damage == 'empty-journal':
        journal.write_text('')
    elif damage == 'nested-json':
        journal.write_text('[' * 2000 + '0' + ']' * 2000)
    elif damage == 'duplicate-key':
        journal.write_text(json.dumps(entry).replace('"version": 1', '"version": 1, "version": 1') + '\n')
    elif damage == 'journal-symlink':
        moved = tmp_path / 'journal-copy'
        journal.rename(moved)
        journal.symlink_to(moved)
    elif damage == 'objects-symlink':
        objects = experiment.root / trial.OBJECTS
        moved = tmp_path / 'object-copy'
        objects.rename(moved)
        objects.symlink_to(moved, target_is_directory=True)
    else:
        target = experiment.object_path(entry['digest'])
        target.unlink()
        if damage == 'object-directory':
            target.mkdir()
        else:
            replacement = tmp_path / 'raw-copy'
            replacement.write_bytes(wire(records()))
            target.symlink_to(replacement)
    assert eb.from_capture(experiment, attempt, DIGEST)['status'] == 'UNKNOWN'


def recover(experiment: trial.Experiment, run_dir: Path) -> dict[str, object]:
    planned, _attempt = next(experiment.attempts())
    config = planned['config']
    assert isinstance(config, dict)
    stored = json.loads(trial.read_object(experiment, str(config['digest'])))
    declaration = calibration.parse_declaration(stored['nhl_egress']['declaration'])
    return cr.recover_report(run_dir, declaration)


def test_real_retention_writer_freezes_raw_once_and_reader_rederives(tmp_path: Path) -> None:
    from test_trial import _spec
    experiment = trial.plan(_spec(), trial.open_store(tmp_path / 'store', forbidden=[]))
    _planned, attempt = next(experiment.attempts())
    attempt_id = str(attempt['attempt_id'])
    eb.retain(experiment, attempt_id, wire(records()), DIGEST)
    value = eb.from_capture(experiment, attempt_id, DIGEST)
    assert value['status'] == 'COMPLETE' and value['client_to_upstream'] == 7
    with pytest.raises(eb.Incomplete):
        eb.retain(experiment, attempt_id, wire(records(8, 12)), DIGEST)
    assert eb.from_capture(experiment, attempt_id, DIGEST) == value


@pytest.mark.parametrize('value', [None, False, 0, [], {}, '', 'not-bytes'])
def test_retention_writer_wrong_shapes_are_named_refusals(tmp_path: Path, value: Any) -> None:
    from test_trial import _spec
    experiment = trial.plan(_spec(), trial.open_store(tmp_path / 'store', forbidden=[]))
    _planned, attempt = next(experiment.attempts())
    attempt_id = str(attempt['attempt_id'])
    for args in [(value, attempt_id, wire(records()), DIGEST),
                 (experiment, value, wire(records()), DIGEST),
                 (experiment, attempt_id, value, DIGEST),
                 (experiment, attempt_id, wire(records()), value)]:
        with pytest.raises((eb.Incomplete, trial.Refused)):
            eb.retain(*args)
