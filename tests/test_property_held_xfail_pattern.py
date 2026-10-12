"""The committed negative control for issue #336's dedicated-exception
fix (`_PropertyHeld`/`_require`, applied to `tests/test_decide_reply_
channel_live.py` and `tests/test_gate_witness_live.py`, matching
`tests/test_gate_overlay_live.py`'s own #332 precedent) AND issue #341's
follow-up (one `_PropertyHeld` SUBTYPE per independently-targeted
property, applied to all four live files: channel, witness, gate
overlay, cold install) - counter-model review found that a single
shared `_PropertyHeld` closed the infra-vs-property gap #336 fixed, but
left a property-vs-property one open: within one break-mode run, a
NEIGHBORING property's own failure could still satisfy the marker.

The first three controls exercise pytest's exception-matching mechanics.
The live-module controls below then import the real markers and exercise
the actual observation predicates without a daemon. They distinguish the
targeted failure, every neighboring property, infrastructure failure and
strict XPASS, pinning test identities as well as counts. Widening the
actual marker or inverting the closure predicate reproduces the false
certification. Generic sibling classes alone cannot detect a wrongly
grouped marker in a live file.

Three inner tests, one generated file, one inner pytest run:

    (a) raises=_PropertyHeld, function raises _PropertyHeld -> XFAILED.
        The ordinary, correct case: a break mode's own property check
        fails as expected and is swallowed by the strict-xfail marker.
    (b) raises=_PropertyHeld, function raises plain AssertionError ->
        FAILED, never XFAILED. An infra/setup `assert` during a break
        run (a docker create failing, say) must be a hard failure - the
        narrower `raises=` type is what makes this true.
    (c) raises=AssertionError (the OLD, too-wide marker this issue
        replaces), function raises plain AssertionError -> XFAILED, the
        WRONG pass. This is the acceptance criterion's own named
        mutation, demonstrated directly rather than only asserted in
        prose: the pre-fix marker could not tell an infra failure from
        the real break, and this is exactly how that looked.

Identity is pinned, not merely counts (`result.stdout.fnmatch_lines`) -
two tests each counted once in the right buckets could otherwise
coincidentally match a correct-looking tally for the wrong reason.

Stdlib plus pytest's own bundled `pytester` fixture only - no Docker, no
real daemon, matching every other no-daemon, parse/mechanics-only check
in this family (`check_pins.py`, `check_interpreters.py`, `check_helpers.py`).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


_INNER_TEST_SOURCE = textwrap.dedent("""
    import pytest

    class _PropertyHeld(Exception):
        pass

    @pytest.mark.xfail(strict=True, raises=_PropertyHeld)
    def test_a_property_held_is_xfailed():
        raise _PropertyHeld("the property did not hold")

    @pytest.mark.xfail(strict=True, raises=_PropertyHeld)
    def test_b_an_infra_assertion_error_is_a_hard_failure():
        assert False, "an unrelated infra/setup failure"

    @pytest.mark.xfail(strict=True, raises=AssertionError)
    def test_c_the_old_too_wide_marker_wrongly_xfails_an_infra_failure():
        assert False, "an unrelated infra/setup failure, wrongly credited"
""")


def test_the_dedicated_exception_narrows_xfail_to_only_the_real_property(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_INNER_TEST_SOURCE)
    result = pytester.runpytest("-v")

    # Overall tally: two of the three inner tests resolve as XFAILED
    # (a: the real property firing; c: the old marker's own wrong pass),
    # one as a hard FAILED (b: the dedicated exception doing its job).
    result.assert_outcomes(xfailed=2, failed=1)

    # Pin WHICH test landed in which bucket - the count alone cannot
    # distinguish "(a) and (c) xfailed, (b) failed" (the real, intended
    # shape) from some other combination that happens to sum the same.
    result.stdout.fnmatch_lines(["*test_a_property_held_is_xfailed XFAIL*"])
    result.stdout.fnmatch_lines(["*test_b_an_infra_assertion_error_is_a_hard_failure FAILED*"])
    result.stdout.fnmatch_lines(["*test_c_the_old_too_wide_marker_wrongly_xfails_an_infra_failure XFAIL*"])


#: Issue #341's own negative control: ONE shared base, TWO independent
#: subtypes (siblings, never one a subclass of the other) - the shape
#: every converted live file now uses (one subtype per targeted
#: property). `test_a` raises its OWN marker's subtype (the ordinary
#: case); `test_b` raises the OTHER, sibling subtype under a marker
#: that names the FIRST - a neighboring property's own failure, which
#: must be a hard FAILED, never swallowed as if property A's own break
#: had fired.
_CROSS_PROPERTY_INNER_TEST_SOURCE = textwrap.dedent("""
    import pytest

    class _PropertyHeld(Exception):
        pass

    class _PropertyAHeld(_PropertyHeld):
        pass

    class _PropertyBHeld(_PropertyHeld):
        pass

    @pytest.mark.xfail(strict=True, raises=_PropertyAHeld)
    def test_a_the_targeted_propertys_own_subtype_is_xfailed():
        raise _PropertyAHeld("property A did not hold")

    @pytest.mark.xfail(strict=True, raises=_PropertyAHeld)
    def test_b_a_neighboring_propertys_subtype_is_a_hard_failure():
        raise _PropertyBHeld("property B did not hold - a DIFFERENT, neighboring property")
