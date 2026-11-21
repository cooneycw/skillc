"""Removed-root absence, part 3b1: the `run_window_contracts` declaration
(#797 A-3b1, SECRET-PATH).

The closed, opt-in declaration a calibration declaration carries when its
window uses the run-window contracts. It is section 2.2 "Dispositions" and the
admission limits of the owner-approved run-window contracts design:

- `version`: 1;
- `limits`: `max_entries` and `max_depth` for every removed-root census, each a
  positive int at or below slice 4's scan ceilings.

Parsing is shape-only, as for every other declaration key: it reads nothing.
Whether the controller can hold a census of that size is a property of the
running process, so it is checked at admission (`require_census_budget`).

The disposition of each surface class is FIXED here, never declared, and no
path appears in the declaration: the root mapping is supplied privately at
close by the trusted adapter, as slice 4 does it. The key requires
`credential_window` (and through it `remnant_scan` and the VM admission keys).
It joins the whole-declaration approval digest like every other key, so a
change after approval is refused by the existing digest check.

This module changes no behaviour for a declaration that does not carry the
key. It lifts no blocker: A-3b2 wires the close sequence.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import remnant_scan, vm_credential_window
from .run_window_absence import fd_budget_ok

KEY = 'run_window_contracts'
REMOVED = 'removed'
RETAINED = 'retained'

#: Surface class -> disposition, fixed by class (design 2.2). Removed-class
#: surfaces must be proven absent at close; retained ones must scan CLEAN.
DISPOSITION: Mapping[str, str] = {
    'home': REMOVED, 'vault': REMOVED, 'staging': REMOVED, 'login-home': REMOVED,
    'scratch-tmp': REMOVED, 'scratch-vartmp': REMOVED, 'scratch-shm': REMOVED,
    'stdout': RETAINED, 'transcript': RETAINED, 'cache-log': RETAINED, 'export-payload': RETAINED,
}

#: The census ceilings: slice 4's own scan limits, never wider.
CEILINGS = {'max_entries': remnant_scan.LIMITS['entries'],
            'max_depth': remnant_scan.LIMITS['depth']}


class ContractsRefused(ValueError):
    """Fixed diagnostics only; supplied values never enter exception text."""


def _require(ok: object, reason: str) -> None:
    if not ok:
        raise ContractsRefused(KEY + ': ' + reason)


def validate_plan(data: Mapping[str, object]) -> dict[str, Any]:
    """The closed v1 object, or a fixed refusal. Returns a normalized copy."""
    raw = data.get(KEY)
    # Key types are checked BEFORE any set is built: a str subclass could
    # compare equal to a declared key, and a custom key's hash or equality
    # could raise with supplied text.
    _require(type(raw) is dict and all(type(k) is str for k in raw)
             and set(raw) == {'version', 'limits'}, 'invalid declared contracts')
    assert isinstance(raw, dict)
    _require(type(raw['version']) is int and raw['version'] == 1, 'unsupported contracts version')
    limits = raw['limits']
    _require(type(limits) is dict and all(type(k) is str for k in limits)
             and set(limits) == set(CEILINGS), 'invalid census limits')
    assert isinstance(limits, dict)
    for name, ceiling in CEILINGS.items():
        value = limits[name]
        _require(type(value) is int and 0 < value <= ceiling,
                 'census limit outside the scan ceiling')
    try:
        vm_credential_window.validate_plan(data)
    except vm_credential_window.CustodyRefused:
        raise ContractsRefused(
            KEY + ': credential_window and its remnant coverage are required') from None
    return {'version': 1, 'limits': dict(limits), 'disposition': dict(DISPOSITION)}


def require_census_budget(plan: Mapping[str, Any]) -> None:
    """Admission check (A-3b2 calls it): the running controller can hold a
    census of the declared size beside its open descriptors and a reserve."""
    limits = plan.get('limits') if isinstance(plan, Mapping) else None
    _require(isinstance(limits, Mapping) and type(limits.get('max_entries')) is int
             and type(limits.get('max_depth')) is int, 'invalid census limits')
    assert isinstance(limits, Mapping)
    _require(fd_budget_ok(limits['max_entries'], limits['max_depth']),
             'census exceeds the descriptor budget')
