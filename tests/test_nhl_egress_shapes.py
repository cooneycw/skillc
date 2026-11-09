"""One closed table checks every new JSON/provenance boundary's error contract.

Some old summary cases already failed closed by returning evidence instead of
raising. Their table red qualifies the new explicit refusal API, not an old
false-absence or authorization claim. Correct legacy dictionaries are twins.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from test_nhl_egress_behavior import ROOT, data, summary
from test_nhl_egress_policy import configured

from skillc import calibration_run as cr
from skillc import docker_backend as db
from skillc import nhl_egress_policy as nhl
from skillc import trial

MATRIX = json.loads((ROOT / 'controls/nhl-egress/shapes.json').read_text())
CASES = [(level, shape) for level in MATRIX['levels'] for shape in MATRIX['wrong']
         if not (level == 'stored-config' and shape in ('missing', 'extra'))
         and not (level in ('allowed', 'denied', 'upstream-failed') and shape == 'missing')
         and not (level in ('stop-flag', 'live-selector') and shape == 'boolean')
         and not (level in ('peer-rejected', 'count-value') and shape == 'integer')
         and not (level == 'connect-target' and shape == 'string')]
CASES += [(level, shape) for level in ('peer-rejected', 'count-value') for shape in MATRIX['wrong_counts']]


@pytest.mark.parametrize('level,shape', CASES, ids=[f'{a}/{b}' for a, b in CASES])
def test_every_new_input_shape_ends_in_a_controlled_module_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: str, shape: str,
) -> None:
    bad = copy.deepcopy({**MATRIX['wrong'], **MATRIX['wrong_counts']}[shape])
    backend, session = configured(tmp_path)
    permit = backend.nhl_egress_permit
    assert isinstance(permit, nhl.Permit)
    good = summary({}, {})
    policy = session.policy
    refused: tuple[type[Exception], ...] = (nhl.PolicyRefused, cr.CalibrationRefused)
    with pytest.raises(refused):
        if level == 'session-declaration':
            nhl.Session(bad)
        elif level == 'policy-block':
            raw = data()
            raw['nhl_egress'] = {**raw['nhl_egress'], 'unexpected': True} if shape == 'extra' else bad
            nhl.parse(raw)
        elif level in ('policy-version', 'policy-purpose-json', 'policy-hosts', 'policy-port', 'policy-stop'):
            raw = data()
            key = {'policy-version': 'version', 'policy-purpose-json': 'purpose',
                   'policy-hosts': 'hosts', 'policy-port': 'port', 'policy-stop': 'stop_on_denied'}[level]
            raw['nhl_egress'][key] = bad
            nhl.Session(raw)
        elif level in ('declared-network', 'network-policy', 'network-digest', 'network-flags', 'approval'):
            raw = data()
            if level == 'approval':
                raw['approval'] = bad
            elif level == 'declared-network':
                raw['shared']['agent_network'] = bad
            else:
                key = {'network-policy': 'policy', 'network-digest': 'allowlist_digest',
                       'network-flags': 'codex_server_side_off'}[level]
                raw['shared']['agent_network'][key] = bad
            nhl.Session(raw)
        elif level.startswith('stored-'):
            value = bad
            if level == 'stored-binding':
                binding = {'declaration': data(), 'unexpected': True} if shape == 'extra' else bad
                value = {'nhl_egress': binding}
            elif level == 'stored-declaration':
                value = {'nhl_egress': {'declaration': bad}}
            experiment = SimpleNamespace(root=tmp_path, attempts=lambda: iter([
                ({'config': {'digest': 'a' * 64}}, {})]))
            monkeypatch.setattr(trial.Experiment, 'open', lambda _root: experiment)
            monkeypatch.setattr(trial, '_read_object', lambda *_a: json.dumps(value).encode())
            cr.build_report(cast(trial.Experiment, experiment), [], declared_model='fixed', declared_effort='fixed')
        elif level == 'summary':
            nhl.violation({**good, 'unexpected': True} if shape == 'extra' else bad, policy)
        elif level == 'summary-policy':
            nhl.violation(good, cast(nhl.Policy, bad))
        elif level in ('allowed', 'denied', 'upstream-failed', 'unparsed-lines', 'stop-flag'):
            key = {'upstream-failed': 'upstream_failed', 'unparsed-lines': 'unparsed_lines',
                   'stop-flag': 'controller_policy_stop'}.get(level, level)
            if level in ('allowed', 'denied', 'upstream-failed') and shape == 'extra':
                bad = {'invalid-target': 'invalid-count'}
            nhl.violation({**good, key: bad}, policy)
        elif level == 'peer-rejected':
            nhl.violation({**good, 'peer_rejected': bad}, policy)
        elif level == 'count-value':
            nhl.violation({**good, 'allowed': {'api.nhle.com:443': bad}}, policy)
        elif level == 'optional-digest':
            nhl.violation({**good, 'digest': bad}, policy)
        elif level == 'connect-target':
            policy.allowed(bad)
        elif level == 'policy-purpose':
            nhl.violation(good, nhl.Policy(bad))
        elif level in ('backend-hosts', 'backend-egress'):
            object.__setattr__(backend, 'egress_hosts' if level == 'backend-hosts' else 'egress', bad)
            nhl.require_backend(backend, 'synthetic')
        elif level in ('permit-policy', 'permit-stopped', 'permit-issuer'):
            forged = nhl.Permit(cast(nhl.Session, bad), 'synthetic')
            if level == 'permit-policy':
                _ = forged.policy
            elif level == 'permit-stopped':
                _ = forged.stopped
            else:
                forged.require(backend, 'synthetic')
        elif level == 'permit-stop':
            nhl.Permit(session, bad).stop()
        elif level == 'require-permit':
            session.require(cast(nhl.Permit, bad), backend, 'synthetic', live=False)
        elif level in ('bind-hosts', 'bind-egress'):
            fresh = session.issue('unbound')
            other = db.DockerBackend('fake-image', tmp_path,
                                     egress=bad if level == 'bind-egress' else True,
                                     egress_hosts=bad if level == 'bind-hosts' else policy.hosts,
                                     nhl_egress_permit=fresh)
            session.bind(fresh, other)
        elif level == 'bind-permit':
            session.bind(cast(nhl.Permit, bad), backend)
        elif level == 'bind-backend':
            fresh = session.issue('unbound')
            session.bind(fresh, bad)
        elif level == 'backend-input':
            nhl.require_backend(bad, 'synthetic')
        elif level == 'issue-attempt':
            session.issue(bad)
        elif level == 'require-attempt':
            permit.require(backend, bad)
        elif level == 'live-selector':
            permit.require(backend, 'synthetic', live=bad)
        else:
            raise AssertionError('unrecognized committed input level')


def test_shape_population_and_valid_legacy_twins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {'session-declaration', 'policy-block', 'stored-config', 'stored-binding',
                'stored-declaration', 'summary', 'summary-policy', 'allowed', 'denied', 'upstream-failed',
                'unparsed-lines', 'stop-flag', 'bind-permit', 'bind-backend', 'backend-input',
                'issue-attempt', 'require-attempt', 'live-selector', 'permit-policy', 'permit-stopped',
                'permit-stop', 'permit-issuer', 'backend-hosts', 'backend-egress', 'peer-rejected',
                'count-value', 'optional-digest', 'connect-target', 'policy-purpose', 'require-permit',
                'policy-version', 'policy-purpose-json', 'policy-hosts', 'policy-port', 'policy-stop',
                'declared-network', 'network-policy', 'network-digest', 'network-flags', 'approval',
                'bind-hosts', 'bind-egress'}
    assert len(MATRIX['levels']) == len(expected) and set(MATRIX['levels']) == expected
    assert len(MATRIX['wrong']) == 7
    backend, session = configured(tmp_path)
    assert nhl.require_backend(backend, 'synthetic') == session.policy
    assert nhl.violation(summary({}, {}), session.policy) is None
    # Config dictionaries without the opt-in remain valid extensible legacy
    # inputs; making these strict would break historical studies.
    for value in ({}, {'unrelated_legacy_field': True}):
        experiment = SimpleNamespace(root=tmp_path, attempts=lambda: iter([
            ({'config': {'digest': 'a' * 64}}, {})]))
        monkeypatch.setattr(trial, '_read_object', lambda *_a, value=value: json.dumps(value).encode())
        assert cr._report_nhl_policy(cast(trial.Experiment, experiment)) is None