""")


def test_a_neighboring_propertys_subtype_does_not_satisfy_this_propertys_marker(pytester: pytest.Pytester) -> None:
    """Issue #341's own committed negative control: per-property
    subtypes only close the gap counter-model review found (on #336's
    single shared `_PropertyHeld`) if a SIBLING subtype - a different,
    neighboring property, sharing only the common base - genuinely
    fails to satisfy a marker that names a DIFFERENT, specific subtype.
    Proven here directly against pytest's own isinstance-based `raises=`
    matching (a sibling subclass is never an instance of its sibling),
    not merely asserted in prose - this is the exact property every one
    of #341's four converted live files now depends on."""
    pytester.makepyfile(_CROSS_PROPERTY_INNER_TEST_SOURCE)
    result = pytester.runpytest("-v")
    result.assert_outcomes(xfailed=1, failed=1)
    result.stdout.fnmatch_lines(["*test_a_the_targeted_propertys_own_subtype_is_xfailed XFAIL*"])
    result.stdout.fnmatch_lines(["*test_b_a_neighboring_propertys_subtype_is_a_hard_failure FAILED*"])


def test_widening_the_marker_back_to_the_shared_base_type_wrongly_passes(pytester: pytest.Pytester) -> None:
    """Mutation check (issue #341's own acceptance criterion): widening
    `test_b`'s marker from the SPECIFIC sibling subtype back to the
    shared `_PropertyHeld` base makes it wrongly XFAIL - proving the
    control above is real, not inert: narrowing to the specific subtype
    is what makes test_b a hard failure, and reverting that narrowing
    (exactly the #336-era shape, before #341) brings the bug back."""
    widened_source = _CROSS_PROPERTY_INNER_TEST_SOURCE.replace(
        "@pytest.mark.xfail(strict=True, raises=_PropertyAHeld)\n"
        "def test_b_a_neighboring_propertys_subtype_is_a_hard_failure():",
        "@pytest.mark.xfail(strict=True, raises=_PropertyHeld)\n"
        "def test_b_a_neighboring_propertys_subtype_is_a_hard_failure():",
    )
    assert widened_source != _CROSS_PROPERTY_INNER_TEST_SOURCE, "fixture bug: the substitution found nothing to replace"
    pytester.makepyfile(widened_source)
    result = pytester.runpytest("-v")
    # Both inner tests now XFAIL - the widened marker wrongly accepts
    # property B's own failure as if it were property A's.
    result.assert_outcomes(xfailed=2, failed=0)


_ROOT = Path(__file__).resolve().parents[1]
_COLD_MODES = ("skill-mount", "home-mount", "mcp-mount", "secret-mount", "cold-cache")


def _live_control_source(
    filename: str, env_name: str, modes: tuple[str, ...], test_name: str, *, widen: bool,
) -> str:
    """Import actual live modules without probing Docker, then reuse their marker.

    The predicates and raised types remain untouched in the mutation run.
    Only the actual marker's raises argument is widened to the shared base.
    Module-level real_docker/skip markers are not copied to these no-daemon
    tests; the function's own strict-xfail marker is copied in full.
    """
    return textwrap.dedent(f"""
        import os
        import runpy
        import sys
        from unittest.mock import patch
        import pytest

        sys.path.insert(0, {str(_ROOT)!r})
        MODES = {modes!r}
        MODULES = {{}}
        for mode in MODES:
            with patch.dict(os.environ, {{{env_name!r}: mode}}), patch('shutil.which', return_value=None):
                ns = runpy.run_path({str(_ROOT / 'tests' / filename)!r})
            markers = [m for m in ns[{test_name!r}].pytestmark if m.name == 'xfail']
            assert len(markers) == 1
            marker = markers[0]
            assert marker.kwargs['condition'] is True
            assert marker.kwargs['strict'] is True
            if {widen!r}:
                marker.kwargs['raises'] = ns.get('_PropertyHeld', Exception)
            MODULES[mode] = (ns, marker)

        def add_case(name, mode, action):
            ns, marker = MODULES[mode]
            def case():
                action(ns)
            case.__name__ = name
            globals()[name] = pytest.mark.xfail(*marker.args, **marker.kwargs)(case)

        def infra(ns):
            raise AssertionError('unrelated setup failure')
    """)


