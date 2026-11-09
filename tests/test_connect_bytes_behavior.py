"""Existing-consumer regressions: no imports of newly added APIs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_nhl_egress_behavior import DIGEST, DOCUMENT, run_control, summary

from skillc import calibration_run as cr
from skillc import nhl_egress_policy as nhl
from skillc import trial

GENERATION = 'ab' * 16


def records(sent: int = 7, received: int = 11) -> list[dict[str, Any]]:
    def row(sequence: int, state: str, out: int, incoming: int) -> dict[str, Any]:
        return {'event': 'bytes', 'generation': GENERATION, 'connection': 1,
                'sequence': sequence, 'target': 'api.nhle.com:443', 'state': state,
                'client_to_upstream': out, 'upstream_to_client': incoming}
    return [{'event': 'start', 'digest': DIGEST, 'allowlist': DOCUMENT,
             'byte_telemetry': {'version': 1, 'generation': GENERATION}},
            {'decision': 'allowed', 'target': 'api.nhle.com:443'}, row(0, 'open', 0, 0),
            row(1, 'progress', sent, received), row(2, 'final', sent, received)]


def wire(rows: list[Any], *, trailer: bool = True) -> bytes:
    lines = []
    previous = '0' * 64
    for index, row in enumerate(rows, start=1):
        entry = {**row, 'seq': index, 'prev': previous} if isinstance(row, dict) else row
        line = json.dumps(entry).encode() + b'\n'
        lines.append(line)
        previous = hashlib.sha256(line).hexdigest()
    if trailer:
        final = {'event': 'bytes-end', 'final': True, 'records': len(lines),
                 'last_hash': previous, 'generation': GENERATION,
                 'finals': [row for row in rows if isinstance(row, dict) and row.get('state') == 'final'],
                 'seq': len(lines) + 1, 'prev': previous}
        lines.append(json.dumps(final).encode() + b'\n')
    return b''.join(lines)


@pytest.mark.parametrize('sent,received', [(0, 0), (7, 11), (65537, 131073)])
def test_existing_proxy_summary_reports_observed_bytes(sent: int, received: int) -> None:
    value = nhl.summarize_log(wire(records(sent, received)))
    measured = value.get('bytes_observed', {})
    assert isinstance(measured, dict)
    assert measured.get('client_to_upstream') == sent
    assert measured['upstream_to_client'] == received
    assert measured['status'] == 'COMPLETE'


@pytest.mark.parametrize('mode', ['no-trailer', 'partial-tail', 'missing-middle', 'regressed'])
def test_existing_summary_marks_lost_coverage_unknown(mode: str) -> None:
    rows = records()
    if mode == 'regressed':
        rows[-1]['client_to_upstream'] = 1
    raw = wire(rows, trailer=mode != 'no-trailer')
    if mode == 'partial-tail':
        raw = raw[:-17]
    elif mode == 'missing-middle':
        raw = b''.join(raw.splitlines(keepends=True)[:3] + raw.splitlines(keepends=True)[4:])
    try:
        value = nhl.summarize_log(raw).get('bytes_observed', {})
    except nhl.PolicyRefused:
        assert mode == 'partial-tail'  # Existing controlled-unavailable preservation.
        return
    assert isinstance(value, dict)
    assert value.get('status') == 'UNKNOWN'
    assert value.get('client_to_upstream', 'absent') is None


def test_existing_report_retains_bytes_and_measurement_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = {'status': 'read', **nhl.summarize_log(wire(records()))}
    experiment, outcomes, _ = run_control(tmp_path, monkeypatch, observed)
    protected_capture(experiment, outcomes[0].scheduled.attempt_id, wire(records()))
    report = cr.build_report(experiment, outcomes, declared_model='gpt-6-astra', declared_effort='high')
    attempts = report['attempts']
    assert isinstance(attempts, list)
    value = attempts[0].get('bytes_observed', {})
    assert value.get('client_to_upstream') == 7
    assert value.get('measurement') == 'bytes observed'
    assert value.get('limitation') == 'HTTP request counts and response codes not measured'


def test_legacy_summary_output_is_unchanged() -> None:
    from skillc import egress
    raw = b'{"event":"start","digest":"legacy"}\n{"decision":"denied","target":"x:443"}\n'
    assert egress.summarize_log(raw) == {
        'allowlist_digest': 'legacy', 'allowed': {}, 'denied': {'x:443': 1},
        'upstream_failed': {}, 'peer_rejected': 0, 'unparsed_lines': 0}


def test_legacy_schedule_report_does_not_gain_byte_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment, outcomes, _ = run_control(tmp_path, monkeypatch, summary({}, {}), opted_in=False)
    report = cr.build_report(experiment, outcomes, declared_model='gpt-6-astra', declared_effort='high')
    attempts = report['attempts']
    assert isinstance(attempts, list)
    assert all('bytes_observed' not in row for row in attempts)


def protected_capture(experiment: trial.Experiment, attempt: str, raw: bytes) -> dict[str, Any]:
    """Synthetic controller-store fixture; not candidate/checkpoint input.

    Write the new binding as bytes so this test also exercises the old public
    reader without a missing-new-event API failure.
    """
    digest = trial.put_object(experiment, raw)
    entry = {'event': 'egress-bytes-retained', 'at': '2026-01-01T00:00:00Z',
             'version': 1, 'attempt': attempt, 'policy_digest': DIGEST,
             'digest': digest, 'size': len(raw)}
    with experiment.journal(attempt).open('a') as stream:
        stream.write(json.dumps(entry) + '\n')
    return entry
