"""Existing transport API regressions; run unchanged on 20bfbd4 (#637)."""
from __future__ import annotations

import os
import select

import pytest

from skillc import codex_goal as g


def test_failed_capture_prevents_any_dispatch() -> None:
    read_fd, write_fd = os.pipe()
    def unavailable(direction: str, raw: bytes) -> None:
        raise OSError('capture unavailable')
    with os.fdopen(read_fd, 'rb', buffering=0) as reader, os.fdopen(write_fd, 'wb', buffering=0) as writer:
        transport = g.JsonLineTransport(reader, writer, wire=unavailable)
        with pytest.raises(OSError, match='capture unavailable'):
            transport.send({'id': 1})
        assert not select.select([reader], [], [], 0)[0], 'dispatch preceded durable capture'


def test_partial_frame_is_retained_before_eof() -> None:
    read_fd, write_fd = os.pipe()
    captured: list[tuple[str, bytes]] = []
    with os.fdopen(read_fd, 'rb', buffering=0) as reader:
        with os.fdopen(write_fd, 'wb', buffering=0) as writer:
            writer.write(b'{"id":1')
        transport = g.JsonLineTransport(reader, reader, wire=lambda d, b: captured.append((d, b)))
        with pytest.raises(EOFError):
            transport.receive()
        assert captured == [('received-partial', b'{"id":1')]
