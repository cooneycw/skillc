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

import re
import textwrap
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

# uv 0.9.7's real offline cache-miss output, line wrapping included (#360).
# An invented paraphrase here once matched an oracle uv never satisfied.
_UV_OFFLINE_CACHE_MISS = (Path(__file__).parent / "fixtures" / "uv-offline-cache-miss-0.9.7.txt").read_text(
    encoding="utf-8")


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


_CWD_KINDS = ("target", "refused", "wrong_landing", "happy_path_broken", "swap_not_outside", "infra")


def _cwd_control_source(*, widen: bool) -> str:
    """#338's cwd-confinement control: the actual test function, driven with
    a scripted backend in `confine-root-omitted` mode. Only the swap that
    the real `-w` demonstrably followed outside the root may XFAIL; a
    refusal (the break never planted), a landing anywhere else, a broken
    happy path, a swap that never left the root, or an unrelated setup
    failure must each stay a hard failure. The mutation widens the actual
    marker's `raises` to `Exception`, which must turn those into XFAILs."""
    source = _live_control_source(
        "test_cwd_confinement_live.py", "SKILLC_CWD_CONFINEMENT_LIVE_BREAK", ("confine-root-omitted",),
        "test_a_swapped_cwd_is_refused_against_a_real_daemon", widen=False,
    )
    if widen:
        source += textwrap.dedent("""
            for ns, marker in MODULES.values():
                marker.kwargs['raises'] = Exception
        """)
    return source + textwrap.dedent("""
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import Mock
        _BASE = tempfile.TemporaryDirectory()
        # Only the live test's own `tempfile` name is replaced: patching
        # tempfile.mkdtemp module-wide also redirects TemporaryDirectory,
        # whose cleanup then deletes _BASE under every later case.
        _TEMPFILE = SimpleNamespace(
            mkdtemp=lambda prefix='': _BASE.name, TemporaryDirectory=tempfile.TemporaryDirectory,
        )

        def observe(ns, kind):
            if kind == 'infra':
                raise AssertionError('unrelated setup failure')
            d = ns['d']
            root = d.CONTAINER_WORKSPACE
            sub, outside = root + '/trial/sub', '/tmp/outside-root'
            handle = d._Handle(attempt_id='control', name='control', env={}, trigger_channel=object())
            backend = Mock()
            backend.prepare.return_value = handle
            backend.resolve_realpath_in_attempt.side_effect = [
                sub, sub if kind == 'swap_not_outside' else outside,
            ]
            happy = ('exited', 0, None, '/elsewhere' if kind == 'happy_path_broken' else sub)
            second = {
                'target': ('exited', 0, None, outside),
                'refused': ('launch-failed', None, d.CWD_CONFINEMENT_REFUSED_SENTINEL, ''),
                'wrong_landing': ('exited', 0, None, '/tmp/elsewhere'),
            }.get(kind, ('exited', 0, None, outside))
            test = ns['test_a_swapped_cwd_is_refused_against_a_real_daemon']
            with patch.object(d, 'DockerBackend', return_value=backend), \\
                    patch.dict(test.__globals__, {
                        'tempfile': _TEMPFILE,
                        '_image_available': lambda image: True,
                        '_exec_setup': lambda *args: None,
                        '_gate_cwd': Mock(side_effect=[happy, second]),
                    }):
                test()

        for kind in KINDS:
            add_case('test_' + kind, 'confine-root-omitted', lambda ns, k=kind: observe(ns, k))
    """).replace("KINDS", repr(_CWD_KINDS))


@pytest.mark.parametrize("widen", [False, True], ids=["specific", "mutated-exception"])
def test_cwd_confinement_real_marker_requires_the_followed_swap(pytester: pytest.Pytester, widen: bool) -> None:
    pytester.makepyfile(_cwd_control_source(widen=widen))
    result = pytester.runpytest("-v", "--tb=line")
    result.assert_outcomes(xfailed=len(_CWD_KINDS) if widen else 1, failed=0 if widen else len(_CWD_KINDS) - 1)
    if not widen:
        # Each hard failure must be the live test's own assertion, never a
        # scaffolding error from this control - otherwise every FAILED below
        # would be blind to the property it claims to separate.
        errors = re.findall(r"^E\s+(\w+)", result.stdout.str(), flags=re.MULTILINE)
        assert errors == ["AssertionError"] * (len(_CWD_KINDS) - 1), errors
    result.stdout.fnmatch_lines(["*test_target XFAIL*"])
    for kind in _CWD_KINDS[1:]:
        result.stdout.fnmatch_lines([f"*test_{kind} {'XFAIL' if widen else 'FAILED'}*"])


_FAMILIES = {
    "channel": (
        "test_decide_reply_channel_live.py", "SKILLC_LIVE_TEST_BREAK",
        ("omit-mount", "wrong-uid", "flip-decision"), "test_the_channel_round_trips_correctly_against_a_real_daemon",
    ),
    "overlay": (
        "test_gate_overlay_live.py", "SKILLC_GATE_SHIM_LIVE_BREAK",
        ("synthesizes-output", "drops-cwd", "wrong-env", "exits-zero-on-channel-failure"),
        "test_the_shim_forwards_the_controllers_real_result_against_a_real_daemon",
    ),
    "witness": (
        "test_gate_witness_live.py", "SKILLC_GATE_WITNESS_LIVE_BREAK",
        ("gate-in-fresh-container", "stale-confirm-lie", "kill-wrong-pid"),
        "test_the_gate_witness_round_trips_correctly_against_a_real_daemon",
    ),
}


