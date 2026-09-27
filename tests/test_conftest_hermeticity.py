"""Proves `conftest.py`'s `_no_real_credential_defaults` autouse fixture
actually does what it claims (issue #106/#117 review): every real standard
credential location is unreachable by default, for every client, in every
test - not merely in the ones that happen to monkeypatch it themselves.

The red case matters more than the green one here (CLAUDE.md's Negative
Control directive: an instrument that cannot fail is not evidence). A guard
that always reports "unreachable" regardless of what is actually on disk
would pass the green test below for the wrong reason - `test_the_guard_can_see_a_reachable_default`
proves this file's OWN checks can tell "unreachable" apart from "reachable"
by making one reachable on purpose and confirming `resolve_path` finds it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillc import credential as cred


def test_no_default_credential_is_reachable_for_any_client() -> None:
    """Under the autouse fixture (armed for every test in this suite,
    including this one - nothing here re-arms it), `resolve_path(client,
    explicit=None)` must refuse for every registered client. This is the
    exact call shape that read a real, live credential off the host running
    an earlier version of `tests/test_agent_trial.py` before this fixture
    existed."""
    for client in cred.CLIENT_SPECS:
        with pytest.raises(cred.CredentialRefused):
            cred.resolve_path(client, explicit=None)


def test_the_guard_can_see_a_reachable_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Red case: plant a real-looking credential at the STANDARD location
    and point `HOME` at it directly, undoing this one test's own copy of the
    fixture's redirect. `resolve_path` must find it - proving the check
    above is capable of seeing a reachable default at all, not merely
    incapable of ever raising anything else. This is what the autouse
    fixture prevents in every OTHER test: without it, exactly this shape is
    what let a real subscription credential resolve."""
    real_looking_home = tmp_path / "planted-home"
    standard = real_looking_home / ".claude" / ".credentials.json"
    standard.parent.mkdir(parents=True)
    standard.write_text("{}")
    monkeypatch.setattr(Path, "home", lambda: real_looking_home)
    monkeypatch.delenv("SKILLC_CLAUDE_CREDENTIAL", raising=False)

    assert cred.resolve_path("claude", explicit=None) == standard
