"""Tests for the `subject.profile` opt-in field (skillc#334, orchestrator
ruling mailbox 5820): a treated arm's subject may name a validated
profile to have its dependency closure installed, approval-bound to the
profile's committed inventory digest exactly as #323 binds
`attempts_per_arm`. Absent (every declaration before #334) is unchanged:
selected skill files only.

Uses the REAL committed `cpp-codex-flow-check-ea6dbfa` profile and its
committed `evidence/inventory.json` digest - the exact value
`test_profile_installed_home_files.py::test_inventory_digest_matches_the_committed_evidence_file`
also pins - rather than a synthetic stand-in, so a drift in either place
is caught by both.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from skillc import calibration, verify

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TASK = ROOT / "evals" / "level3" / "slugkit-pipeline"
GRADER = verify.GraderDef.load(TASK)
PROFILE_PATH = "evals/subjects/cpp-codex-flow-check-ea6dbfa"
COMMITTED_INVENTORY_DIGEST = "sha256:eb9cad6f8bb74c92fab4aa002bd6f2a55f3e8eb15ff25adcd582fea21071b1ab"

SUBJECT = {
    "name": "cpp-codex-flow-check-ea6dbfa",
    "locator": "github.com/cooneycw/claude-power-pack",
    "revision": "ea6dbfa45f9308ee6ba60f032d8e7031bd6938a1",
    "profile": PROFILE_PATH,
}


def _calibration_declaration(*, attempts_per_arm: int = 4, approval: dict[str, object] | None = None) -> dict[str, Any]:
    names = ["cpp", "baseline"]
    sequence = calibration.derive_arm_order(1, names, attempts_per_arm)
    return {
        "kind": "calibration-declaration",
        "arms": [
            {"name": "cpp", "subject": dict(SUBJECT), "treatment": "the validated profile closure installed"},
            {"name": "baseline", "subject": None, "treatment": "nothing installed"},
        ],
        "shared": {
            "client": {"name": "codex", "version": "0.157.1"},
            "model": "gpt-6-astra",
            "reasoning_effort": "high",
            "tools": "defaults",
            "permissions": "defaults",
            "public_requirements": "goal.md",
            "image": {"tag": "skillc-trial:latest", "digest": "sha256:" + "d" * 64},
            "per_attempt_seconds": 1200,
            "total_seconds": 1200 * attempts_per_arm * 2,
        },
        "attempts_per_arm": attempts_per_arm,
        "arm_order": {"seed": 1, "sequence": sequence},
        "task": {"path": "evals/level3/slugkit-pipeline", "grader_id": GRADER.id, "grader_revision": GRADER.revision},
        "retain_transcripts": True,
        "approval": approval,
    }


def _approved_calibration_declaration(
    *, attempts_per_arm: int = 4, profile_inventory_digest: str = COMMITTED_INVENTORY_DIGEST,
) -> dict[str, Any]:
    return _calibration_declaration(attempts_per_arm=attempts_per_arm, approval={
        "by": "owner (cooneycw)", "at": "2026-10-07", "attempts_per_arm": attempts_per_arm,
        "profile_inventory_digest": profile_inventory_digest,
    })


def test_a_subject_profile_field_parses() -> None:
    declaration = calibration.parse_declaration(_calibration_declaration())
    arms = declaration.data.get("arms")
    assert isinstance(arms, list)
    cpp_arm = next(a for a in arms if isinstance(a, dict) and a.get("name") == "cpp")
    assert cpp_arm["subject"]["profile"] == PROFILE_PATH


def test_an_empty_profile_string_is_refused() -> None:
    data = _calibration_declaration()
    data["arms"][0]["subject"]["profile"] = ""
    with pytest.raises(calibration.DeclarationRefused, match="profile must be a non-empty string"):
        calibration.parse_declaration(data)


def test_require_approved_succeeds_with_the_matching_committed_digest() -> None:
    declaration = calibration.parse_declaration(_approved_calibration_declaration())
    calibration.require_approved(declaration, ROOT)


def test_require_approved_refuses_a_missing_profile_inventory_digest() -> None:
    attempts = 4
    data = _calibration_declaration(attempts_per_arm=attempts, approval={
        "by": "owner (cooneycw)", "at": "2026-10-07", "attempts_per_arm": attempts,
    })
    declaration = calibration.parse_declaration(data)
    with pytest.raises(calibration.DeclarationRefused, match="profile_inventory_digest"):
        calibration.require_approved(declaration, ROOT)


def test_red_case_a_stale_profile_inventory_digest_is_refused() -> None:
    """Mutation check: the approval names a digest that is NOT the
    committed evidence's real digest - must refuse, naming both values."""
    declaration = calibration.parse_declaration(
        _approved_calibration_declaration(profile_inventory_digest="sha256:" + "0" * 64)
    )
    with pytest.raises(calibration.DeclarationRefused, match="approved for profile_inventory_digest"):
        calibration.require_approved(declaration, ROOT)