def _family_control_source(family: str, widen: bool) -> str:
    filename, env, modes, name = _FAMILIES[family]
    source = _live_control_source(filename, env, modes, name, widen=widen)
    if family == "channel":
        source += textwrap.dedent("""
            PROPERTIES = ('connectivity', 'uid', 'decision')
            TARGETS = dict(zip(MODES, PROPERTIES))
            from types import SimpleNamespace
            from unittest.mock import Mock
            from skillc.backend import ExecuteResult, Confirmation
            import json
            def observe(ns, failed):
                handle = ns['d']._Handle(attempt_id='control', name='control', env={}, trigger_channel=object())
                reported = {
                    'uid': 0 if failed == 'uid' else ns['d'].CANDIDATE_UID,
                    'decisions': [] if failed == 'decision' else ['pass','pass','fail','pass','pass'],
                }
                backend = Mock()
                backend.prepare.return_value = handle
                code = {'connectivity': 91, 'launch': 127, 'runtime': 1, 'missing_proof': 91, 'malformed': 91}.get(failed, 0)
                if failed == 'connectivity': reported = {'channel_error': 'socket-missing'}
                if failed == 'malformed': reported = None
                backend.execute.return_value = ExecuteResult(reason='exited', exit_code=code)
                backend.confirm_stopped.return_value = Confirmation.CONFIRMED
                backend.export.side_effect = lambda handle, root: (root / 'observations').write_text(json.dumps(reported))
                backend.trigger_log.return_value = [SimpleNamespace(result={'decision': v}) for v in ['pass','pass','fail','pass','pass']]
                ns['test_the_channel_round_trips_correctly_against_a_real_daemon'](backend)
        """)
    elif family == "overlay":
        source += textwrap.dedent("""
            PROPERTIES = ('output', 'cwd', 'env', 'channel')
            TARGETS = dict(zip(MODES, PROPERTIES))
            def observe(ns, failed):
                argv = ['--plan', 'check', '--evidence', 'flow-check']
                output = ns['_expected_output'](argv, ns['_DECLARED_HOME'])
                code = 3
                if failed == 'output':
                    output, code = 'FLOW_FINISH_GATE: ok\\n', 0
                if failed in ('cwd', 'both'):
                    output = output.replace('CWD:' + ns['TINY_PROJECT_DIR'], 'CWD:/work')
                if failed in ('env', 'both'):
                    output = output.replace('HOME:' + ns['_home_digest'](ns['_DECLARED_HOME']), 'HOME:wrong')
                if failed == 'malformed':
                    output = 'unrelated output\\n'
                if failed == 'exit':
                    code = 127
                from unittest.mock import Mock
                from skillc.backend import ExecuteResult
                handle = ns['d']._Handle(attempt_id='control', name='control', env={}, trigger_channel=object())
                backend = Mock()
                backend.prepare.return_value = handle
                backend.exec_in_attempt.return_value = ExecuteResult(reason='exited', exit_code=0)
                def read_result(backend, handle, path):
                    if 'channel-failure' in path:
                        return {'exit_code': {'channel': 0, 'channel_launch': 127, 'channel_malformed': None}.get(failed, 125), 'stdout': ''}
                    if 'summary' in path:
                        return {'exit_code': 0, 'stdout': ns['_expected_output'](['--check-summary'], ns['_DECLARED_HOME'])}
                    return {'exit_code': code, 'stdout': output}
                test = ns['test_the_shim_forwards_the_controllers_real_result_against_a_real_daemon']
                with patch.object(ns['d'], 'DockerBackend', return_value=backend), patch.dict(test.__globals__, {
                    '_image_available': lambda image: True,
                    '_prepare_candidate_dirs': lambda *args: None,
                    'apply_flow_check_gate_overlay': lambda *args, **kwargs: None,
                    'GateWitness': Mock(), '_read_result_via_exec': read_result,
                }):
                    test()
        """)
    else:
        source += textwrap.dedent("""
            from skillc.backend import ExecuteResult
            PROPERTIES = ('concurrent', 'kill', 'primary')
            TARGETS = {'gate-in-fresh-container': 'concurrent', 'stale-confirm-lie': 'kill', 'kill-wrong-pid': 'kill'}
            def observe(ns, failed):
                ns['_check_concurrent_reply'](
                    {'reason': 'exited', 'exit_code': 1 if failed in ('concurrent','unproven') else 0},
                    missing_marker_confirmed=failed == 'concurrent',
                )
                ns['_check_kill_observation'](
                    None if failed == 'unknown' else failed == 'kill', failed != 'unconfirmed',
                )
                ns['_check_primary']([ExecuteResult(reason='exited', exit_code=1 if failed == 'primary' else 0)], 1, 2)
        """)
    source += textwrap.dedent("""
        for mode in MODES:
            suffix = mode.replace('-', '_')
            add_case('test_target_' + suffix, mode, lambda ns, m=mode: observe(ns, TARGETS[m]))
            add_case('test_intact_' + suffix, mode, lambda ns: observe(ns, None))
            add_case('test_infra_' + suffix, mode, infra)
            for prop in PROPERTIES:
                if prop != TARGETS[mode]:
                    add_case('test_neighbor_' + suffix + '_' + prop, mode, lambda ns, p=prop: observe(ns, p))
    """)
    extras = {"channel": ("launch", "runtime", "missing_proof", "malformed"), "overlay": ("malformed", "exit", "both", "channel_launch", "channel_malformed"), "witness": ("unknown", "unconfirmed", "unproven")}[family]
    source += textwrap.dedent(f"""
        for mode in MODES:
            for extra in {extras!r}:
                add_case('test_hard_' + mode.replace('-', '_') + '_' + extra, mode,
                         lambda ns, e=extra: observe(ns, e))
    """)
    return source


@pytest.mark.parametrize("family", ["channel", "overlay", "witness"])
@pytest.mark.parametrize("widen", [False, True], ids=["specific", "mutated-base"])
def test_live_family_real_markers_and_predicates(pytester: pytest.Pytester, family: str, widen: bool) -> None:
    pytester.makepyfile(_family_control_source(family, widen))
    result = pytester.runpytest("-v", "--tb=short")
    modes = _FAMILIES[family][2]
    properties = {
        "channel": ("connectivity", "uid", "decision"),
        "overlay": ("output", "cwd", "env", "channel"),
        "witness": ("concurrent", "kill", "primary"),
    }[family]
    targets = ("concurrent", "kill", "kill") if family == "witness" else properties
    extras = {"channel": ("launch", "runtime", "missing_proof", "malformed"), "overlay": ("malformed", "exit", "both", "channel_launch", "channel_malformed"), "witness": ("unknown", "unconfirmed", "unproven")}[family]
    count = len(modes) * (len(properties) + 2 + len(extras))
    xfails = len(modes) * (len(properties) if widen else 1)
    result.assert_outcomes(xfailed=xfails, failed=count - xfails)
    for mode, target in zip(modes, targets, strict=True):
        suffix = mode.replace("-", "_")
        for kind, status in (("target", "XFAIL"), ("intact", "FAILED"), ("infra", "FAILED")):
            result.stdout.fnmatch_lines([f"*test_{kind}_{suffix} {status}*"])
        for prop in properties:
            if prop != target:
                result.stdout.fnmatch_lines([f"*test_neighbor_{suffix}_{prop} {'XFAIL' if widen else 'FAILED'}*"])
        for extra in extras:
            result.stdout.fnmatch_lines([f"*test_hard_{suffix}_{extra} FAILED*"])
    result.stdout.fnmatch_lines(["*XPASS(strict)*"])