def _cold_control_source(*, widen: bool) -> str:
    return _live_control_source(
        "test_profile_install_cold_container_live.py", "SKILLC_COLDINSTALL_LIVE_BREAK", _COLD_MODES,
        "test_profile_runs_cold_with_no_operator_mounts", widen=widen,
    ) + textwrap.dedent("""
        # Fixed observations independent of the module's break-mode map.
        DESTINATIONS = {
            'skill-mount': '/root/.claude/skills',
            'home-mount': '/root',
            'mcp-mount': '/root/.mcp.json',
            'secret-mount': '/root/.config/skillc/secret',
        }

        def observe(ns, failed):
            mounts = [{'Destination': DESTINATIONS[failed]}] if failed in DESTINATIONS else []
            ns['_check_mounts'](mounts)
            ns['_check_offline_sync'](1 if failed == 'cold-cache' else 0, 'cache unavailable')

        for mode in MODES:
            suffix = mode.replace('-', '_')
            add_case('test_target_' + suffix, mode, lambda ns, m=mode: observe(ns, m))
            add_case('test_intact_' + suffix, mode, lambda ns: observe(ns, None))
            add_case('test_infra_' + suffix, mode, infra)
            for neighbor in MODES:
                if neighbor != mode:
                    name = 'test_neighbor_' + suffix + '_' + neighbor.replace('-', '_')
                    add_case(name, mode, lambda ns, other=neighbor: observe(ns, other))

            add_case('test_unknown_mount_' + suffix, mode,
                     lambda ns: ns['_check_mounts']([{'Destination': '/unexpected'}]))
            add_case('test_malformed_mount_' + suffix, mode,
                     lambda ns: ns['_check_mounts']([{}]))
            add_case('test_multiple_mounts_' + suffix, mode,
                     lambda ns: ns['_check_mounts']([
                         {'Destination': '/root/.claude/skills'},
                         {'Destination': '/root/.config/skillc/secret'},
                     ]))
    """)


@pytest.mark.parametrize("widen", [False, True], ids=["specific", "mutated-base"])
def test_cold_install_real_markers_discriminate_observed_properties(pytester: pytest.Pytester, widen: bool) -> None:
    pytester.makepyfile(_cold_control_source(widen=widen))
    result = pytester.runpytest("-v", "--tb=short")
    # Five targeted failures, twenty ordered neighbor pairs, five intact
    # strict XPASSes, five infra failures and fifteen mount-integrity failures.
    result.assert_outcomes(xfailed=25 if widen else 5, failed=25 if widen else 45)
    for mode in _COLD_MODES:
        suffix = mode.replace("-", "_")
        result.stdout.fnmatch_lines([f"*test_target_{suffix} XFAIL*"])
        result.stdout.fnmatch_lines([f"*test_intact_{suffix} FAILED*"])
        result.stdout.fnmatch_lines([f"*test_infra_{suffix} FAILED*"])
        for kind in ("unknown_mount", "malformed_mount", "multiple_mounts"):
            result.stdout.fnmatch_lines([f"*test_{kind}_{suffix} FAILED*"])
        for neighbor in _COLD_MODES:
            if neighbor != mode:
                status = "XFAIL" if widen else "FAILED"
                result.stdout.fnmatch_lines([
                    f"*test_neighbor_{suffix}_{neighbor.replace('-', '_')} {status}*",
                ])
    result.stdout.fnmatch_lines(["*XPASS(strict)*"])


_CLOSURE_MODES = ("missing-closure", "tampered-closure")


