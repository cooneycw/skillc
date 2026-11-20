"""Contract A part 3a (#797 A-3a): per-surface verdicts and the total release
predicate. These qualify NEW instruments (the module is new); none claims a
red run on the parent. Each rule that a weaker predicate would break is paired
with that predicate (`blind_*`), which must give a different answer.
"""
from __future__ import annotations

from typing import Any

import pytest

from skillc import run_window_compose as rc
from skillc.remnant_scan import ScanResult
from skillc.run_window_absence import FAIL, NEG, SURV, Reresolved
from skillc.run_window_teardown import LAUNCH_ONLY, ScopedObservation

SUFFICIENT: dict[str, Any] = {
    'census_complete': True, 'unlinked': NEG, 'reresolved': Reresolved(NEG, False), 'teardown': NEG,
    'no_holder': NEG, 'superblock_gone': NEG, 'tmpfs': True,
    'isolation': ScopedObservation(NEG, rc.LIFETIME),
}
FACTS = ('unlinked', 'teardown', 'no_holder', 'superblock_gone')


def verdict(**override: Any) -> str:
    return rc.removed_surface_verdict(**{**SUFFICIENT, **override})


def scan(status: str) -> ScanResult:
    return ScanResult(status, b'{}')


# ----------------------------------------------------------- removed surfaces


def test_sufficient_evidence_is_absent() -> None:
    assert verdict() == rc.ABSENT


@pytest.mark.parametrize('fact', FACTS)
@pytest.mark.parametrize('value', [FAIL, SURV])
def test_any_fact_that_is_not_negative_is_unknown(fact: str, value: Any) -> None:
    assert verdict(**{fact: value}) == rc.UNKNOWN


def blind_ignores_domain_veto(**inputs: Any) -> str:
    """A predicate that trusts fact 2 over the teardown boundary."""
    return rc.ABSENT if inputs['no_holder'] is NEG and inputs['unlinked'] is NEG else rc.UNKNOWN


def test_nonempty_domain_vetoes_even_when_fact2_is_clean() -> None:
    inputs = {**SUFFICIENT, 'teardown': SURV}
    assert blind_ignores_domain_veto(**inputs) == rc.ABSENT
    assert rc.removed_surface_verdict(**inputs) == rc.UNKNOWN


def blind_accepts_launch_only(**inputs: Any) -> str:
    return rc.ABSENT if inputs['isolation'].observation is NEG else rc.UNKNOWN


@pytest.mark.parametrize('isolation', [ScopedObservation(NEG, LAUNCH_ONLY), ScopedObservation(NEG, 'other'),
                                       ScopedObservation(FAIL, rc.LIFETIME), ScopedObservation(SURV, rc.LIFETIME),
                                       NEG, None])
def test_isolation_must_be_negative_for_the_lifetime(isolation: Any) -> None:
    if isolation == ScopedObservation(NEG, LAUNCH_ONLY):
        assert blind_accepts_launch_only(**{**SUFFICIENT, 'isolation': isolation}) == rc.ABSENT
    assert verdict(isolation=isolation) == rc.UNKNOWN


def test_incomplete_census_is_unknown() -> None:
    assert verdict(census_complete=False) == rc.UNKNOWN


def blind_releases_unlinked(**inputs: Any) -> str:
    return rc.ABSENT if all(inputs[f] is NEG for f in FACTS) else rc.UNKNOWN


def test_disk_backed_root_is_absent_unlinked_and_never_releases() -> None:
    inputs = {**SUFFICIENT, 'tmpfs': False}
    assert blind_releases_unlinked(**inputs) == rc.ABSENT
    assert rc.removed_surface_verdict(**inputs) == rc.ABSENT_UNLINKED
    result = rc.window_verdict({'home': rc.ABSENT_UNLINKED}, declared={'home': rc.REMOVED},
                               capture_sealed=True, preconditions_held=True)
    assert result.status == rc.UNKNOWN


@pytest.mark.parametrize('reresolved', [Reresolved(SURV, True), Reresolved(FAIL, True), SURV])
def test_rescan_request_is_present(reresolved: Any) -> None:
    assert verdict(reresolved=reresolved) == rc.PRESENT
    assert verdict(reresolved=reresolved, teardown=SURV) == rc.PRESENT  # Always scanned.


@pytest.mark.parametrize('reresolved', [Reresolved(FAIL, False), FAIL, None, 'NEG'])
def test_failed_or_malformed_fact4_is_unknown(reresolved: Any) -> None:
    assert verdict(reresolved=reresolved) == rc.UNKNOWN