def _witness_namespace():
    import runpy
    from unittest.mock import patch
    with patch.dict("os.environ", {"SKILLC_GATE_WITNESS_LIVE_BREAK": "none"}), patch("shutil.which", return_value=None):
        return runpy.run_path(str(_ROOT / "tests" / "test_gate_witness_live.py"))


@pytest.mark.parametrize("fault", [None, "setup", "exec", "read"])
@pytest.mark.parametrize("confine_root", [None, "/work"], ids=["default", "confined"])
def test_actual_fresh_transport_forwards_arguments_and_always_cleans_up(monkeypatch, fault, confine_root):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from skillc.backend import ExecuteResult, Limits
    ns = _witness_namespace()
    handle = ns["d"]._Handle(attempt_id="fresh", name="fresh", env={})
    backend = SimpleNamespace(prepare=Mock(return_value=handle), install=Mock(), destroy=Mock())
    setup = Mock(side_effect=RuntimeError("setup") if fault == "setup" else None)
    read = Mock(return_value=None if fault == "read" else "PRIMARY_MARKER: absent\n")
    monkeypatch.setitem(ns["_make_fresh_exec"].__globals__, "_prepare_candidate_workspace", setup)
    monkeypatch.setitem(ns["_make_fresh_exec"].__globals__, "_read_file_via_exec", read)
    result = ExecuteResult(reason="exited", exit_code=1)
    real_exec = Mock(return_value=result, side_effect=RuntimeError("exec") if fault == "exec" else None)
    observed = []
    callback = ns["_make_fresh_exec"](real_exec, observed)
    original = object()
    args, limits, cancel, data, env = ["python3", "-c", "pass"], Limits(timeout=2), lambda: False, b"input", {"HOME": "/declared"}
    confinement = {} if confine_root is None else {"confine_root": confine_root}
    if fault:
        with pytest.raises(AssertionError if fault == "read" else RuntimeError):
            callback(backend, original, args, limits, cancel, data, cwd="/work", env=env, **confinement)
    else:
        assert callback(backend, original, args, limits, cancel, data, cwd="/work", env=env, **confinement) is result
        assert observed == [(1, "PRIMARY_MARKER: absent\n")]
    backend.destroy.assert_called_once_with(handle)
    if fault == "setup":
        real_exec.assert_not_called()
    else:
        real_exec.assert_called_once_with(
            backend, handle, args, limits, cancel, data, cwd="/work", env=env, confine_root=confine_root,
        )


def test_fresh_transport_control_rejects_dropped_confinement(monkeypatch):
    import inspect

    ns = _witness_namespace()
    original = ns["_make_fresh_exec"]
    source = inspect.getsource(original)
    mutated = source.replace(", confine_root=confine_root", "")
    assert mutated != source
    exec(mutated, original.__globals__)  # noqa: S102 - mutate only this trusted test source
    ns["_make_fresh_exec"] = original.__globals__["_make_fresh_exec"]
    control = test_actual_fresh_transport_forwards_arguments_and_always_cleans_up
    monkeypatch.setitem(control.__globals__, "_witness_namespace", lambda: ns)
    with pytest.raises(AssertionError, match="expected call not found"):
        control(monkeypatch, None, "/work")


def test_actual_primary_bypasses_gate_transport_and_propagates_failure():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from skillc.backend import ExecuteResult
    ns = _witness_namespace()
    result = ExecuteResult(reason="exited", exit_code=0)
    real_exec, forbidden = Mock(return_value=result), Mock(side_effect=AssertionError("gate-only substitution"))
    backend = SimpleNamespace(exec_in_attempt=forbidden, execute=forbidden)
    results, errors = [], []
    handle = object()
    ns["_run_primary"](real_exec, backend, handle, results, errors)
    assert results == [result] and errors == []
    assert real_exec.call_args.args[:2] == (backend, handle)
    forbidden.assert_not_called()
    error = RuntimeError("primary transport")
    ns["_run_primary"](Mock(side_effect=error), backend, handle, results, errors)
    assert errors == [error]


@pytest.mark.parametrize("stuck", [False, True])
@pytest.mark.parametrize("destroy_fails", [False, True])
def test_actual_cleanup_joins_with_a_bound_even_when_destroy_fails(stuck, destroy_fails):
    from types import SimpleNamespace
    from unittest.mock import Mock
    ns = _witness_namespace()
    backend = SimpleNamespace(daemon_timeout=2, destroy=Mock(side_effect=RuntimeError("destroy") if destroy_fails else None))
    thread = SimpleNamespace(join=Mock(), is_alive=Mock(return_value=stuck))
    if stuck or destroy_fails:
        with pytest.raises(AssertionError if stuck else RuntimeError):
            ns["_destroy_and_join"](backend, "handle", thread)
    else:
        ns["_destroy_and_join"](backend, "handle", thread)
    backend.destroy.assert_called_once_with("handle")
    thread.join.assert_called_once_with(timeout=2 + ns["GATE_GRACE"])


def test_cold_cache_complete_function_reaches_the_healthy_predicate(pytester: pytest.Pytester) -> None:
    source = _live_control_source(
        "test_profile_install_cold_container_live.py", "SKILLC_COLDINSTALL_LIVE_BREAK", ("cold-cache",),
        "test_profile_runs_cold_with_no_operator_mounts", widen=False,
    ) + textwrap.dedent("""
        from subprocess import CompletedProcess
        from pathlib import Path
        from tempfile import TemporaryDirectory
        def observe(ns, code, stderr):
            def install(home):
                checkout = home / 'Projects' / 'claude-power-pack'
                checkout.mkdir(parents=True)
                (checkout / 'uv.lock').write_text('lock')
            def run(argv, **kwargs):
                command = str(argv[-1])
                if 'lockfile.sha256' in command:
                    return CompletedProcess(argv, 0, 'MISSING', '')
                if 'uv sync' in command:
                    return CompletedProcess(argv, code, '', stderr)
                return CompletedProcess(argv, 0, 'runner', '')
            test = ns['test_profile_runs_cold_with_no_operator_mounts']
            with TemporaryDirectory() as tmp, patch.dict(test.__globals__, {
                '_install_profile': install, '_build_image': lambda *args: None,
                '_run': run, '_container_mounts': lambda container: [],
            }), patch.object(ns['gate_path'], 'classify_gate_output', return_value='real-runner'):
                test(Path(tmp))
        add_case('test_target', 'cold-cache', lambda ns: observe(ns, 1, "wasn't found in the cache"))
        add_case('test_intact', 'cold-cache', lambda ns: observe(ns, 0, ''))
        add_case('test_unrelated', 'cold-cache', lambda ns: observe(ns, 127, 'uv not found'))
    """)
    pytester.makepyfile(source)
    result = pytester.runpytest("-v", "--tb=short")
    result.assert_outcomes(xfailed=1, failed=2)
    result.stdout.fnmatch_lines(["*test_target XFAIL*", "*test_intact FAILED*", "*test_unrelated FAILED*"])
    result.stdout.fnmatch_lines(["*XPASS(strict)*"])


