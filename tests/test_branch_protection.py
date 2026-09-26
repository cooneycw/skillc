"""Branch protection drift check (#73), an operator tool never run in CI.

`good.json` is the REAL response captured from `gh api repos/cooneycw/skillc/
branches/main/protection` on 2026-09-26 (read-only GET; nothing was changed).
`bad.json` is a plausible drifted state (not strict, force-pushes allowed).
`test_a_different_expected_context_is_drift` is the specific negative control
the issue names: `--check` against a deliberately different expected context
must report drift, proving the comparison is not blind to the ONE thing most
likely to change (a renamed or added required check).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci import branch_protection as bp

CONTROLS = Path(__file__).resolve().parent.parent / "controls" / "branch-protection"


def _load(name: str) -> dict[str, object]:
    data = json.loads((CONTROLS / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_the_live_captured_response_matches_policy() -> None:
    assert bp.drift(_load("good.json")) == []


def test_the_drifted_response_is_caught() -> None:
    problems = bp.drift(_load("bad.json"))
    assert problems, "a non-strict, force-pushable state was not reported as drift"
    joined = " ".join(problems)
    assert "strict" in joined
    assert "allow_force_pushes" in joined


def test_a_different_expected_context_is_drift() -> None:
    """The issue's own committed negative control: --check against a
    deliberately different expected context must report drift."""
    good = _load("good.json")
    assert bp.drift(good) == []  # sanity: the real response is clean against the REAL policy
    problems = bp.drift(good, expected_contexts=["some-other-required-check"])
    assert problems, "a different expected context was not reported as drift"
    assert "contexts" in problems[0]


def test_missing_status_checks_key_is_drift() -> None:
    assert bp.drift({}) != []


def test_a_required_review_requirement_is_drift() -> None:
    good = _load("good.json")
    drifted = {**good, "required_pull_request_reviews": {"required_approving_review_count": 1}}
    assert any("required_pull_request_reviews" in p for p in bp.drift(drifted))


def test_restrictions_present_is_drift() -> None:
    good = _load("good.json")
    drifted = {**good, "restrictions": {"users": [], "teams": []}}
    assert any("restrictions" in p for p in bp.drift(drifted))


def test_apply_body_is_well_formed() -> None:
    """The PUT body must express what `drift`'s GET-shape check verifies -
    kept as one test so the two cannot silently disagree."""
    body = bp.APPLY_BODY
    assert body["required_status_checks"] == {"strict": True, "contexts": bp.EXPECTED_CONTEXTS}
    assert body["enforce_admins"] is False
    assert body["required_pull_request_reviews"] is None
    assert body["restrictions"] is None
    assert body["allow_force_pushes"] is False
    assert body["allow_deletions"] is False


def test_main_refuses_when_neither_or_both_flags_are_given() -> None:
    assert bp.main([]) == 2
    assert bp.main(["--check", "--apply"]) == 2


def test_an_unrecognized_flag_refuses_before_any_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cross-model review [MEDIUM]: `--apply --dry-run` used to silently ignore
    the unsupported `--dry-run` and perform the real write anyway. Confirmed
    real on the pre-fix code. `apply_protection` is monkeypatched to explode
    if reached at all - the assertion is "never called", not "called safely"."""

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("apply_protection() was called despite an unrecognized flag")

    monkeypatch.setattr(bp, "apply_protection", _boom)
    assert bp.main(["--apply", "--dry-run"]) == 2
