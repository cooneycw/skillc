"""Issue #219: a committed regression for `tests/conftest.py`'s
`_no_quarantine_leaks_across_tests` autouse fixture.

These two tests must run in this file's own definition order - no
randomization plugin is installed in this project (checked:
`pyproject.toml` declares none, and no `conftest.py` reorders collection) -
so the first test's leftover quarantine is exactly what the second would
inherit, were it not for the fixture under test.
"""

from __future__ import annotations

from skillc import verify


def test_a_quarantine_set_here_does_not_survive_this_test() -> None:
    """Simulates the real trigger (a lost backend probe/teardown
    confirmation, `tests/test_verify_backend.py`'s own tests) directly on the
    module flag, without driving the full backend machinery - this fixture's
    job is to reset the flag, not to re-prove how it gets set."""
    verify._set_quarantine("issue #219 regression: simulated containment loss")
    assert verify._quarantine is not None


def test_the_next_test_starts_with_no_quarantine() -> None:
    """Without `tests/conftest.py`'s autouse fixture, this test inherits the
    previous test's quarantine and fails here - the #219 cascade, reproduced
    with two tests instead of the eighteen main pipeline 482 lost."""
    assert verify._quarantine is None