def _drive_closure(ns, refusal, monkeypatch, output_fault=None, subject_fault=None) -> None:
    from unittest.mock import Mock, patch

    from skillc.backend import ExecuteResult
    entrypoint = ".claude/scripts/flow-finish-gate.sh"
    files = {entrypoint: b"real", ns["_TARGET_RELPATH"]: b"library"}
    digests = {path: "sha256:" + "a" * 64 for path in files}
    backend = Mock()
    stdout = (b"flow-finish-gate: running deterministic gate (lib.cicd run --plan check)\n"
              + ns["_DISCRIMINATION_VERDICT"])
    stderr = b"  [3/3] typecheck: SKIPPED\nFLOW_FINISH_GATE_EXIT=3\n"
    exit_code = 0 if output_fault == "wrong-verdict" else ns["_DISCRIMINATION_EXIT"]
    backend.execute.return_value = ExecuteResult(
        reason="exited", exit_code=exit_code,
        stdout=None if output_fault == "missing" else b"\xff" if output_fault == "invalid" else stdout,
        stdout_truncated=output_fault == "truncated",
        stdout_incomplete=output_fault == "stdout-incomplete",
        stderr_incomplete=output_fault == "stderr-incomplete",
        stderr=stderr[:4] if output_fault == "stderr-truncated" else stderr,
        stderr_truncated=output_fault == "stderr-truncated",
    )
    witness = Mock()
    witness.return_value.finalize.return_value.gates = {
        ns["_GATE_NAME"]: Mock(coverage="not-observed" if output_fault == "unwitnessed" else "complete"),
    }
    test = ns["test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner"]
    monkeypatch.setitem(test.__globals__, "_closure_inputs", lambda: (files, digests, (), entrypoint))
    supply = Mock(image_id="sha256:" + "a" * 64)
    backend.image_id.return_value = supply.image_id
    backend.runtime_environment.return_value = {"HOME": "/home/candidate"}
    backend.gate_outputs = [backend.execute.return_value]
    # Healthy/forged subject output cannot replace broken controller bytes.
    # `subject_fault` changes only what the subject saw (#334 byte identity).
    backend.execute.return_value = ExecuteResult(
        reason="exited", exit_code=ns["_DISCRIMINATION_EXIT"] + (subject_fault == "exit"),
        stdout=stdout + b" " * (subject_fault == "stdout"),
        stderr=None if subject_fault == "uncaptured" else stderr[:-1] if subject_fault == "stderr" else stderr,
    )
    monkeypatch.setitem(test.__globals__, "_build_trial_image", lambda *args: (supply, lambda: None))
    monkeypatch.setitem(test.__globals__, "_baseline_acceptance", lambda *args: None)
    for helper in ("_environment_controls", "_generic_offline_control", "_observe_delivery", "_check_metadata"):
        monkeypatch.setitem(test.__globals__, helper, lambda *args: None)
    monkeypatch.setitem(test.__globals__, "_RuntimeBackend", lambda **kwargs: backend)
    replacements = []
    def replace_backend(original, **kwargs):
        replacements.append(kwargs["frozen_preflight"])
        return original
    monkeypatch.setitem(test.__globals__, "replace", replace_backend)
    monkeypatch.setitem(test.__globals__, "GateWitness", witness)
    diagnostics = {
        "empty-runtime-cache": _UV_OFFLINE_CACHE_MISS,
        "runtime-cache-permissions": "Permission denied: /home/candidate/.cache/uv/.lock",
        "project-venv-permissions": "Permission denied: /home/candidate/Projects/claude-power-pack/.venv",
    }
    monkeypatch.setitem(test.__globals__, "_runtime_diagnostic", lambda *args: diagnostics[ns["BREAK_MODE"]])
    error = None
    if refusal == "target":
        reason = ("tool dependency 'tool-pypi-runtime' was not verified in-container"
                  if ns["BREAK_MODE"] in ns["_RUNTIME_MODES"] else
                  ns["_TARGET_RELPATH"] + " " + ns["_REFUSAL_SYMPTOMS"][ns["BREAK_MODE"]])
        error = ns["at"].HomeFileVerificationRefused(reason)
    elif refusal == "unrelated":
        error = ns["at"].HomeFileVerificationRefused("a tool could not be verified")
    with patch.object(ns["d"], "DockerBackend", return_value=backend), \
            patch.object(ns["at"], "_preflight_in_container", side_effect=error), \
            patch.object(ns["gate_overlay"], "apply_flow_check_gate_overlay"), \
            patch("subprocess.run"):
        test()
    assert replacements == [False, True]
    assert backend.prepare.call_count == 2
    assert backend.prepare.call_args_list[0] != backend.prepare.call_args_list[1]
    assert witness.call_args.kwargs["declared_gates"] == {
        ns["_GATE_NAME"]: (ns["_HARNESS_ABS"], *ns["_GATE_ARGV_TAIL"]),
    }
    assert f"exec {ns['d'].CONTAINER_HOME}/{entrypoint} " in backend.execute.call_args.args[1][-1]


_CLOSURE_OUTPUT_FAULTS = (None, "missing", "truncated", "stdout-incomplete", "stderr-incomplete", "invalid",
                          "stderr-truncated", "wrong-verdict", "unwitnessed")


