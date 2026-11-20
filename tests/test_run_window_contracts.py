"""#797 A-3b1: the opt-in `run_window_contracts` declaration.

New instruments: the closed schema, the census ceilings, the fixed disposition
table, the five calibration plumbing sites, and the census budget check at
admission. The regression guard that a non-opted declaration behaves exactly
as on the parent is `tests/test_run_window_contracts_legacy.py`.
"""
from __future__ import annotations

import copy
from typing import Any, cast

import pytest
from conftest import stamp_approval
from test_calibration import ROOT
from test_calibration_discrimination_declaration import _approved as discrimination
from test_vm_credential_window_declaration import data as window_data

from skillc import calibration, remnant_scan
from skillc import run_window_contracts as rc


ONLY_CALIBRATION = 'run_window_contracts is supported only for calibration-declaration'


def contracts() -> dict[str, Any]:
    return {'version': 1, 'limits': {'max_entries': 1024, 'max_depth': 16}}


def data() -> dict[str, Any]:
    return stamp_approval({**window_data(), rc.KEY: contracts()})


def test_a_valid_opt_in_parses_and_normalizes() -> None:
    decl = calibration.parse_declaration(data())
    assert rc.validate_plan(decl.data) == {'version': 1, 'limits': contracts()['limits'],
                                           'disposition': dict(rc.DISPOSITION)}


FAULTS = ['unknown-field', 'missing-limits', 'boolean-version', 'version-two',
          'entries-over-ceiling', 'depth-over-ceiling', 'zero-limit', 'boolean-limit',
          'extra-limit', 'missing-credential-window', 'not-an-object']


@pytest.mark.parametrize('fault', FAULTS)
def test_invalid_opt_in_is_refused(fault: str) -> None:
    raw = data()
    field = raw[rc.KEY]
    if fault == 'unknown-field':
        field['roots'] = ['/home']
    elif fault == 'missing-limits':
        del field['limits']
    elif fault == 'boolean-version':
        field['version'] = True
    elif fault == 'version-two':
        field['version'] = 2
    elif fault == 'entries-over-ceiling':
        field['limits']['max_entries'] = remnant_scan.LIMITS['entries'] + 1
    elif fault == 'depth-over-ceiling':
        field['limits']['max_depth'] = remnant_scan.LIMITS['depth'] + 1
    elif fault == 'zero-limit':
        field['limits']['max_depth'] = 0
    elif fault == 'boolean-limit':
        field['limits']['max_entries'] = True
    elif fault == 'extra-limit':
        field['limits']['max_bytes'] = 1
    elif fault == 'missing-credential-window':
        del raw['credential_window']
    else:
        raw[rc.KEY] = ['version', 1]
    with pytest.raises(calibration.DeclarationRefused, match='run_window_contracts'):
        calibration.parse_declaration(stamp_approval(raw))


class Sneaky(str):
    """A str subclass that compares equal to a declared key."""


