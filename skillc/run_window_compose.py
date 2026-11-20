"""Removed-root absence, part 3a: per-surface verdicts and the total release
predicate (#797 A-3a, SECRET-PATH).

This implements section 2.3 of the owner-approved run-window contracts
design, composing A-1's facts (census, fact 1, fact 4) with A-2's facts
(teardown boundary, facts 2, 2b and 3). It is pure: it reads no file, holds no
descriptor and touches no host. A-3b supplies the declaration, gathers the
evidence in the close sequence, and lifts the absence blocker.

Binding rules carried from A-2:
- A `launch-only` fact 2b is never sufficient for ABSENT. Only a
  `lifetime`-scoped 2b, which needs PR-1's sampler, can be. Until then every
  removed surface composes to UNKNOWN.
- A non-empty holder domain (teardown not negative) vetoes ABSENT, whatever
  fact 2 says.
- A holder (fact 2 not negative) vetoes ABSENT.

Verdicts are fixed strings. Any input of the wrong type is UNKNOWN; nothing
is coerced. The window predicate is a total allowlist: CLEAN only when every
declared surface has exactly one verdict in its allowed state, and Contract
B's capture is sealed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .remnant_scan import ScanResult
from .run_window_absence import FAIL, NEG, SURV, Observation, Reresolved
from .run_window_teardown import ScopedObservation

ABSENT = 'ABSENT'
ABSENT_UNLINKED = 'ABSENT_UNLINKED'
PRESENT = 'PRESENT'
UNKNOWN = 'UNKNOWN'
NOT_CLEAN = 'NOT_CLEAN'
CLEAN = 'CLEAN'
LIFETIME = 'lifetime'
REMOVED = 'removed'
RETAINED = 'retained'

REMOVED_VERDICTS = frozenset({ABSENT, ABSENT_UNLINKED, PRESENT, UNKNOWN, NOT_CLEAN})
RETAINED_VERDICTS = frozenset({CLEAN, UNKNOWN, NOT_CLEAN})

#: Fixed reason tokens; nothing else ever appears in a public window result.
REASONS = ('evidence-population-mismatch', 'unknown-verdict', 'removed-surface-not-absent',
           'retained-surface-not-clean', 'reference-retention-contract-unavailable',
           'preconditions-not-held', 'remnant-matched')


def _obs(value: object) -> Observation | None:
    return value if type(value) is Observation else None


def _snapshot(mapping: object) -> list[tuple[Any, Any]] | None:
    """The entries of a built-in dict, taken FIRST as a list, so every later
    check reads the same contents even if the caller mutates its own dict, and
    no caller-defined key is hashed or compared before its type is checked."""
    return list(mapping.items()) if type(mapping) is dict else None


def _plain(entries: list[tuple[Any, Any]] | None) -> dict[str, str] | None:
    """A lookup dict built only once every key and value is an exact str: the
    only accepted representation, so no subclass can override lookup, hashing
    or equality."""
    if entries is None or any(type(k) is not str or type(v) is not str for k, v in entries):
        return None
    return dict(entries)


def removed_surface_verdict(*, census_complete: object, unlinked: object, reresolved: object,
                            teardown: object, no_holder: object, superblock_gone: object,
                            tmpfs: object, isolation: object) -> str:
    """One removed-class surface.

    - PRESENT if fact 4 asked for a rescan (a recreated, non-empty or
      replaced path). The caller scans it (`present_surface_verdict`); it is
      never released.
    - UNKNOWN on any veto, any failed or unexpected input, an incomplete
      census, or a 2b that is not `lifetime`-scoped.
    - ABSENT_UNLINKED when every fact holds on a non-tmpfs root (Q1: it never
      releases).
    - ABSENT only when every fact is CONFIRMED_NEGATIVE, the root is tmpfs,
      and 2b is CONFIRMED_NEGATIVE for its lifetime.
    """
    if type(reresolved) is Reresolved:
        if type(reresolved.rescan) is not bool:
            return UNKNOWN  # Malformed evidence is never interpreted.
        rescan = reresolved.rescan
        fact4 = _obs(reresolved.observation)
    else:
        fact4 = _obs(reresolved)
        rescan = fact4 is SURV
    if rescan:
        return PRESENT
    facts = (_obs(unlinked), fact4, _obs(teardown), _obs(no_holder), _obs(superblock_gone))
    if any(f is None for f in facts) or type(census_complete) is not bool or type(tmpfs) is not bool:
        return UNKNOWN
    if any(f is not NEG for f in facts) or not census_complete:
        return UNKNOWN  # Includes both vetoes: teardown SURV/FAIL and no_holder SURV/FAIL.
    if (type(isolation) is not ScopedObservation or isolation.observation is not NEG
            or type(isolation.scope) is not str or isolation.scope != LIFETIME):
        return UNKNOWN  # A launch-only 2b never suffices (binding A-2 rule).
    return ABSENT if tmpfs else ABSENT_UNLINKED


def present_surface_verdict(scan: object) -> str:
    """A PRESENT removed root after its population was scanned: a match is
    NOT_CLEAN; anything else stays UNKNOWN (it was not removed)."""
    if type(scan) is ScanResult and type(scan.status) is str and scan.status == 'NOT_CLEAN':
        return NOT_CLEAN
    return UNKNOWN


def retained_surface_verdict(scan: object) -> str:
    """A retained surface: its own slice 4 result. CLEAN only for a CLEAN
    result; a match is NOT_CLEAN; anything else is UNKNOWN."""
    if type(scan) is not ScanResult or type(scan.status) is not str:
        return UNKNOWN
    if scan.status == 'NOT_CLEAN':
        return NOT_CLEAN
    return CLEAN if scan.status == 'CLEAN' else UNKNOWN


@dataclass(frozen=True)
class WindowVerdict:
    """The composed window result. `public()` is an exact allowlist."""

    status: str
    reasons: tuple[str, ...]
    removed: int
    retained: int

    def public(self) -> dict[str, Any]:
        return {'version': 1, 'status': self.status, 'reasons': list(self.reasons),
                'surfaces': {'removed': self.removed, 'retained': self.retained}}


def window_verdict(verdicts: object, *, declared: object, capture_sealed: object,
                   preconditions_held: object) -> WindowVerdict:
    """The total allowlist predicate (design 2.3).

    NOT_CLEAN if any verdict anywhere is NOT_CLEAN, declared or not ("any
    match anywhere"). Otherwise CLEAN only if: both mappings are built-in
    dicts of exact strings; the verdicts cover exactly the declared surfaces;
    every retained surface is CLEAN; every removed surface is ABSENT; Contract
    B's capture is sealed; and the 1.2 preconditions held. UNKNOWN otherwise,
    with fixed reason tokens.
    """
    raw = _snapshot(verdicts)
    decl_raw = _snapshot(declared)
    if raw is not None and any(type(v) is str and v == NOT_CLEAN for _, v in raw):
        return WindowVerdict(NOT_CLEAN, ('remnant-matched',), 0, 0)
    found = _plain(raw)
    decl = _plain(decl_raw)
    if found is None or decl is None or not decl:
        return WindowVerdict(UNKNOWN, ('evidence-population-mismatch',), 0, 0)
    reasons: list[str] = []
    if set(found) != set(decl) or any(d not in (REMOVED, RETAINED) for d in decl.values()):
        reasons.append('evidence-population-mismatch')
    removed = sum(1 for d in decl.values() if d == REMOVED)
    retained = sum(1 for d in decl.values() if d == RETAINED)
    for surface, disposition in decl.items():
        verdict = found.get(surface)
        allowed = REMOVED_VERDICTS if disposition == REMOVED else RETAINED_VERDICTS
        if verdict is None or verdict not in allowed:
            if 'unknown-verdict' not in reasons:
                reasons.append('unknown-verdict')
            continue
        if disposition == REMOVED and verdict != ABSENT and 'removed-surface-not-absent' not in reasons:
            reasons.append('removed-surface-not-absent')
        if disposition == RETAINED and verdict != CLEAN and 'retained-surface-not-clean' not in reasons:
            reasons.append('retained-surface-not-clean')
    if capture_sealed is not True:
        reasons.append('reference-retention-contract-unavailable')
    if preconditions_held is not True:
        reasons.append('preconditions-not-held')
    return WindowVerdict(CLEAN if not reasons else UNKNOWN, tuple(reasons), removed, retained)


__all__ = ['ABSENT', 'ABSENT_UNLINKED', 'PRESENT', 'UNKNOWN', 'NOT_CLEAN', 'CLEAN', 'LIFETIME', 'REMOVED',
           'RETAINED', 'REASONS', 'removed_surface_verdict', 'present_surface_verdict',
           'retained_surface_verdict', 'WindowVerdict', 'window_verdict', 'FAIL']