@pytest.mark.parametrize("fault", _CLOSURE_OUTPUT_FAULTS)
def test_closure_consumes_complete_controller_output_not_forged_artifacts(monkeypatch, fault) -> None:
    import runpy
    from unittest.mock import patch

    from skillc import gate_witness

    # A forged legacy artifact can classify as healthy. It must never supply
    # missing controller output or hide its incomplete/invalid measurement.
    monkeypatch.setattr(gate_witness, "_read_observations", lambda *args, **kwargs:
                        "flow-finish-gate: running deterministic gate (lib.cicd run --plan check)", raising=False)
    with patch.dict("os.environ", {"SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK": "none"}), patch("shutil.which", return_value=None):
        ns = runpy.run_path(str(_ROOT / "tests" / "test_profile_closure_preflight_live.py"))
    if fault is None:
        _drive_closure(ns, None, monkeypatch)
    else:
        expected = UnicodeDecodeError if fault == "invalid" else AssertionError
        with pytest.raises(expected) as raised:
            _drive_closure(ns, None, monkeypatch, fault)
        assert type(raised.value) is expected  # generic failure, never a targeted-property exception


@pytest.mark.parametrize("old_routing", [False, True], ids=["harness", "mutated-subject-shim"])
def test_closure_complete_function_routes_controller_to_harness(monkeypatch, old_routing) -> None:
    import inspect
    import runpy
    from unittest.mock import patch
    with patch.dict("os.environ", {"SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK": "none"}), patch("shutil.which", return_value=None):
        ns = runpy.run_path(str(_ROOT / "tests" / "test_profile_closure_preflight_live.py"))
    if old_routing:
        name = "test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner"
        original = ns[name]
        source = inspect.getsource(original)
        mutated = source.replace("declared_gates={_GATE_NAME: (_HARNESS_ABS,", "declared_gates={_GATE_NAME: (subject_abs,")
        assert mutated != source
        exec(mutated, original.__globals__)  # noqa: S102 - mutate only this trusted test source
        ns[name] = original.__globals__[name]
        with pytest.raises(AssertionError):
            _drive_closure(ns, None, monkeypatch)
    else:
        _drive_closure(ns, None, monkeypatch)


def test_closure_complete_function_refusals_and_missed_refusal(pytester: pytest.Pytester) -> None:
    source = _live_control_source(
        "test_profile_closure_preflight_live.py", "SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK", _CLOSURE_MODES,
        "test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner", widen=False,
    ) + textwrap.dedent(f"""
        controls = runpy.run_path({str(Path(__file__).resolve())!r})
        def observe(ns, refusal):
            with pytest.MonkeyPatch.context() as mp:
                controls['_drive_closure'](ns, refusal, mp)
        for mode in MODES:
            for kind in ('target', 'intact', 'unrelated'):
                add_case('test_' + kind + '_' + mode.replace('-', '_'), mode,
                         lambda ns, k=kind: observe(ns, k))
    """)
    pytester.makepyfile(source)
    result = pytester.runpytest("-v", "--tb=short")
    result.assert_outcomes(xfailed=2, failed=4)
    for mode in _CLOSURE_MODES:
        suffix = mode.replace("-", "_")
        for kind, status in (("target", "XFAIL"), ("intact", "FAILED"), ("unrelated", "FAILED")):
            result.stdout.fnmatch_lines([f"*test_{kind}_{suffix} {status}*"])
    result.stdout.fnmatch_lines(["*XPASS(strict)*"])


def test_closure_output_faults_cannot_receive_targeted_xfail_credit(pytester: pytest.Pytester) -> None:
    source = _live_control_source(
        "test_profile_closure_preflight_live.py", "SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK", _CLOSURE_MODES,
        "test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner", widen=False,
    ) + textwrap.dedent(f"""
        controls = runpy.run_path({str(Path(__file__).resolve())!r})
        def observe(ns, fault):
            with pytest.MonkeyPatch.context() as mp:
                controls['_drive_closure'](ns, None, mp, fault)
        for mode in MODES:
            for fault in {_CLOSURE_OUTPUT_FAULTS!r}:
                add_case('test_' + str(fault).replace('-', '_') + '_' + mode.replace('-', '_'), mode,
                         lambda ns, f=fault: observe(ns, f))
    """)
    pytester.makepyfile(source)
    result = pytester.runpytest("-v", "--tb=short")
    result.assert_outcomes(failed=2 * len(_CLOSURE_OUTPUT_FAULTS))
    result.stdout.fnmatch_lines(["*XPASS(strict)*"])
    for mode in _CLOSURE_MODES:
        for fault in (str(f).replace("-", "_") for f in _CLOSURE_OUTPUT_FAULTS if f is not None):
            result.stdout.fnmatch_lines([f"*test_{fault}_{mode.replace('-', '_')} FAILED*"])


_IDENTITY_TARGETS = ("stderr", "stdout", "exit")


@pytest.mark.parametrize("widen", [False, True], ids=["specific", "mutated-base"])
def test_closure_forwarding_identity_real_marker(pytester: pytest.Pytester, widen: bool) -> None:
    """#334: `shim-alters-output` drives the actual test function. Only a
    subject that saw different stdout, stderr or exit code than the
    controller's real run may XFAIL. An identical subject (the break never
    planted) is strict XPASS; an uncaptured subject stream, a wrong real
    verdict, an unwitnessed gate, a capped controller stderr and the
    neighbouring runner property each stay hard failures, even beside an
    altered stderr. Widening the actual marker to the shared base must
    turn the neighbour into an XFAIL."""
    source = _live_control_source(
        "test_profile_closure_preflight_live.py", "SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK", ("shim-alters-output",),
        "test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner", widen=widen,
    ) + textwrap.dedent(f"""
        controls = runpy.run_path({str(Path(__file__).resolve())!r})
        def observe(ns, output_fault, subject_fault):
            with pytest.MonkeyPatch.context() as mp:
                controls['_drive_closure'](ns, None, mp, output_fault, subject_fault)
        mode = 'shim-alters-output'
        for target in {_IDENTITY_TARGETS!r}:
            add_case('test_target_' + target, mode, lambda ns, t=target: observe(ns, None, t))
        add_case('test_intact', mode, lambda ns: observe(ns, None, None))
        add_case('test_uncaptured', mode, lambda ns: observe(ns, None, 'uncaptured'))
        for fault in ('wrong-verdict', 'unwitnessed', 'stderr-truncated'):
            add_case('test_' + fault.replace('-', '_'), mode, lambda ns, f=fault: observe(ns, f, 'stderr'))
        add_case('test_neighbor_runner', mode,
                 lambda ns: ns['_check_gate_classification']('makefile-fallback'))
        add_case('test_infra', mode, infra)
    """)
    pytester.makepyfile(source)
    result = pytester.runpytest("-v", "--tb=short")
    result.assert_outcomes(xfailed=4 if widen else 3, failed=6 if widen else 7)
    for target in _IDENTITY_TARGETS:
        result.stdout.fnmatch_lines([f"*test_target_{target} XFAIL*"])
    for case in ("intact", "uncaptured", "wrong_verdict", "unwitnessed", "stderr_truncated", "infra"):
        result.stdout.fnmatch_lines([f"*test_{case} FAILED*"])
    result.stdout.fnmatch_lines([f"*test_neighbor_runner {'XFAIL' if widen else 'FAILED'}*"])
    result.stdout.fnmatch_lines(["*XPASS(strict)*"])


