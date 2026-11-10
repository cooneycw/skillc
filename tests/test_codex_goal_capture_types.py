"""Complete wrong-type sweep of the new public goal custody inputs (#637)."""
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from skillc import codex_goal as g
from skillc import codex_goal_capture as c

BAD: list[Any] = [None, True, False, 0, -1, 1.5, float('nan'), float('inf'), '', 'x', b'x', [], {}, [1], {'x': 1}]
IDS = [f't{i}' for i in range(len(BAD))]
CONTEXT: dict[str, Any] = {'attempt_id': 'attempt', 'approved_declaration_digest': 'sha256:' + 'a' * 64,
    'client_version': g.CLIENT_VERSION, 'model': 'model', 'objective': 'objective', 'recorded_token_budget': 1}
REFERENCE: dict[str, Any] = {'version': 1, 'context_digest': 'sha256:' + 'a' * 64,
    'digest': 'sha256:' + 'b' * 64, 'size': 1}


@pytest.mark.parametrize('bad', BAD, ids=IDS)
@pytest.mark.parametrize('field', list(CONTEXT))
def test_context_field_sweep(field: str, bad: Any) -> None:
    candidate = {**CONTEXT, field: bad}
    # Valid values from another category are explicitly excluded, not asserted bad.
    if field in ('attempt_id', 'model', 'objective', 'client_version') and type(bad) is str and bad:
        return
    with pytest.raises(c.CaptureUnavailable):
        c.parse_context(candidate)


@pytest.mark.parametrize('bad', BAD, ids=IDS)
@pytest.mark.parametrize('field', list(REFERENCE))
def test_reference_field_sweep(field: str, bad: Any) -> None:
    with pytest.raises(c.CaptureUnavailable):
        c.parse_reference({**REFERENCE, field: bad})


@pytest.mark.parametrize('bad', BAD, ids=IDS)
def test_closed_parser_root_sweep(bad: Any) -> None:
    for parser in (c.parse_context, c.parse_reference):
        with pytest.raises(c.CaptureUnavailable):
            parser(bad)


@pytest.mark.parametrize('bad', BAD, ids=IDS)
@pytest.mark.parametrize('argument', ['root', 'reference', 'expected'])
def test_verifier_argument_sweep(tmp_path: Path, argument: str, bad: Any) -> None:
    args = {'root': tmp_path, 'reference': c.Reference(**REFERENCE), 'expected': c.Context(**CONTEXT)}
    args[argument] = bad
    assert c.verify(**args)['status'] == 'UNKNOWN'


@pytest.mark.parametrize('bad', BAD, ids=IDS)
@pytest.mark.parametrize('argument', ['root', 'context'])
def test_capture_constructor_sweep(tmp_path: Path, argument: str, bad: Any) -> None:
    args = {'root': tmp_path / 'capture', 'context': c.Context(**CONTEXT)}
    args[argument] = bad
    with pytest.raises(c.CaptureUnavailable):
        c.Capture(**args)
    assert not (tmp_path / 'capture').exists()


@pytest.fixture
def capture(tmp_path: Path):
    writer = c.Capture(tmp_path / 'capture', c.Context(**CONTEXT))
    writer.bind_transport()
    writer.bind_session(client_version=g.CLIENT_VERSION, model='model', objective='objective', budget=1)
    try:
        yield writer
    finally:
        writer.close()


@pytest.mark.parametrize('bad', BAD, ids=IDS)
@pytest.mark.parametrize('argument', ['direction', 'raw'])
def test_frame_argument_sweep(capture: c.Capture, argument: str, bad: Any) -> None:
    args = {'direction': 'received', 'raw': b'{}\n'}
    args[argument] = bad
    with pytest.raises(c.CaptureUnavailable):
        capture.frame(**args)
    assert capture.failed


@pytest.mark.parametrize('bad', BAD, ids=IDS)
def test_event_root_sweep(capture: c.Capture, bad: Any) -> None:
    with pytest.raises(c.CaptureUnavailable):
        capture.event(bad)
    assert capture.failed


@pytest.mark.parametrize('bad', BAD, ids=IDS)
@pytest.mark.parametrize('field', ['seq', 'kind'])
def test_event_field_sweep(capture: c.Capture, field: str, bad: Any) -> None:
    with pytest.raises(c.CaptureUnavailable):
        capture.event({'seq': 1, 'kind': 'request', field: bad})
    assert capture.failed


@pytest.mark.parametrize('bad', BAD, ids=IDS)
@pytest.mark.parametrize('field', ['client_version', 'model', 'objective', 'budget'])
def test_bind_session_field_sweep(tmp_path: Path, field: str, bad: Any) -> None:
    capture = c.Capture(tmp_path / 'capture', c.Context(**CONTEXT))
    try:
        capture.bind_transport()
        args = {'client_version': g.CLIENT_VERSION, 'model': 'model', 'objective': 'objective', 'budget': 1}
        args[field] = bad
        with pytest.raises(c.CaptureUnavailable):
            capture.bind_session(**args)
        assert not capture.session_bound
    finally:
        capture.close()


@pytest.mark.parametrize('bad', BAD, ids=IDS)
def test_existing_adapter_capture_seam_sweep(bad: Any) -> None:
    if bad is None:  # Explicit legacy, uncaptured diagnostic mode.
        return
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd, 'rb', buffering=0) as reader, os.fdopen(write_fd, 'wb', buffering=0) as writer:
        with pytest.raises(g.GoalRefused):
            g.JsonLineTransport(reader, writer, wire=lambda *_: None, capture=bad)
        with pytest.raises(g.GoalRefused):
            g.GoalSession(None, objective='objective', model='model', comparison_sessions=[
                {'session': 'worker', 'role': 'worker', 'token_budget': 1}], capture=bad)


def test_closed_field_sets_and_boolean_integer_boundaries() -> None:
    for parser, row in ((c.parse_context, CONTEXT), (c.parse_reference, REFERENCE)):
        for candidate in ({**row, 'extra': 1}, {key: val for key, val in row.items() if key != next(iter(row))}):
            with pytest.raises(c.CaptureUnavailable):
                parser(candidate)
    assert c.parse_context(CONTEXT).recorded_token_budget == 1
    assert asdict(c.parse_reference(REFERENCE)) == REFERENCE
