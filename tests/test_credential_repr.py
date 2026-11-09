"""Memory-only synthetic credentials must stay out of ordinary diagnostics."""
from __future__ import annotations

import dataclasses
import traceback
from dataclasses import dataclass, field
from functools import partial
from typing import Any

import pytest
from test_remnant_scan import PrivateOutput, no_marker, references
from test_remnant_scan import audit_captured_output as audit_captured_output  # noqa: PLC0414

from skillc import credential_steward as cs
from skillc import remnant_scan as rs
from skillc.attempt_guard import AttemptGuard
from skillc.fixture_attempt import AttemptFixture, FixtureSession
from skillc.judge_anthropic import AnthropicJudge
from skillc.managed_backend import ManagedBackend, _Handle


@dataclass(repr=False)
class PrivateSubject:
    value: object = field(repr=False)
    refs: rs.References = field(repr=False)

    def __repr__(self) -> str:
        return '<PrivateSubject redacted>'


def subject(kind: str) -> PrivateSubject:
    refs = references()
    text = refs._values[0].decode('utf-8')
    driver = cs.CredentialSteward(cs.CredentialStewardSession('synthetic-attempt'), cs.HOME_CODEX)
    driver.final_vault = refs._values[0]
    # Error diagnostics can contain private material too. The complete driver
    # repr must not become unsafe through another field after vault redaction.
    driver.failure = text
    if kind == 'driver':
        value: object = driver
    elif kind == 'attempt-guard':
        guard = AttemptGuard('synthetic-attempt')
        guard.steward_driver = driver
        value = guard
    elif kind == 'fixture-session':
        fixture = AttemptFixture('synthetic-case', {}, {}, lambda _root, _facts: {})
        holder = FixtureSession(fixture, 'synthetic-attempt')
        holder.steward_driver = driver
        value = holder
    elif kind == 'managed-handle':
        value = _Handle('synthetic-attempt', text)
    elif kind == 'managed-backend':
        value = ManagedBackend(None, credential=text)
    elif kind == 'judge-provider':
        # A lawful callable provider may itself carry the credential in repr.
        # No provider or API is invoked to test this representation boundary.
        value = AnthropicJudge(partial(str, text), {})
    elif kind == 'references':
        value = refs
    else:
        assert kind == 'patterns'
        value = rs._Patterns((('raw', refs._values[0]),))
    return PrivateSubject(value, refs)


def frame_with_subject(value: object) -> bytes:
    """The traceback's actual failing frame holds the driver/holder itself."""
    try:
        raise RuntimeError('synthetic diagnostic')
    except RuntimeError as error:
        return ''.join(traceback.TracebackException.from_exception(error, capture_locals=True).format()).encode()


@pytest.mark.parametrize('kind', ['driver', 'attempt-guard', 'fixture-session', 'managed-handle',
                                  'managed-backend', 'judge-provider', 'references', 'patterns'])
@pytest.mark.parametrize('render', ['repr', 'str', 'traceback-with-locals'])
def test_credential_material_never_enters_diagnostic_representation(kind: str, render: str) -> None:
    private = subject(kind)
    if render == 'repr':
        output = PrivateOutput(repr(private.value).encode())
    elif render == 'str':
        output = PrivateOutput(str(private.value).encode())
    else:
        output = PrivateOutput(frame_with_subject(private.value))
    no_marker(output.data, private.refs)


@pytest.mark.parametrize('class_,name', [
    (cs.CredentialSteward, 'final_vault'), (AttemptGuard, 'steward_driver'),
    (FixtureSession, 'steward_driver'), (_Handle, 'token'), (ManagedBackend, 'credential'),
    (AnthropicJudge, 'key_provider'), (rs.References, '_values'), (rs._Patterns, 'values'),
])
def test_credential_bearing_fields_are_explicitly_excluded(class_: Any, name: str) -> None:
    assert next(row for row in dataclasses.fields(class_) if row.name == name).repr is False


def test_no_marker_oracle_refuses_a_deliberately_leaking_renderer() -> None:
    private = subject('driver')
    with pytest.raises(AssertionError, match='privacy control refused'):
        no_marker(repr(private.refs._values[0]).encode(), private.refs)
    no_marker(repr(private).encode(), private.refs)