@pytest.mark.parametrize("error", [FileNotFoundError("absent"), PermissionError("denied"), RuntimeError("unrelated")])
def test_actual_channel_subject_reports_only_missing_socket(error, capsys) -> None:
    import json
    import runpy
    from unittest.mock import Mock, patch
    with patch("shutil.which", return_value=None):
        ns = runpy.run_path(str(_ROOT / "tests" / "test_decide_reply_channel_live.py"))
    client = Mock()
    client.connect.side_effect = error
    with patch("socket.socket", return_value=client):
        if isinstance(error, FileNotFoundError):
            with pytest.raises(SystemExit) as raised:
                exec(ns["_subject_script"](), {})  # noqa: S102 - execute the actual fixed test subject
            assert raised.value.code == 91
            assert json.loads(capsys.readouterr().out) == {"channel_error": "socket-missing"}
        else:
            with pytest.raises(type(error)):
                exec(ns["_subject_script"](), {})  # noqa: S102 - execute the actual fixed test subject


_RUNTIME_MODES = ("empty-runtime-cache", "runtime-cache-permissions", "project-venv-permissions")


def _closure_namespace(mode="none"):
    import runpy
    from unittest.mock import patch
    with patch.dict("os.environ", {"SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK": mode}), patch("shutil.which", return_value=None):
        return runpy.run_path(str(_ROOT / "tests" / "test_profile_closure_preflight_live.py"))


@pytest.mark.parametrize("mode", _RUNTIME_MODES)
def test_runtime_fault_requires_dependency_and_specific_diagnostic(mode) -> None:
    ns = _closure_namespace()
    check = ns["_check_runtime_preflight"]
    reason = "tool dependency 'tool-pypi-runtime' was not verified in-container"
    diagnostic = {
        "empty-runtime-cache": _UV_OFFLINE_CACHE_MISS,
        "runtime-cache-permissions": "Permission denied (os error 13): /home/candidate/.cache/uv/.lock",
        "project-venv-permissions": "Permission denied (os error 13): /home/candidate/Projects/claude-power-pack/.venv",
    }[mode]
    with pytest.raises(ns["_MODE_PROPERTY"][mode]):
        check(True, reason, mode=mode, diagnostic=diagnostic)
    check(False, "", mode=mode, diagnostic="")  # unchanged healthy predicate; marker must XPASS
    for bad_reason, bad_diag in ((reason.replace("tool-pypi-runtime", "neighbor"), diagnostic),
                                 (reason, "IMPORT_FAIL"), (reason, "timed out"),
                                 (reason, diagnostic.replace(".cache/uv", ".cache/other").replace("claude-power-pack/.venv", "neighbor/.venv"))):
        if bad_diag == diagnostic:
            continue
        with pytest.raises(AssertionError) as error:
            check(True, bad_reason, mode=mode, diagnostic=bad_diag)
        assert type(error.value) is AssertionError
    with pytest.raises(AssertionError):
        check(True, reason.replace("tool-pypi-runtime", "neighbor"), mode=mode, diagnostic=diagnostic)


@pytest.mark.parametrize("decoy", [False, True])
def test_actual_baseline_scan_detects_recognized_skill_decoy(tmp_path, decoy) -> None:
    import json
    import subprocess
    import sys
    ns = _closure_namespace()
    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    if decoy:
        skill = home / ".codex" / "skills" / "decoy" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("decoy")
    result = subprocess.run([sys.executable, "-c", ns["_BASELINE_SCAN"], str(home), str(work)],
                            capture_output=True, check=False)
    assert result.returncode == 0
    if decoy:
        with pytest.raises(AssertionError, match="baseline"):
            ns["_check_baseline_scan"](result.stdout)
    else:
        ns["_check_baseline_scan"](result.stdout)
    with pytest.raises(AssertionError):
        ns["_check_baseline_scan"](json.dumps({"roots": [], "hits": []}).encode())
    missing = subprocess.run([sys.executable, "-c", ns["_BASELINE_SCAN"], str(home / "absent")],
                             capture_output=True, check=False)
    assert missing.returncode != 0


@pytest.mark.parametrize("widen", [False, True], ids=["specific", "mutated-base"])
def test_runtime_real_markers_exclude_neighbor_properties(pytester, widen) -> None:
    source = _live_control_source(
        "test_profile_closure_preflight_live.py", "SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK", _RUNTIME_MODES,
        "test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner", widen=widen,
    ) + textwrap.dedent("""
        def observe(ns, kind):
            mode = ns['BREAK_MODE']
            reason = "tool dependency 'tool-pypi-runtime' was not verified in-container"
            diagnostic = {
                'empty-runtime-cache': "Network connectivity is disabled, but the\\n      requested data wasn't found in the cache for: pydantic-core",
                'runtime-cache-permissions': 'Permission denied: /home/candidate/.cache/uv/.lock',
                'project-venv-permissions': 'Permission denied: /home/candidate/Projects/claude-power-pack/.venv',
            }[mode]
            if kind == 'neighbor':
                ns['_check_gate_classification']('fallback')
            if kind == 'wrong-dependency':
                reason = reason.replace('tool-pypi-runtime', 'neighbor')
            if kind == 'wrong-symptom':
                diagnostic = 'IMPORT_FAIL'
            ns['_check_runtime_preflight'](kind != 'intact', reason, mode=mode, diagnostic=diagnostic)
        for mode in MODES:
            for kind in ('target', 'intact', 'neighbor', 'wrong-dependency', 'wrong-symptom'):
                add_case('test_' + kind.replace('-', '_') + '_' + mode.replace('-', '_'), mode,
                         lambda ns, k=kind: observe(ns, k))
    """)
    pytester.makepyfile(source)
    result = pytester.runpytest("-v", "--tb=short")
    result.assert_outcomes(xfailed=6 if widen else 3, failed=9 if widen else 12)
    for mode in _RUNTIME_MODES:
        for kind, status in (("target", "XFAIL"), ("intact", "FAILED"),
                             ("neighbor", "XFAIL" if widen else "FAILED"),
                             ("wrong_dependency", "FAILED"), ("wrong_symptom", "FAILED")):
            result.stdout.fnmatch_lines([f"*test_{kind}_{mode.replace('-', '_')} {status}*"])
    result.stdout.fnmatch_lines(["*XPASS(strict)*"])


