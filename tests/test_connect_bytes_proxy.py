"""The shipped proxy's byte stream, signal and frozen-log behavior on loopback."""
from __future__ import annotations

import json
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from test_connect_bytes_behavior import DOCUMENT
from test_egress import _free_port

from skillc import egress as eg
from skillc import nhl_egress_policy as nhl


def await_proxy_start(
    log: Path, digest: str, alive: Callable[[], bool], *,
    clock: Callable[[], float] = time.monotonic, pause: Callable[[float], None] = time.sleep,
) -> None:
    """The proxy's start record means bound; mere log creation does not."""
    deadline = clock() + 5
    while clock() < deadline:
        assert alive(), 'proxy exited before recording its listening start'
        try:
            with log.open('rb') as stream:
                entry = json.loads(stream.readline(65536))
        except (OSError, ValueError):
            entry = None
        if isinstance(entry, dict) and entry.get('event') == 'start' and entry.get('digest') == digest:
            assert alive(), 'proxy exited after recording its listening start'
            return
        pause(min(0.01, max(0, deadline - clock())))
    raise AssertionError('proxy did not record its listening start within 5 seconds')


@pytest.mark.parametrize('kind', ['empty', 'partial', 'wrong-root', 'wrong-digest', 'dead'])
def test_start_guard_refuses_created_log_without_live_bound_start(tmp_path: Path, kind: str) -> None:
    log = tmp_path / 'proxy.log'
    log.write_bytes({'empty': b'', 'partial': b'{', 'wrong-root': b'null\n',
                     'wrong-digest': b'{"event":"start","digest":"wrong"}\n',
                     'dead': b'{"event":"start","digest":"expected"}\n'}[kind])
    clock = [0.0]
    def pause(seconds: float) -> None:
        clock[0] += seconds
    with pytest.raises(AssertionError, match='proxy (exited|did not record)'):
        await_proxy_start(log, 'expected', lambda: kind != 'dead', clock=lambda: clock[0], pause=pause)
    assert clock[0] <= 5


def test_start_guard_waits_past_empty_log_until_live_start(tmp_path: Path) -> None:
    log = tmp_path / 'proxy.log'
    log.touch()
    clock = [0.0]
    pauses = []
    def pause(seconds: float) -> None:
        pauses.append(seconds)
        clock[0] += seconds
        log.write_text('{"event":"start","digest":"expected"}\n')
    await_proxy_start(log, 'expected', lambda: True, clock=lambda: clock[0], pause=pause)
    assert pauses == [0.01]  # A blind file-exists guard would return before this.


def test_start_guard_control_defeats_the_old_file_exists_mutant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def blind(log: Path, *_args: object, **_kwargs: object) -> None:
        assert log.exists()
    monkeypatch.setitem(globals(), 'await_proxy_start', blind)
    with pytest.raises(AssertionError):
        test_start_guard_waits_past_empty_log_until_live_start(tmp_path)


@pytest.mark.parametrize('chunks', [[], [b'\x16\x03\x03one', b'two\x00'], [b'a' * 65537]])
def test_shipped_proxy_counts_chopped_streams_and_quiesces_once(tmp_path: Path, chunks: list[bytes]) -> None:
    upstream = socket.socket()
    upstream.bind(('127.0.0.1', 0))
    upstream.listen()
    upstream.settimeout(5)
    up_port = upstream.getsockname()[1]
    payload = b''.join(chunks)
    response = b'reply:' + payload if payload else b''
    observed: list[bytes] = []
    errors: list[BaseException] = []

    def respond() -> None:
        try:
            conn, _ = upstream.accept()
            with conn:
                conn.settimeout(5)
                data = bytearray()
                while len(data) < len(payload):
                    part = conn.recv(4096)
                    if not part:
                        break
                    data.extend(part)
                observed.append(bytes(data))
                conn.sendall(response)
        except OSError as exc:
            errors.append(exc)

    thread = threading.Thread(target=respond, daemon=True)
    thread.start()
    document = {**DOCUMENT, 'hosts': ['127.0.0.1']}
    argv = eg.proxy_run_argv(['docker'], image='synthetic', name='controlled', labels={},
                             container_user='candidate', subnet='127.0.0.0/8', policy_document=document)
    shipped = argv[argv.index('-c') + 1]
    source = shipped.replace('port != "443"', f'port != "{up_port}"')
    assert source.replace(f'port != "{up_port}"', 'port != "443"') == shipped
    port, log = _free_port(), tmp_path / 'proxy.log'
    proc = subprocess.Popen([sys.executable, '-c', source, str(port), str(log), json.dumps(document),
                             eg.document_digest(document), '127.0.0.0/8'])
    try:
        await_proxy_start(log, eg.document_digest(document), lambda: proc.poll() is None)
        with socket.create_connection(('127.0.0.1', port), timeout=5) as client:
            client.sendall(f'CONNECT 127.0.0.1:{up_port} HTTP/1.1\r\n\r\n'.encode())
            assert client.recv(200).startswith(b'HTTP/1.1 200')
            for chunk in chunks:
                client.sendall(chunk)
            actual = bytearray()
            while len(actual) < len(response):
                part = client.recv(65536)
                if not part:
                    break
                actual.extend(part)
            assert bytes(actual) == response
        thread.join(5)
        assert not thread.is_alive() and not errors and observed == [payload]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            rows = [json.loads(line) for line in log.read_bytes().splitlines()]
            if any(row.get('state') == 'final' for row in rows):
                break
            time.sleep(0.01)
        # This assertion is an output regression on pre-fix main, not API absence.
        assert any(row.get('state') == 'final' for row in rows)
        proc.send_signal(signal.SIGUSR1)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            captured = log.read_bytes()
            if json.loads(captured.splitlines()[-1]).get('event') == 'bytes-end':
                break
            time.sleep(0.01)
        value = nhl.summarize_log(captured)['bytes_observed']
        assert isinstance(value, dict)
        assert value['status'] == 'COMPLETE'
        assert value['client_to_upstream'] == len(payload)
        assert value['upstream_to_client'] == len(response)
        proc.send_signal(signal.SIGUSR1)
        with pytest.raises(OSError):
            socket.create_connection(('127.0.0.1', port), timeout=0.2)
        time.sleep(0.05)
        assert proc.poll() is None and log.read_bytes() == captured
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        upstream.close()
