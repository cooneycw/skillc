"""Raw wire roots are validated before the older summary decoder is called."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_nhl_egress_behavior import ROOT, run_control
from test_nhl_egress_policy import configured

from skillc import docker_backend as db
from skillc import egress

CASES = json.loads((ROOT / 'controls/nhl-egress/wire.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_raw_proxy_roots_and_mixed_lines_latch_a_controlled_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: dict[str, Any],
) -> None:
    backend, session = configured(tmp_path)
    start = {'event': 'start', 'digest': session.policy.digest}
    raw = '\n'.join(json.dumps(row) for row in [start, *case['entries']]).encode()
    monkeypatch.setattr(db.DockerBackend, 'egress_log', lambda *_a: raw)
    handle = db._Handle('synthetic', 'controlled', {})
    assert backend._nhl_egress_stop(handle, session.policy) is case['stop']
    if case['stop']:
        healthy = json.dumps(start).encode()
        monkeypatch.setattr(db.DockerBackend, 'egress_log', lambda *_a: healthy)
        assert backend._nhl_egress_stop(handle, session.policy)


@pytest.mark.parametrize('raw', [None, False, 0, [], {}, 'not-bytes'])
def test_wrong_wire_transport_type_is_an_unavailable_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: object,
) -> None:
    backend, session = configured(tmp_path)
    monkeypatch.setattr(db.DockerBackend, 'egress_log', lambda *_a: raw)
    assert backend._nhl_egress_stop(db._Handle('synthetic', 'controlled', {}), session.policy)


def test_malformed_wire_stops_native_schedule_without_a_parser_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The normalized unavailable result is the actual boundary between the
    # controller's wire observation and the pre-existing schedule consumer.
    _, _, calls = run_control(tmp_path, monkeypatch, {'status': 'unread'})
    assert len(calls) == 1


def test_wire_population_and_legacy_decoder_twin() -> None:
    assert len(CASES) == 9 and {c['name'] for c in CASES} == {
        'null-root', 'false-root', 'integer-root', 'array-root', 'string-root',
        'empty-object', 'mixed-null', 'mixed-array', 'healthy-twin'}
    parsed = egress.summarize_log(b'{"decision":"allowed","target":"chatgpt.com:443"}\n')
    assert parsed['allowed'] == {'chatgpt.com:443': 1} and parsed['unparsed_lines'] == 0