def test_runtime_complete_function_target_missed_and_unrelated_failures(pytester) -> None:
    source = _live_control_source(
        "test_profile_closure_preflight_live.py", "SKILLC_CLOSURE_PREFLIGHT_LIVE_BREAK", _RUNTIME_MODES,
        "test_a_treated_attempts_closure_is_verified_and_the_gate_reaches_the_real_runner", widen=False,
    ) + textwrap.dedent(f"""
        controls = runpy.run_path({str(Path(__file__).resolve())!r})
        def observe(ns, kind):
            with pytest.MonkeyPatch.context() as mp:
                controls['_drive_closure'](ns, kind, mp)
        for mode in MODES:
            for kind in ('target', 'intact', 'unrelated'):
                add_case('test_' + kind + '_' + mode.replace('-', '_'), mode,
                         lambda ns, k=kind: observe(ns, k))
    """)
    pytester.makepyfile(source)
    result = pytester.runpytest("-v", "--tb=short")
    result.assert_outcomes(xfailed=3, failed=6)
    for mode in _RUNTIME_MODES:
        for kind, status in (("target", "XFAIL"), ("intact", "FAILED"), ("unrelated", "FAILED")):
            result.stdout.fnmatch_lines([f"*test_{kind}_{mode.replace('-', '_')} {status}*"])
    result.stdout.fnmatch_lines(["*XPASS(strict)*"])


@pytest.mark.parametrize("refuse", [False, True])
def test_actual_runtime_wrapper_validates_before_fault_without_warming(monkeypatch, tmp_path, refuse) -> None:
    ns = _closure_namespace()
    events = []
    backend = ns["_RuntimeBackend"](image="image", base_dir=tmp_path, fault="project-venv-permissions")
    def validate(self, handle, limits, verified):
        events.append("validated")
        if refuse:
            raise ValueError("receipt/image/environment refusal")
        return {"HOME": "/home/candidate"}
    monkeypatch.setattr(ns["d"].DockerBackend, "runtime_environment", validate)
    monkeypatch.setattr(ns["d"].DockerBackend, "controller_output", lambda self, handle, argv, limits:
                        events.append(tuple(argv)))
    if refuse:
        with pytest.raises(ValueError):
            backend.runtime_environment(object(), ns["_LIVE_LIMITS"], {"file": "digest"})
        assert events == ["validated"]
    else:
        assert backend.runtime_environment(object(), ns["_LIVE_LIMITS"], {"file": "digest"}) == {"HOME": "/home/candidate"}
        assert events == ["validated", ("chmod", "a-w", ns["_PROJECT"])]


@pytest.mark.parametrize("fault", [None, "missing", "truncated", "incomplete", "timeout", "wrong-env", "repeat"])
def test_actual_bounded_observer_uses_controller_call_only(monkeypatch, tmp_path, fault) -> None:
    from skillc.backend import ExecuteResult
    ns = _closure_namespace()
    backend = ns["_RuntimeBackend"](image="image", base_dir=tmp_path)
    backend.frozen_env.update(HOME="/home/candidate")
    result = ExecuteResult(reason="timeout" if fault == "timeout" else "exited", exit_code=0,
                           stdout=None if fault == "missing" else b"controller",
                           stdout_truncated=fault == "truncated", stdout_incomplete=fault == "incomplete")
    monkeypatch.setattr(ns["d"].DockerBackend, "exec_in_attempt", lambda *args, **kwargs: result)
    # A primary/subject call cannot fill the controller observation slot.
    backend.exec_in_attempt(object(), ["subject-shim"], ns["_LIVE_LIMITS"])
    assert backend.gate_outputs == []
    if fault == "repeat":
        backend.gate_outputs.append(result)
    kwargs = {"env": {} if fault == "wrong-env" else dict(backend.frozen_env)}
    if fault:
        with pytest.raises(AssertionError):
            backend.exec_in_attempt(object(), [ns["_HARNESS_ABS"]], ns["_LIVE_LIMITS"], **kwargs)
    else:
        backend.exec_in_attempt(object(), [ns["_HARNESS_ABS"]], ns["_LIVE_LIMITS"], **kwargs)
        assert backend.gate_outputs == [result]


@pytest.mark.parametrize("fault", [None, "uid", "gid", "mode", "writable", "symlink", "venv", "candidate", "empty"])
def test_delivery_ownership_measurement_has_discriminating_controls(fault) -> None:
    import json
    ns = _closure_namespace()
    record = {"candidate": ns["d"].CANDIDATE_UID, "venv": False, "paths": [
        {"uid": ns["d"].CANDIDATE_UID, "gid": ns["d"].CANDIDATE_GID,
         "mode": 0o755, "writable": True, "symlink": False} for _ in range(2)]}
    if fault == "empty":
        record["paths"] = []
    elif fault in ("uid", "gid", "mode"):
        record["paths"][0][fault] = 0
    elif fault in ("writable", "symlink"):
        record["paths"][0][fault] = fault == "symlink"
    elif fault == "venv":
        record["venv"] = True
    elif fault == "candidate":
        record["candidate"] = 0
    if fault:
        with pytest.raises(AssertionError):
            ns["_check_delivery"](json.dumps(record).encode())
    else:
        ns["_check_delivery"](json.dumps(record).encode())


@pytest.mark.parametrize("changed", [None, "pyproject.toml", "uv.lock"])
def test_post_gate_metadata_matches_exact_pinned_bytes(changed) -> None:
    from unittest.mock import Mock
    ns = _closure_namespace()
    backend = Mock()
    def read(handle, path):
        original = (ns["FIXTURE_DIR"] / Path(path).name).read_bytes()
        return original + b"\nchanged" if Path(path).name == changed else original
    backend.read_home_file.side_effect = read
    verified = {"Projects/claude-power-pack/" + name: ns["m"].sha256_bytes((ns["FIXTURE_DIR"] / name).read_bytes())
                for name in ("pyproject.toml", "uv.lock")}
    if changed:
        with pytest.raises(AssertionError, match="metadata changed"):
            ns["_check_metadata"](backend, object(), verified)
    else:
        ns["_check_metadata"](backend, object(), verified)