@pytest.mark.parametrize('field,value', [('census_complete', 1), ('tmpfs', 'yes'), ('unlinked', 'CONFIRMED_NEGATIVE'),
                                         ('teardown', None), ('no_holder', 0)])
def test_inputs_of_the_wrong_type_are_never_coerced(field: str, value: Any) -> None:
    assert verdict(**{field: value}) == rc.UNKNOWN


class EqualToEverything:
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = None  # type: ignore[assignment]


class AbsentLike(str):
    """A str subclass that hashes and compares like 'ABSENT'."""


class LyingDict(dict[str, str]):
    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return rc.ABSENT


@pytest.mark.parametrize('case', ['rescan-int', 'scope-object', 'reresolved-subclass'])
def test_malformed_evidence_never_yields_absent(case: str) -> None:
    if case == 'rescan-int':
        assert verdict(reresolved=Reresolved(NEG, 1)) == rc.UNKNOWN  # type: ignore[arg-type]
    elif case == 'scope-object':
        assert verdict(isolation=ScopedObservation(NEG, EqualToEverything())) == rc.UNKNOWN  # type: ignore[arg-type]
    else:
        class Sub(Reresolved):
            pass

        assert verdict(reresolved=Sub(NEG, False)) == rc.UNKNOWN


def test_a_status_that_only_compares_equal_is_not_clean_evidence() -> None:
    fake = ScanResult(EqualToEverything(), b'{}')  # type: ignore[arg-type]
    assert rc.retained_surface_verdict(fake) == rc.UNKNOWN
    assert rc.present_surface_verdict(fake) == rc.UNKNOWN


def test_present_root_after_its_scan() -> None:
    assert rc.present_surface_verdict(scan('NOT_CLEAN')) == rc.NOT_CLEAN
    for status in ('CLEAN', 'UNKNOWN'):
        assert rc.present_surface_verdict(scan(status)) == rc.UNKNOWN
    assert rc.present_surface_verdict({'status': 'NOT_CLEAN'}) == rc.UNKNOWN


def test_retained_surface_uses_its_own_scan_only() -> None:
    assert rc.retained_surface_verdict(scan('CLEAN')) == rc.CLEAN
    assert rc.retained_surface_verdict(scan('NOT_CLEAN')) == rc.NOT_CLEAN
    assert rc.retained_surface_verdict(scan('UNKNOWN')) == rc.UNKNOWN
    assert rc.retained_surface_verdict({'status': 'CLEAN'}) == rc.UNKNOWN  # A public dict is not evidence.


# --------------------------------------------------------- window predicate

DECLARED = {'wave-a/worker/home': rc.REMOVED, 'wave-a/worker/vault': rc.REMOVED, 'wave-a/worker/transcript': rc.RETAINED}
GOOD = {'wave-a/worker/home': rc.ABSENT, 'wave-a/worker/vault': rc.ABSENT, 'wave-a/worker/transcript': rc.CLEAN}


def window(verdicts: Any = None, **kw: Any) -> rc.WindowVerdict:
    kw.setdefault('declared', DECLARED)
    kw.setdefault('capture_sealed', True)
    kw.setdefault('preconditions_held', True)
    return rc.window_verdict(GOOD if verdicts is None else verdicts, **kw)


def test_window_is_clean_only_with_everything_in_place() -> None:
    result = window()
    assert result.status == rc.CLEAN and result.reasons == ()


def test_without_contract_b_the_window_is_unknown() -> None:
    result = window(capture_sealed=False)
    assert result.status == rc.UNKNOWN
    assert result.reasons == ('reference-retention-contract-unavailable',)


@pytest.mark.parametrize('case', ['missing', 'extra', 'not-a-mapping', 'empty-declared', 'bad-disposition'])
def test_evidence_population_must_match_the_declaration(case: str) -> None:
    verdicts: Any = dict(GOOD)
    declared: Any = dict(DECLARED)
    if case == 'missing':
        del verdicts['wave-a/worker/vault']
    elif case == 'extra':
        verdicts['wave-a/worker/stray'] = rc.ABSENT
    elif case == 'not-a-mapping':
        verdicts = list(GOOD.items())
    elif case == 'empty-declared':
        declared = {}
    else:
        declared['wave-a/worker/home'] = 'sometimes'
    assert window(verdicts, declared=declared).status == rc.UNKNOWN