class Exploding:
    """A key that hashes like a declared key but whose equality raises with
    supplied text, so building a set of keys would raise it."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        raise RuntimeError('supplied-marker-text')


@pytest.mark.parametrize('where', ['top', 'limits'])
@pytest.mark.parametrize('key', ['subclass', 'exploding'])
def test_non_string_keys_are_refused_with_fixed_text(where: str, key: str) -> None:
    """Directly against the validator, so no serialization can mask it."""
    plan = contracts()
    target = plan if where == 'top' else plan['limits']
    name = 'version' if where == 'top' else 'max_entries'
    value = target.pop(name)
    target[Sneaky(name) if key == 'subclass' else Exploding(name)] = value
    with pytest.raises(rc.ContractsRefused) as info:
        rc.validate_plan({**data(), rc.KEY: plan})
    assert 'supplied-marker-text' not in str(info.value)
    assert str(info.value) in ('run_window_contracts: invalid declared contracts',
                               'run_window_contracts: invalid census limits')


def test_ceilings_are_the_scan_limits_and_the_maximum_is_accepted() -> None:
    raw = data()
    raw[rc.KEY]['limits'] = {'max_entries': remnant_scan.LIMITS['entries'],
                             'max_depth': remnant_scan.LIMITS['depth']}
    calibration.parse_declaration(stamp_approval(raw))


def test_dispositions_are_fixed_by_class() -> None:
    new = {'login-home', 'scratch-tmp', 'scratch-vartmp', 'scratch-shm'}
    assert set(rc.DISPOSITION) == set(remnant_scan.CLASSES) | new
    removed = {k for k, v in rc.DISPOSITION.items() if v == rc.REMOVED}
    assert removed == {'home', 'vault', 'staging', *new}
    assert {k for k, v in rc.DISPOSITION.items() if v == rc.RETAINED} == {
        'stdout', 'transcript', 'cache-log', 'export-payload'}
    # Nothing in the declaration can change a disposition.
    raw = data()
    raw[rc.KEY]['disposition'] = {'home': rc.RETAINED}
    with pytest.raises(calibration.DeclarationRefused, match='run_window_contracts'):
        calibration.parse_declaration(stamp_approval(raw))


def test_discrimination_declarations_refuse_the_key() -> None:
    raw = discrimination()
    raw[rc.KEY] = contracts()
    with pytest.raises(calibration.DeclarationRefused, match=ONLY_CALIBRATION):
        calibration.parse_discrimination_declaration(raw)


def test_discrimination_approval_checks_refuse_the_key() -> None:
    decl = calibration.parse_discrimination_declaration(discrimination())
    cast(dict[str, Any], decl.data)[rc.KEY] = contracts()
    with pytest.raises(calibration.DeclarationRefused, match=ONLY_CALIBRATION):
        calibration.require_discrimination_approval_record(decl)
    with pytest.raises(calibration.DeclarationRefused, match=ONLY_CALIBRATION):
        calibration.require_approved_discrimination(decl, ROOT)


def test_an_opt_in_injected_after_parsing_is_revalidated_at_execution() -> None:
    """A complete plan whose ONLY fault is the version, so the execution-time
    check is the version check and nothing else."""
    decl = calibration.parse_declaration(window_data())
    cast(dict[str, Any], decl.data)[rc.KEY] = {**contracts(), 'version': 2}
    with pytest.raises(calibration.DeclarationRefused) as info:
        calibration.require_approved(decl, ROOT)
    assert str(info.value) == ('calibration declaration: run_window_contracts: '
                               'unsupported contracts version')


def test_the_key_joins_the_approval_digest_with_no_digest_change() -> None:
    approved = data()
    changed = copy.deepcopy(approved)
    changed[rc.KEY]['limits']['max_entries'] = 2048
    assert calibration.declaration_digest(changed) != approved['approval']['declaration_digest']
    with pytest.raises(calibration.DeclarationRefused, match='declaration_digest'):
        calibration._require_whole_declaration_approval(changed, changed['approval'])


def test_a_limit_changed_after_approval_is_refused_through_require_approved() -> None:
    """The same binding through the public execution path: a valid limit,
    changed on a parsed and approved declaration, is refused by the digest."""
    decl = calibration.parse_declaration(data())
    cast(dict[str, Any], decl.data)[rc.KEY] = {**contracts(),
                                               'limits': {'max_entries': 2048, 'max_depth': 16}}
    with pytest.raises(calibration.DeclarationRefused, match='declaration_digest'):
        calibration.require_approved(decl, ROOT)


def test_census_budget_is_checked_at_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = rc.validate_plan(data())
    monkeypatch.setattr(rc, 'fd_budget_ok', lambda entries, depth: False)
    with pytest.raises(rc.ContractsRefused, match='descriptor budget'):
        rc.require_census_budget(plan)
    monkeypatch.setattr(rc, 'fd_budget_ok', lambda entries, depth: True)
    rc.require_census_budget(plan)


def test_parsing_does_not_consult_the_descriptor_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parsing is shape-only: a process that could not hold the census still
    parses the declaration; admission is where the budget refuses."""
    def forbidden(entries: int, depth: int) -> bool:
        pytest.fail('parsing consulted the descriptor budget')

    monkeypatch.setattr(rc, 'fd_budget_ok', forbidden)
    calibration.parse_declaration(data())
