"""Coverage, bounded capture, interruption, and blind-instrument controls."""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_connect_bytes_behavior import DIGEST, GENERATION, records, wire
from test_connect_bytes_shapes import ROOT, rechain
from test_nhl_egress_policy import configured

from skillc import docker_backend as db
from skillc import egress_bytes as eb


@pytest.mark.parametrize('damage', ['missing-open', 'missing-final', 'duplicate', 'reordered',
                                  'wrong-generation', 'wrong-digest', 'overflow', 'unknown-event',
                                  'extra-field', 'boolean-final-counter'])
def test_damaged_evidence_is_unknown(damage: str) -> None:
    rows = [json.loads(line) for line in wire(records()).splitlines()]
    if damage == 'missing-open':
        del rows[2]
    elif damage == 'missing-final':
        del rows[4]
    elif damage == 'duplicate':
        rows.insert(4, copy.deepcopy(rows[3]))
    elif damage == 'reordered':
        rows[3], rows[4] = rows[4], rows[3]
    elif damage == 'wrong-generation':
        rows[3]['generation'] = 'cd' * 16
    elif damage == 'wrong-digest':
        rows[0]['digest'] = 'sha256:' + 'cd' * 32
    elif damage == 'overflow':
        rows[3]['client_to_upstream'] = eb.MAX_COUNTER + 1
    elif damage == 'unknown-event':
        rows[3]['event'] = 'unexpected'
    elif damage == 'extra-field':
        rows[3]['extra'] = None
    elif damage == 'boolean-final-counter':
        rows = [json.loads(line) for line in wire(records(1, 1)).splitlines()]
        rows[-1]['finals'][0]['client_to_upstream'] = True
    value = eb.summarize(rechain(rows), DIGEST)
    assert value['status'] == 'UNKNOWN' and value['client_to_upstream'] is None


@pytest.mark.parametrize('raw', [b'', b'null\n', b'false\n', b'[]\n', b'0\n', b'"text"\n',
                               b'{}\n', b'\xff\n', b'{broken}\n'])
def test_raw_roots_and_decode_failures_are_unknown(raw: bytes) -> None:
    assert eb.summarize(raw, DIGEST)['status'] == 'UNKNOWN'


def test_all_byte_and_whole_line_truncations_cannot_be_complete() -> None:
    raw = wire(records())
    # A small fixed stream exercises EVERY prefix, including empty and every
    # entire-line boundary, not only the last character of a chosen row.
    for length in range(len(raw)):
        value = eb.summarize(raw[:length], DIGEST)
        assert value['status'] == 'UNKNOWN' and value['client_to_upstream'] is None
    assert eb.summarize(raw, DIGEST)['status'] == 'COMPLETE'


def test_checkpoint_lower_bounds_survive_interruption() -> None:
    raw = wire(records()[:-1], trailer=False)
    for interrupted in (raw, raw + b'{"partial'):
        value = eb.summarize(interrupted, DIGEST)
        assert value['status'] == 'UNKNOWN'
        assert value['observed_lower_bound'] == {'client_to_upstream': 7, 'upstream_to_client': 11}
        assert value['client_to_upstream'] is None


def test_multiple_tunnels_and_requests_are_still_only_byte_observations() -> None:
    first = records(11, 19)
    second = records(23, 29)[1:]
    for row in second:
        if row.get('event') == 'bytes':
            row['connection'] = 2
    raw = wire(first + second)
    # wire's committed trailer generator must reflect every final, in order.
    value = eb.summarize(raw, DIGEST)
    assert value['status'] == 'COMPLETE' and value['connections'] == 2
    assert value['client_to_upstream'] == 34 and value['upstream_to_client'] == 48
    assert value['limitation'] == eb.LIMITATION


def test_read_boundary_counts_even_when_drain_fails() -> None:
    namespace: dict[str, Any] = {'__name__': 'controlled'}
    exec(compile(eb.proxy_source(), '<controlled-proxy>', 'exec'), namespace)  # noqa: S102
    emitted: list[dict[str, Any]] = []
    connection = namespace['ByteConnection'](emitted.append, GENERATION, 1, 'api.nhle.com:443', {})

    class Reader:
        async def read(self, _size: int) -> bytes:
            return b'\x16\x03\x03planted'

    class Writer:
        def write(self, _raw: bytes) -> None:
            pass

        async def drain(self) -> None:
            raise OSError('controlled delivery failure')

        def close(self) -> None:
            pass

    asyncio.run(namespace['_pipe'](Reader(), Writer(), connection, 'client'))
    connection.record('error')
    assert connection.failed and emitted[-1]['client_to_upstream'] == 10
    assert emitted[-1]['state'] == 'error'


def test_long_tunnel_checkpoints_use_cumulative_counts_without_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace: dict[str, Any] = {'__name__': 'controlled'}
    exec(compile(eb.proxy_source(), '<controlled-proxy>', 'exec'), namespace)  # noqa: S102
    emitted: list[dict[str, Any]] = []
    connection = namespace['ByteConnection'](emitted.append, GENERATION, 1, 'api.nhle.com:443', {})
    ticks = []

    class ControlledEnd(Exception):
        pass

    async def sleep(seconds: float) -> None:
        ticks.append(seconds)
        if len(ticks) == 3:
            raise ControlledEnd
        connection.observe('client', 7)

    monkeypatch.setattr(namespace['asyncio'], 'sleep', sleep)
    with pytest.raises(ControlledEnd):
        asyncio.run(connection.checkpoint())
    assert ticks == [1, 1, 1]
    assert [row['sequence'] for row in emitted] == [0, 1, 2]
    assert [row['client_to_upstream'] for row in emitted] == [0, 7, 14]
    assert [row['state'] for row in emitted] == ['open', 'progress', 'progress']