def test_a_subject_with_no_profile_field_is_unaffected() -> None:
    """Today's behavior (every declaration before #334): no profile named,
    no profile_inventory_digest required."""
    attempts = 4
    data = _calibration_declaration(attempts_per_arm=attempts)
    del data["arms"][0]["subject"]["profile"]
    data["approval"] = {"by": "owner (cooneycw)", "at": "2026-10-07", "attempts_per_arm": attempts}
    declaration = calibration.parse_declaration(data)
    calibration.require_approved(declaration, ROOT)  # does not raise over the missing profile digest


# --------------------------------------------------- discrimination-declaration


def _discrimination_declaration(
    *, attempts_per_arm: int = 4, approval: dict[str, object] | None = None,
) -> dict[str, Any]:
    names = list(calibration.DISCRIMINATION_ARMS)
    sequence = calibration.derive_arm_order(2, names, attempts_per_arm)
    intact_subject = dict(SUBJECT)
    degraded_revision = calibration._expected_degraded_revision(intact_subject)
    return {
        "kind": "discrimination-declaration",
        "arms": [
            {"name": "intact", "subject": dict(intact_subject)},
            {
                "name": "degraded",
                "subject": {**intact_subject, "revision": degraded_revision},
                "mutation": {
                    "skill": "flow-check", "path": "reference.md", "removed_text": "x",
                    "diagnose_evidence": "diagnose run", "mutated_digest": "sha256:" + "a" * 64,
                },
            },
        ],
        "shared": {
            "client": {"name": "codex", "version": "0.157.1"},
            "model": "gpt-6-astra",
            "reasoning_effort": "high",
            "tools": "defaults",
            "permissions": "defaults",
            "public_requirements": "goal.md",
            "image": {"tag": "skillc-trial:latest", "digest": "sha256:" + "d" * 64},
            "per_attempt_seconds": 1200,
            "total_seconds": 1200 * attempts_per_arm * 2,
        },
        "attempts_per_arm": attempts_per_arm,
        "arm_order": {"seed": 2, "sequence": sequence},
        "task": {"path": "evals/level3/slugkit-pipeline", "grader_id": GRADER.id, "grader_revision": GRADER.revision},
        "retain_transcripts": True,
        "tolerance": {"non_evaluable_per_arm": 1},
        "approval": approval,
    }


def _approved_discrimination_declaration(
    *, attempts_per_arm: int = 4, profile_inventory_digest: str = COMMITTED_INVENTORY_DIGEST,
) -> dict[str, Any]:
    return _discrimination_declaration(attempts_per_arm=attempts_per_arm, approval={
        "by": "owner (cooneycw)", "at": "2026-10-07", "attempts_per_arm": attempts_per_arm,
        "mutated_digest": "sha256:" + "a" * 64, "profile_inventory_digest": profile_inventory_digest,
    })


def test_discrimination_subject_profile_field_parses_and_both_arms_match() -> None:
    declaration = calibration.parse_discrimination_declaration(_discrimination_declaration())
    assert declaration.intact_subject["profile"] == PROFILE_PATH
    assert declaration.degraded_subject["profile"] == PROFILE_PATH


def test_discrimination_require_approved_succeeds_with_the_matching_committed_digest() -> None:
    declaration = calibration.parse_discrimination_declaration(_approved_discrimination_declaration())
    calibration.require_approved_discrimination(declaration, ROOT)


def test_red_case_discrimination_a_stale_profile_inventory_digest_is_refused() -> None:
    declaration = calibration.parse_discrimination_declaration(
        _approved_discrimination_declaration(profile_inventory_digest="sha256:" + "1" * 64)
    )
    with pytest.raises(calibration.DeclarationRefused, match="approved for profile_inventory_digest"):
        calibration.require_approved_discrimination(declaration, ROOT)


def test_red_case_a_degraded_arm_naming_a_different_profile_is_refused() -> None:
    """Not a new check - the existing subject set-equality check (#333)
    already covers this, since `profile` is just another subject key. A
    dedicated test naming `profile` specifically, so a future change to
    that equality check's scope is caught here too, not only incidentally."""
    data = _discrimination_declaration()
    data["arms"][1]["subject"]["profile"] = "evals/subjects/cpp-codex-flow-check"
    with pytest.raises(calibration.DeclarationRefused, match="a different subject"):
        calibration.parse_discrimination_declaration(data)
