"""The committed negative control for issue #336's dedicated-exception
fix (`_PropertyHeld`/`_require`, applied to `tests/test_decide_reply_
channel_live.py` and `tests/test_gate_witness_live.py`, matching
`tests/test_gate_overlay_live.py`'s own #332 precedent).

The claim under test is purely about PYTEST'S OWN MECHANICS, not about
any one file's specific `_PropertyHeld` class: does `@pytest.mark.xfail
(strict=True, raises=X)` actually distinguish "the function raised X"
from "the function raised some OTHER exception" - the property the
whole fix exists to establish. Demonstrated with the `pytester` fixture
(opt-in - `pytest_plugins = ["pytester"]` below), which runs a REAL,
separate pytest subprocess against a tiny generated test file and reads
THAT run's own reported outcomes. This is a committed test, not a
throwaway script run once in a session (orchestrator direction, issue
#336): a future edit that weakens the pattern - in either live file, or
in a new one copying it - has no committed instrument here to catch it,
but THIS file's own claim (that the mechanism itself discriminates) is
pinned so it cannot silently stop being true for pytest's own reasons
(a pytest upgrade changing `xfail`'s semantics, say).

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
