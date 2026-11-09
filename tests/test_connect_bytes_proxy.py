"""The shipped proxy's byte stream, signal and frozen-log behavior on loopback."""
from __future__ import annotations

import json
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from test_connect_bytes_behavior import DOCUMENT
from test_egress import _free_port

from skillc import egress as eg
from skillc import nhl_egress_policy as nhl


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
        deadline = time.monotonic() + 5
        while not log.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
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
