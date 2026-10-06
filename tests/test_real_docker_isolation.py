"""Tests for `ci/real_docker_isolation.py` (#315, R6): the preflight
isolation DETECTOR's pure classifier. Covers all four meaningful
combinations of the three probe inputs, plus a mutation check proving a
classifier that ignores the LAN probe would miss a real case."""

from __future__ import annotations

from ci import real_docker_isolation as iso


def test_lan_reachable_refuses() -> None:
    result = iso.classify(lan_reachable=True, lan_configured=True, github_reachable=True)
    assert result.status == iso.REFUSED
    assert "reachable" in result.reason


def test_lan_unconfigured_refuses_even_if_everything_else_looks_fine() -> None:
    result = iso.classify(lan_reachable=False, lan_configured=False, github_reachable=True)
    assert result.status == iso.REFUSED
    assert "unconfigured" in result.reason


def test_github_unreachable_refuses() -> None:
    result = iso.classify(lan_reachable=False, lan_configured=True, github_reachable=False)
    assert result.status == iso.REFUSED
    assert "positive control" in result.reason


def test_only_lan_unreachable_plus_github_reachable_proceeds() -> None:
    result = iso.classify(lan_reachable=False, lan_configured=True, github_reachable=True)
    assert result.status == iso.PROCEED


def test_red_case_a_classifier_that_ignores_the_lan_probe_must_fail_a_case() -> None:
    """Mutation check (R6's explicit requirement): a classifier that never
    reads `lan_reachable` at all - treating configuration and GitHub
    reachability as the whole story - would wrongly PROCEED when the LAN
    is actually reachable. Proves this suite would catch that mistake."""

    def ignores_lan_probe(*, lan_reachable: bool, lan_configured: bool, github_reachable: bool) -> str:
        del lan_reachable  # the planted defect: never consulted
        if not lan_configured:
            return iso.REFUSED
        if not github_reachable:
            return iso.REFUSED
        return iso.PROCEED

    correct = iso.classify(lan_reachable=True, lan_configured=True, github_reachable=True).status
    mutated = ignores_lan_probe(lan_reachable=True, lan_configured=True, github_reachable=True)
    assert correct == iso.REFUSED
    assert mutated != correct, "the LAN-blind mutation accidentally agrees - this red case is inert"
