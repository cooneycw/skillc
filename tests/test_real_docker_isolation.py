"""Tests for `ci/real_docker_isolation.py` (#315, R6 + B2's tri-state
correction): the preflight isolation DETECTOR's pure classifier. Covers
every meaningful combination of the three inputs, plus the mutation checks
the orchestrator review explicitly required."""

from __future__ import annotations

import pytest

from ci import real_docker_isolation as iso


def test_lan_reachable_by_successful_connect_refuses() -> None:
    result = iso.classify(lan_probe=iso.REACHABLE, lan_configured=True, github_probe=iso.REACHABLE)
    assert result.status == iso.REFUSED
    assert "reachable" in result.reason


def test_lan_connection_refused_also_refuses() -> None:
    """B2: a connection REFUSED still proves a host answered at that
    address - the probe script reports this as REACHABLE (not UNREACHABLE,
    and not an error), and the classifier must refuse on it exactly as it
    would for a fully successful connection."""
    result = iso.classify(lan_probe=iso.REACHABLE, lan_configured=True, github_probe=iso.REACHABLE)
    assert result.status == iso.REFUSED


def test_lan_unconfigured_refuses_even_if_everything_else_looks_fine() -> None:
    result = iso.classify(lan_probe=iso.UNREACHABLE, lan_configured=False, github_probe=iso.REACHABLE)
    assert result.status == iso.REFUSED
    assert "unconfigured" in result.reason


def test_lan_probe_error_refuses() -> None:
    """B2's central new case: the LAN probe itself failing to run (missing
    tool, throwaway container never started) must REFUSE, never be
    silently treated as 'unreachable' (which is what the old boolean
    design's `|| echo unreachable` fallback effectively did)."""
    result = iso.classify(lan_probe=iso.PROBE_ERROR, lan_configured=True, github_probe=iso.REACHABLE)
    assert result.status == iso.REFUSED
    assert "could not run" in result.reason


def test_github_probe_error_refuses() -> None:
    result = iso.classify(lan_probe=iso.UNREACHABLE, lan_configured=True, github_probe=iso.PROBE_ERROR)
    assert result.status == iso.REFUSED
    assert "could not run" in result.reason


def test_github_unreachable_refuses() -> None:
    result = iso.classify(lan_probe=iso.UNREACHABLE, lan_configured=True, github_probe=iso.UNREACHABLE)
    assert result.status == iso.REFUSED
    assert "positive control" in result.reason


def test_only_lan_unreachable_plus_github_reachable_proceeds() -> None:
    result = iso.classify(lan_probe=iso.UNREACHABLE, lan_configured=True, github_probe=iso.REACHABLE)
    assert result.status == iso.PROCEED


def test_an_invalid_probe_value_is_rejected_outright() -> None:
    """Never silently coerced - a typo'd probe result string must raise,
    not be treated as some default state."""
    with pytest.raises(ValueError, match="lan_probe"):
        iso.classify(lan_probe="maybe", lan_configured=True, github_probe=iso.REACHABLE)
    with pytest.raises(ValueError, match="github_probe"):
        iso.classify(lan_probe=iso.UNREACHABLE, lan_configured=True, github_probe="maybe")


def test_red_case_a_classifier_that_ignores_the_lan_probe_must_fail_a_case() -> None:
    """Mutation check (R6's explicit requirement): a classifier that never
    reads `lan_probe` at all - treating configuration and GitHub
    reachability as the whole story - would wrongly PROCEED when the LAN
    is actually reachable. Proves this suite would catch that mistake."""

    def ignores_lan_probe(*, lan_probe: str, lan_configured: bool, github_probe: str) -> str:
        del lan_probe  # the planted defect: never consulted
        if not lan_configured:
            return iso.REFUSED
        if github_probe != iso.REACHABLE:
            return iso.REFUSED
        return iso.PROCEED

    correct = iso.classify(lan_probe=iso.REACHABLE, lan_configured=True, github_probe=iso.REACHABLE).status
    mutated = ignores_lan_probe(lan_probe=iso.REACHABLE, lan_configured=True, github_probe=iso.REACHABLE)
    assert correct == iso.REFUSED
    assert mutated != correct, "the LAN-blind mutation accidentally agrees - this red case is inert"


def test_red_case_b2_folding_probe_error_into_unreachable_would_miss_this() -> None:
    """Mutation check for B2 specifically: the OLD design's
    `|| echo unreachable` fallback folded 'the probe could not run' into
    the SAME value as 'the probe ran and found nothing' - which would
    wrongly PROCEED on a LAN probe that never actually executed. Proves
    the tri-state distinction is load-bearing, not cosmetic."""

    def folds_error_into_unreachable(*, lan_probe: str, lan_configured: bool, github_probe: str) -> str:
        # The planted defect: PROBE_ERROR is treated exactly like UNREACHABLE.
        lan_ok = lan_probe != iso.REACHABLE
        github_ok = github_probe == iso.REACHABLE or github_probe == iso.PROBE_ERROR
        if not lan_configured:
            return iso.REFUSED
        if not lan_ok:
            return iso.REFUSED
        if not github_ok:
            return iso.REFUSED
        return iso.PROCEED

    correct = iso.classify(lan_probe=iso.PROBE_ERROR, lan_configured=True, github_probe=iso.REACHABLE).status
    mutated = folds_error_into_unreachable(lan_probe=iso.PROBE_ERROR, lan_configured=True, github_probe=iso.REACHABLE)
    assert correct == iso.REFUSED
    assert mutated != correct, "the error-folding mutation accidentally agrees - this red case is inert"
