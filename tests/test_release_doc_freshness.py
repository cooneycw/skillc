"""Committed stale-document cases from #554; current pages must retire them."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STALE_CASES = [
    ("AGENTS.md", "#26 remains open"),
    ("evals/README.md", "#26 remains open"),
    ("evals/README.md", "No existing fixture admits it"),
    ("README.md", "Also in this cycle, still open:"),
    ("README.md", "23/23 rule(s) discriminate"),
    ("README.md", "no agent has attempted either yet"),
    ("README.md", "neither level has run through a live agent yet"),
    ("AGENTS.md", "no live attempt has run"),
    ("AGENTS.md", "(not approved, not run)"),
    ("AGENTS.md", "(receipt, ledger, manifest, result, attempt lifecycle)"),
    ("PLAN.md", "runtime capability not implemented"),
    ("evals/README.md", "no live attempt has run"),
    ("evals/README.md", "No behavioral runner is implemented here yet"),
    ("skillc/verify.py", "No concrete backend ships"),
    ("docs/specs/evaluation-facility/verification.md", "No concrete backend exists"),
    ("skillc/fixture_live.py", "graded by grader revision 2"),
    ("evals/subjects/cpp-codex-flow-check-ea6dbfa/PROFILE.md", "remains #237's own path"),
]


def stale_claim(text: str, claim: str) -> bool:
    return claim in " ".join(text.split())


@pytest.mark.parametrize(("path", "claim"), STALE_CASES)
def test_retired_claim_is_absent(path: str, claim: str) -> None:
    assert not stale_claim((ROOT / path).read_text(), claim)


@pytest.mark.parametrize(("path", "claim"), STALE_CASES)
def test_committed_stale_claim_is_detected(path: str, claim: str) -> None:
    """Known bad input uses the same predicate as the real-page check."""
    assert stale_claim(f"Page introduction.\n{claim}\nOther text.", claim)


@pytest.mark.parametrize("path", ["evals/calibration-203/report.md", "evals/calibration-203-low/README.md"])
def test_calibration_reports_explain_install_constraint(path: str) -> None:
    text = (ROOT / path).read_text()
    assert "#393" in text and "tests/unit/__init__.py" in text


def test_provenance_annotates_historical_not_run_claim() -> None:
    text = (ROOT / "evals/level3/gate-stops-early/PROVENANCE.md").read_text()
    original_paragraph = text.split("Two runner mechanisms", 1)[1].split("`reference.md`'s own Step 6", 1)[0]
    assert "pending" in original_paragraph and "Revision 5" in original_paragraph


def test_frozen_profile_has_an_adjacent_current_network_policy_correction() -> None:
    from skillc.collection_conformance import AGENT_NETWORK_POLICY

    text = (ROOT / "evals/subjects/cpp-codex-flow-check-ea6dbfa/PROFILE.md").read_text()
    assert AGENT_NETWORK_POLICY in text
    assert "profile_digest" in text and "network:none" in text