@pytest.mark.parametrize("fault", [None, "success", "timeout", "missing", "truncated"])
def test_runtime_diagnostic_uses_fresh_delivery_and_actual_import_command(monkeypatch, fault) -> None:
    from unittest.mock import Mock

    from skillc.backend import ExecuteResult
    ns = _closure_namespace()
    backend = Mock()
    events = []
    def prepare(attempt):
        events.append("fresh")
        return object()
    backend.prepare.side_effect = prepare
    backend.deliver_home_file.side_effect = lambda *args: events.append("delivered")
    backend.runtime_environment.side_effect = lambda *args: events.append("validated-then-faulted")
    output = _UV_OFFLINE_CACHE_MISS.encode("utf-8")
    def run(handle, argv, limits):
        events.append("import")
        assert "--offline --locked --project" in argv[-1]
        assert "import pydantic; import yaml" in argv[-1]
        assert argv[-1].endswith("2>&1") and "dev/null" not in argv[-1]
        return ExecuteResult(reason="timeout" if fault == "timeout" else "exited",
                             exit_code=0 if fault == "success" else 1,
                             stdout=None if fault == "missing" else output,
                             stdout_truncated=fault == "truncated")
    backend.exec_in_attempt.side_effect = run
    tools = ({"id": "tool-pypi-runtime", "probes": [{"kind": "python-import", "modules": ["pydantic", "yaml"],
              "uv_project": "Projects/claude-power-pack"}]},)
    if fault:
        with pytest.raises(AssertionError):
            ns["_runtime_diagnostic"](backend, {"file": b"bytes"}, {"file": "digest"}, tools)
    else:
        assert ns["_runtime_diagnostic"](backend, {"file": b"bytes"}, {"file": "digest"}, tools) == output.decode()
    assert events == ["fresh", "delivered", "validated-then-faulted", "import"]
    backend.destroy.assert_called_once()


@pytest.mark.parametrize("mode", ["cache-sibling", "cache-link", "walk-error"])
def test_baseline_scan_cannot_hide_cache_neighbors_or_walk_errors(tmp_path, mode) -> None:
    import subprocess
    import sys
    ns = _closure_namespace()
    home, work = tmp_path / "home", tmp_path / "work"
    home.mkdir()
    work.mkdir()
    cache = home / ".cache"
    cache.mkdir()
    if mode == "cache-sibling":
        decoy = cache / "other" / "SKILL.md"
        decoy.parent.mkdir()
        decoy.write_text("decoy")
    elif mode == "cache-link":
        (cache / "uv").symlink_to(work, target_is_directory=True)
    script = ns["_BASELINE_SCAN"]
    if mode == "walk-error":
        script = ("from unittest.mock import patch\n" +
                  "with patch('os.scandir', side_effect=PermissionError('seeded unreadable subtree')):\n" +
                  "    exec(" + repr(script) + ")\n")
    result = subprocess.run([sys.executable, "-c", script, str(home), str(work)], capture_output=True, check=False)
    if mode == "cache-sibling":
        assert result.returncode == 0
        with pytest.raises(AssertionError, match="baseline"):
            ns["_check_baseline_scan"](result.stdout)
    else:
        assert result.returncode != 0


@pytest.mark.parametrize("frozen", [False, True])
def test_cold_preflight_uses_declared_environment_only_in_frozen_arm(monkeypatch, tmp_path, frozen) -> None:
    from skillc.backend import ExecuteResult
    ns = _closure_namespace()
    calls = []
    backend = ns["_RuntimeBackend"](image="image", base_dir=tmp_path, frozen_preflight=frozen)
    backend.frozen_env.update(HOME="/home/candidate")
    def execute(self, handle, argv, limits, cancel, stdin, cwd, env, confine_root):
        calls.append(env)
        return ExecuteResult(reason="exited", exit_code=0, stdout=b"report")
    monkeypatch.setattr(ns["d"].DockerBackend, "exec_in_attempt", execute)
    command = ["sh", "-c", "echo " + ns["at"]._TOOLS_MARKER]
    backend.exec_in_attempt(object(), command, ns["_LIVE_LIMITS"])
    assert calls == [dict(backend.frozen_env) if frozen else None]


@pytest.mark.parametrize("frozen", [False, True])
def test_actual_consuming_preflight_dispatches_cold_frozen_policy(monkeypatch, tmp_path, frozen) -> None:
    from skillc.backend import ExecuteResult
    ns = _closure_namespace()
    calls = []
    supply = ns["rs"].RuntimeSupply.from_path(_ROOT / "tests/fixtures/profile-trial-runtime/receipt.good.json")
    backend = ns["_RuntimeBackend"](image=supply.image_id, base_dir=tmp_path, runtime_supply=supply,
                                   witness_io=True, frozen_preflight=frozen)
    backend.frozen_env.update(HOME="/home/candidate", UV_OFFLINE="1", UV_LOCKED="1")
    def execute(self, handle, argv, limits, cancel, stdin, cwd, env, confine_root):
        assert "uv run --offline --locked --project" in argv[-1]
        assert "import json" in argv[-1]
        calls.append(env)
        return ExecuteResult(reason="exited", exit_code=0,
                             stdout=(ns["at"]._TOOLS_MARKER + "\nPROBE:0:IMPORT_OK\n").encode())
    monkeypatch.setattr(ns["d"].DockerBackend, "exec_in_attempt", execute)
    monkeypatch.setattr(ns["d"].DockerBackend, "export", lambda *args: None)
    tools = ({"id": "tool-pypi-runtime", "probes": [{"kind": "python-import", "modules": ["json"],
              "uv_project": "Projects/claude-power-pack"}]},)
    ns["at"]._preflight_in_container(backend, object(), ns["_LIVE_LIMITS"], {}, tools)
    assert calls == [dict(backend.frozen_env) if frozen else None]


def test_venv_permission_diagnostic_rejects_neighboring_path_prefix() -> None:
    ns = _closure_namespace()
    with pytest.raises(AssertionError):
        ns["_check_runtime_preflight"](
            True, "tool dependency 'tool-pypi-runtime' is not satisfied in the container",
            mode="project-venv-permissions",
            diagnostic="Permission denied: /home/candidate/Projects/claude-power-pack/.venv-neighbor",
        )