@pytest.mark.parametrize('surface,value', [('wave-a/worker/home', rc.UNKNOWN), ('wave-a/worker/home', rc.PRESENT),
                                           ('wave-a/worker/home', rc.CLEAN), ('wave-a/worker/transcript', rc.ABSENT),
                                           ('wave-a/worker/transcript', rc.UNKNOWN), ('wave-a/worker/vault', 'absent')])
def test_one_surface_out_of_place_makes_the_window_unknown(surface: str, value: str) -> None:
    assert window({**GOOD, surface: value}).status == rc.UNKNOWN


def blind_class_aggregate(verdicts: dict[str, str]) -> str:
    """Reads one verdict per class, so a bad role hides behind a good one."""
    # Ascending order: the later role overwrites the earlier, so one role's
    # CLEAN hides another's UNKNOWN for the same class.
    by_class = {s.rsplit('/', 1)[-1]: v for s, v in sorted(verdicts.items())}
    return rc.CLEAN if all(v in (rc.ABSENT, rc.CLEAN) for v in by_class.values()) else rc.UNKNOWN


def test_one_unreadable_role_is_not_hidden_by_another_roles_clean() -> None:
    declared = {**DECLARED, 'wave-a/integrator/transcript': rc.RETAINED}
    verdicts = {**GOOD, 'wave-a/integrator/transcript': rc.UNKNOWN}
    assert blind_class_aggregate(verdicts) == rc.CLEAN
    assert window(verdicts, declared=declared).status == rc.UNKNOWN


@pytest.mark.parametrize('case', ['declared', 'declared-with-missing', 'stray', 'empty-declaration',
                                  'unsealed'])
def test_any_match_anywhere_is_not_clean(case: str) -> None:
    verdicts: dict[str, str] = dict(GOOD)
    declared: dict[str, str] = dict(DECLARED)
    sealed = True
    if case == 'declared':
        verdicts['wave-a/worker/vault'] = rc.NOT_CLEAN
    elif case == 'declared-with-missing':
        verdicts['wave-a/worker/vault'] = rc.NOT_CLEAN
        del verdicts['wave-a/worker/home']
    elif case == 'stray':
        verdicts['stray'] = rc.NOT_CLEAN
    elif case == 'empty-declaration':
        verdicts['wave-a/worker/vault'] = rc.NOT_CLEAN
        declared = {}
    else:
        verdicts['wave-a/worker/vault'] = rc.NOT_CLEAN
        sealed = False
    result = rc.window_verdict(verdicts, declared=declared, capture_sealed=sealed, preconditions_held=True)
    assert result.status == rc.NOT_CLEAN and result.reasons == ('remnant-matched',)


@pytest.mark.parametrize('case', ['str-subclass-verdict', 'lying-dict', 'non-str-keys', 'dict-subclass'])
def test_only_plain_dicts_of_exact_strings_are_evidence(case: str) -> None:
    verdicts: Any = dict(GOOD)
    declared: Any = dict(DECLARED)
    if case == 'str-subclass-verdict':
        verdicts['wave-a/worker/home'] = AbsentLike(rc.ABSENT)
    elif case == 'lying-dict':
        verdicts = LyingDict({**GOOD, 'wave-a/worker/home': rc.UNKNOWN})
    elif case == 'non-str-keys':
        verdicts = {1: rc.ABSENT}
        declared = {True: rc.REMOVED}
    else:
        declared = LyingDict(DECLARED)
    assert rc.window_verdict(verdicts, declared=declared, capture_sealed=True,
                             preconditions_held=True).status == rc.UNKNOWN


def test_preconditions_must_hold() -> None:
    assert window(preconditions_held=False).status == rc.UNKNOWN
    assert window(preconditions_held=1).status == rc.UNKNOWN  # Not coerced.


def test_public_result_is_an_exact_allowlist() -> None:
    result = window({**GOOD, 'wave-a/worker/home': rc.UNKNOWN}, capture_sealed=False)
    assert result.public() == {'version': 1, 'status': rc.UNKNOWN,
                               'reasons': ['removed-surface-not-absent',
                                           'reference-retention-contract-unavailable'],
                               'surfaces': {'removed': 2, 'retained': 1}}
    assert all(reason in rc.REASONS for reason in result.public()['reasons'])
    assert 'wave-a/worker' not in repr(result.public())  # No surface name leaves the module.