def _closure_control_source(mutation: str) -> str:
    source = _live_control_source(
        "test_profile_closure_preflight_live.py", "SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK", _CLOSURE_MODES,
        "test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner",
        widen=mutation == "base",
    )
    if mutation == "inverted":
        source += textwrap.dedent("""
            import inspect
            for ns, marker in MODULES.values():
                original = ns['_check_preflight']
                text = inspect.getsource(original)
                inverted = text.replace('not refused,', 'refused,')
                assert inverted != text, 'mutation no longer matches the actual healthy predicate'
                exec(inverted, original.__globals__)
                ns['_check_preflight'] = original.__globals__['_check_preflight']
        """)
    return source + textwrap.dedent("""
        SYMPTOMS = {
            'missing-closure': 'was not read back',
            'tampered-closure': 'disagrees with the expected',
        }

        def observe(ns, mode, kind):
            symptom = SYMPTOMS[mode]
            path = ns['_TARGET_RELPATH']
            reason = path + ' ' + symptom
            if kind == 'wrong_symptom':
                reason = path + ' ' + SYMPTOMS[next(m for m in MODES if m != mode)]
            elif kind == 'wrong_path':
                reason = 'another/file ' + symptom
            elif kind == 'path_prefix':
                reason = path + '.neighbor ' + symptom
            elif kind == 'unrelated':
                reason = 'a required tool is unavailable'
            ns['_check_preflight'](kind != 'intact', reason, expected_symptom=symptom)

        for mode in MODES:
            suffix = mode.replace('-', '_')
            for kind in ('target', 'intact', 'wrong_symptom', 'wrong_path', 'path_prefix', 'unrelated'):
                add_case('test_' + kind + '_' + suffix, mode,
                         lambda ns, m=mode, k=kind: observe(ns, m, k))
            add_case('test_infra_' + suffix, mode, infra)
            add_case('test_neighbor_runner_' + suffix, mode,
                     lambda ns: ns['_check_gate_classification']('makefile-fallback'))
    """)


@pytest.mark.parametrize("mutation", ["none", "base", "inverted"])
def test_closure_real_marker_and_refusal_oracle(pytester: pytest.Pytester, mutation: str) -> None:
    pytester.makepyfile(_closure_control_source(mutation))
    result = pytester.runpytest("-v", "--tb=short")
    result.assert_outcomes(xfailed=4 if mutation == "base" else 2, failed=12 if mutation == "base" else 14)
    for mode in _CLOSURE_MODES:
        suffix = mode.replace("-", "_")
        for kind in ("wrong_symptom", "wrong_path", "path_prefix", "unrelated", "infra"):
            result.stdout.fnmatch_lines([f"*test_{kind}_{suffix} FAILED*"])
        target = "FAILED" if mutation == "inverted" else "XFAIL"
        intact = "XFAIL" if mutation == "inverted" else "FAILED"
        neighbor = "XFAIL" if mutation == "base" else "FAILED"
        result.stdout.fnmatch_lines([f"*test_target_{suffix} {target}*"])
        result.stdout.fnmatch_lines([f"*test_intact_{suffix} {intact}*"])
        result.stdout.fnmatch_lines([f"*test_neighbor_runner_{suffix} {neighbor}*"])
    result.stdout.fnmatch_lines(["*XPASS(strict)*"])


@pytest.mark.parametrize("widen", [False, True], ids=["specific", "mutated-base"])
def test_image_tools_real_marker_excludes_infrastructure(pytester: pytest.Pytester, widen: bool) -> None:
    source = _live_control_source(
        "test_trial_image_tools_live.py", "SKILLC_TRIAL_IMAGE_BREAK", ("no-uv",),
        "test_uv_is_present_at_the_pinned_version", widen=widen,
    ) + textwrap.dedent("""
        from subprocess import CompletedProcess

        def observe(ns, returncode, version):
            # Invoke the actual test function; replace only the Docker I/O.
            with patch('subprocess.run', return_value=CompletedProcess([], returncode, version, '')):
                ns['test_uv_is_present_at_the_pinned_version']('unused-image')

        add_case('test_target', 'no-uv', lambda ns: observe(ns, 127, ''))
        add_case('test_wrong_version', 'no-uv', lambda ns: observe(ns, 0, 'uv 0.0.0'))
        add_case('test_intact', 'no-uv', lambda ns: observe(ns, 0, 'uv ' + ns['_PINNED_UV_VERSION']))
        add_case('test_infra', 'no-uv', infra)
    """)
    pytester.makepyfile(source)
    result = pytester.runpytest("-v", "--tb=short")
    result.assert_outcomes(xfailed=3 if widen else 2, failed=1 if widen else 2)
    result.stdout.fnmatch_lines(["*test_target XFAIL*", "*test_wrong_version XFAIL*", "*test_intact FAILED*"])
    result.stdout.fnmatch_lines([f"*test_infra {'XFAIL' if widen else 'FAILED'}*"])
    result.stdout.fnmatch_lines(["*XPASS(strict)*"])