def test_source_anchor_drift_refuses_instead_of_silently_losing_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    from skillc import egress
    assert 'class ByteConnection' in eb.proxy_source()
    monkeypatch.setattr(egress, 'PROXY_SOURCE', egress.PROXY_SOURCE.replace('import asyncio,', 'import asyncio as loop,'))
    with pytest.raises(RuntimeError, match='anchor drift'):
        eb.proxy_source()


def test_duplicate_wire_keys_and_oversized_input_are_unknown() -> None:
    raw = wire(records()).replace(b'"sequence": 1', b'"sequence": 0, "sequence": 1', 1)
    assert eb.summarize(raw, DIGEST)['status'] == 'UNKNOWN'
    assert eb.summarize(b'x' * (eb.MAX_CAPTURE + 1), DIGEST)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('failure', ['signal-exit', 'signal-timeout', 'no-handler', 'read-unavailable'])
def test_final_capture_failures_are_unavailable_without_touching_destroy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    backend, _session = configured(tmp_path)
    clock = [0.0]
    monkeypatch.setattr(db.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(db.time, 'sleep', lambda amount: clock.__setitem__(0, clock[0] + amount))
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> Any:
        calls.append(argv)
        assert kwargs['timeout'] <= 3
        if 'kill' in argv:
            assert argv[-3:] == ['--signal', 'SIGUSR1', 'controlled-proxy']
            if failure == 'signal-timeout':
                raise subprocess.TimeoutExpired(argv, 3)
            return SimpleNamespace(returncode=1 if failure == 'signal-exit' else 0, stdout=b'')
        return SimpleNamespace(returncode=1 if failure == 'read-unavailable' else 0,
                               stdout=wire(records(), trailer=False))

    monkeypatch.setattr(db.subprocess, 'run', run)
    result = backend.finalize_egress_log(db._Handle('synthetic', 'controlled', {}, egress_proxy='controlled-proxy'))
    assert eb.summarize(result, DIGEST)['status'] == 'UNKNOWN'
    assert clock[0] <= 3.01 and all('rm' not in argv for argv in calls)


@pytest.mark.parametrize('raw', [None, False, 0, [], {}, 'not-bytes', b'x' * (eb.MAX_CAPTURE + 1)])
def test_bounded_backend_capture_refuses_bad_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: object,
) -> None:
    backend, _session = configured(tmp_path)
    monkeypatch.setattr(db.subprocess, 'run', lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=raw))
    assert backend.egress_log(db._Handle('synthetic', 'controlled', {}, egress_proxy='controlled-proxy')) is None


@pytest.mark.parametrize('kind', ['root', 'attempt', 'proxy', 'name', 'revoked'])
@pytest.mark.parametrize('value', [None, False, 0, [], {}, 'other'])
def test_final_signal_requires_registered_attempt_and_derived_owned_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, value: Any,
) -> None:
    backend, session = configured(tmp_path)
    handle: Any = db._Handle('synthetic', 'controlled', {}, egress_proxy='controlled-proxy')
    if kind == 'root':
        handle = value
    elif kind == 'attempt':
        handle = db._Handle(value, 'controlled', {}, egress_proxy='controlled-proxy')
    elif kind == 'proxy':
        handle = db._Handle('synthetic', 'controlled', {}, egress_proxy=value)
    elif kind == 'name':
        handle = db._Handle('synthetic', value, {}, egress_proxy='controlled-proxy')
    else:
        session._permits.clear()
    calls = []
    monkeypatch.setattr(db.subprocess, 'run', lambda *_a, **_k: calls.append(True))
    assert backend.finalize_egress_log(handle) is None and calls == []


@pytest.mark.parametrize('mutant', json.loads((ROOT / 'controls/connect-bytes/mutants.json').read_text()),
                         ids=lambda row: row['name'])
def test_committed_mutants_lose_on_their_known_bad_witness(mutant: dict[str, str]) -> None:
    source = inspect.getsource(eb._summarize)
    assert source.count(mutant['before']) == 1
    source = source.replace(mutant['before'], mutant['after'])
    namespace = dict(vars(eb))
    exec(compile(source, '<controlled-byte-mutant>', 'exec'), namespace)  # noqa: S102
    raw = wire(records())
    if mutant['witness'] == 'no-trailer':
        raw = wire(records(), trailer=False)
    elif mutant['witness'] == 'middle-change':
        raw = raw.replace(b'"client_to_upstream": 7', b'"client_to_upstream": 6', 1)
    elif mutant['witness'] == 'regressed':
        rows = records()
        rows[-1]['client_to_upstream'] = 1
        raw = wire(rows)
    intact = eb.summarize(raw, DIGEST)
    broken = namespace['_summarize'](raw, DIGEST)
    if mutant['name'] == 'always-zero':
        assert intact['status'] == 'COMPLETE' and intact['client_to_upstream'] == 7
        with pytest.raises(AssertionError):
            assert broken['client_to_upstream'] == 7
    else:
        assert intact['status'] == 'UNKNOWN'
        with pytest.raises(AssertionError):
            assert broken['status'] == 'UNKNOWN'
