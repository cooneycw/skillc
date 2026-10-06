"""Tests for the discrimination-declaration kind (skillc#287, orchestrator
ruling 2026-10-06, mailbox message 5614/5626).

`skillc.calibration.parse_declaration` cannot express an intact-vs-degraded
contrast: it requires exactly one arm literally named 'baseline' with a null
subject, and a 3-arm declaration's two treated arms must share an IDENTICAL
subject, which a degraded arm's revision never does. This kind is the
orchestrator-approved resolution - a sibling parser, reusing `parse_
declaration`'s own shared/attempts/arm_order/task machinery rather than
copying it, never changing `parse_declaration`'s own behavior for
'calibration-declaration'.

The committed red cases: an extra subject difference between the two arms;
a hand-typed (not derived) degraded revision label; a missing
diagnose_evidence; an approval at the wrong attempts_per_arm; and the
mailbox ruling's own named case - the SAME file with a DIFFERENT
removed_text (hence a different real degraded file) carrying the SAME
approval, refused through the mutated_digest mismatch rather than through
the revision label, which is content-independent (verified directly: two
edits of the same file with different content produce an identical derived
revision - see `test_the_derived_revision_label_does_not_depend_on_edit_content`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from skillc import calibration, degrade, verify
from skillc import materialize as m

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TASK = ROOT / "evals" / "level3" / "slugkit-pipeline"
GRADER = verify.GraderDef.load(TASK)

INTACT_SUBJECT = {
    "name": "cpp-codex-flow-check-ea6dbfa",
    "locator": "github.com/cooneycw/claude-power-pack",
    "revision": "ea6dbfa45f9308ee6ba60f032d8e7031bd6938a1",
}
DERIVED_REVISION = calibration._expected_degraded_revision(INTACT_SUBJECT)
MUTATED_DIGEST = "sha256:" + "a" * 64
OTHER_MUTATED_DIGEST = "sha256:" + "b" * 64


def _declaration(*, attempts_per_arm: int = 10, seed: int = 20261006, approval: dict[str, object] | None = None,
                  mutated_digest: str = MUTATED_DIGEST) -> dict[str, Any]:
    sequence = calibration.derive_arm_order(seed, list(calibration.DISCRIMINATION_ARMS), attempts_per_arm)
    return {
        "kind": "discrimination-declaration",
        "arms": [
            {"name": "intact", "subject": dict(INTACT_SUBJECT)},
            {
                "name": "degraded",
                "subject": {**INTACT_SUBJECT, "revision": DERIVED_REVISION},
                "mutation": {
                    "skill": "flow-check",
                    "path": "reference.md",
                    "removed_text": "A `skipped gates:` name is a SKIP row ... never a PASS.",
                    "diagnose_evidence": "skillc profile diagnose run 2026-10-06, 0 problems",
                    "mutated_digest": mutated_digest,
                },
            },
        ],
        "shared": {
            "client": {"name": "codex", "version": "0.157.1"},
            "model": "gpt-6-astra",
            "reasoning_effort": "high",
            "tools": "the client's defaults inside the trial container; no MCP servers",
            "permissions": "the same non-interactive sandbox/approval settings for every attempt",
            "public_requirements": "evals/level3/slugkit-pipeline/goal.md, delivered verbatim to both arms",
            "image": {"tag": "skillc-trial:latest", "digest": "sha256:" + "d" * 64},
            "per_attempt_seconds": 1200,
            "total_seconds": 1200 * attempts_per_arm * 2,
        },
        "attempts_per_arm": attempts_per_arm,
        "arm_order": {"seed": seed, "sequence": sequence},
        "task": {"path": "evals/level3/slugkit-pipeline", "grader_id": GRADER.id, "grader_revision": GRADER.revision},
        "retain_transcripts": True,
        "tolerance": {"non_evaluable_per_arm": 1},
        "approval": approval,
    }


def _approved(*, attempts_per_arm: int = 10, mutated_digest: str = MUTATED_DIGEST) -> dict[str, Any]:
    return _declaration(attempts_per_arm=attempts_per_arm, mutated_digest=mutated_digest, approval={
        "by": "owner (cooneycw)", "at": "2026-10-06", "attempts_per_arm": attempts_per_arm,
        "mutated_digest": mutated_digest,
    })


def test_a_well_formed_declaration_parses() -> None:
    declaration = calibration.parse_discrimination_declaration(_declaration())
    assert declaration.attempts_per_arm == 10
    assert declaration.intact_subject["revision"] == INTACT_SUBJECT["revision"]
    assert declaration.degraded_subject["revision"] == DERIVED_REVISION
    assert declaration.tolerance_non_evaluable_per_arm == 1


def test_an_approved_declaration_authorizes() -> None:
    calibration.require_approved_discrimination(calibration.parse_discrimination_declaration(_approved()), ROOT)


def test_wrong_kind_is_refused() -> None:
    data = _declaration()
    data["kind"] = "calibration-declaration"
    with pytest.raises(calibration.DeclarationRefused, match="kind is"):
        calibration.parse_discrimination_declaration(data)


def test_arms_must_be_named_exactly_intact_and_degraded() -> None:
    data = _declaration()
    data["arms"][0]["name"] = "baseline"
    with pytest.raises(calibration.DeclarationRefused, match="arms must be named exactly"):
        calibration.parse_discrimination_declaration(data)


# --------------------------------------------------- red case: extra subject difference


def test_red_case_a_different_subject_name_is_refused() -> None:
    data = _declaration()
    data["arms"][1]["subject"]["name"] = "a-different-subject"
    with pytest.raises(calibration.DeclarationRefused, match="a different subject"):
        calibration.parse_discrimination_declaration(data)


def test_red_case_a_different_subject_locator_is_refused() -> None:
    data = _declaration()
    data["arms"][1]["subject"]["locator"] = "github.com/someone-else/other-repo"
    with pytest.raises(calibration.DeclarationRefused, match="a different subject"):
        calibration.parse_discrimination_declaration(data)


# --------------------------------------------------- red case: hand-typed revision label


def test_red_case_a_hand_typed_degraded_revision_is_refused() -> None:
    data = _declaration()
    data["arms"][1]["subject"]["revision"] = "degraded:just-trust-me"
    with pytest.raises(calibration.DeclarationRefused, match="not the derived"):
        calibration.parse_discrimination_declaration(data)


def test_the_derived_revision_label_does_not_depend_on_edit_content() -> None:
    """Why `mutated_digest` exists at all: the label alone cannot tell two
    different removals of the same file apart. Verified directly against
    `degrade.py`'s own function, not assumed."""
    base = m.Source(kind="git", locator="x", revision="a" * 40, surface_dir=Path("."), digest="", origin=Path("."))
    first = degrade._degraded_revision(base, degrade.Mutation(edits=(degrade.FileEdit("s", "p", content=b"one"),)))
    second = degrade._degraded_revision(base, degrade.Mutation(edits=(degrade.FileEdit("s", "p", content=b"two"),)))
    assert first == second


# --------------------------------------------------- red case: missing diagnose_evidence


def test_red_case_a_missing_diagnose_evidence_is_refused() -> None:
    data = _declaration()
    del data["arms"][1]["mutation"]["diagnose_evidence"]
    with pytest.raises(calibration.DeclarationRefused, match="mutation"):
        calibration.parse_discrimination_declaration(data)


def test_red_case_an_empty_diagnose_evidence_is_refused() -> None:
    data = _declaration()
    data["arms"][1]["mutation"]["diagnose_evidence"] = ""
    with pytest.raises(calibration.DeclarationRefused, match="mutation"):
        calibration.parse_discrimination_declaration(data)


def test_a_malformed_mutated_digest_is_refused_at_parse_time() -> None:
    data = _declaration()
    data["arms"][1]["mutation"]["mutated_digest"] = "not-a-digest"
    with pytest.raises(calibration.DeclarationRefused, match="mutated_digest"):
        calibration.parse_discrimination_declaration(data)


# --------------------------------------------------- red case: approval at the wrong size


def test_red_case_approval_at_the_wrong_attempts_per_arm_is_refused() -> None:
    data = _approved(attempts_per_arm=10)
    data["attempts_per_arm"] = 15
    data["arm_order"] = {
        "seed": 20261006,
        "sequence": calibration.derive_arm_order(20261006, list(calibration.DISCRIMINATION_ARMS), 15),
    }
    data["shared"]["total_seconds"] = 1200 * 15 * 2
    declaration = calibration.parse_discrimination_declaration(data)
    with pytest.raises(calibration.DeclarationRefused, match="approved for attempts_per_arm"):
        calibration.require_approved_discrimination(declaration, ROOT)


# --------------------------------------------- red case: same file, different removed_text, same approval


def test_red_case_a_changed_removed_text_with_a_stale_approval_is_refused_through_the_digest() -> None:
    """The mailbox ruling's own named red case (message 5626): the same
    file, a DIFFERENT removed_text (hence a different real degraded file),
    under an approval that still names the OLD mutated_digest. The revision
    label cannot catch this (previous test) - the digest binding must."""
    approved_digest = MUTATED_DIGEST
    data = _approved(mutated_digest=approved_digest)
    # Someone edits removed_text and recomputes mutated_digest honestly for
    # the NEW degraded file, but does not get a fresh approval.
    data["arms"][1]["mutation"]["removed_text"] = "a completely different sentence was removed instead"
    data["arms"][1]["mutation"]["mutated_digest"] = OTHER_MUTATED_DIGEST
    assert data["approval"]["mutated_digest"] == approved_digest  # unchanged - the stale approval
    declaration = calibration.parse_discrimination_declaration(data)
    with pytest.raises(calibration.DeclarationRefused, match="approved for mutation.mutated_digest"):
        calibration.require_approved_discrimination(declaration, ROOT)


# --------------------------------------------------- reused-helper regression guard


def test_derive_arm_order_is_reused_not_copied() -> None:
    """P6: the arm order is calibration's seed-derived interleaving. A
    sequence not matching what the seed derives is refused exactly as a
    calibration-declaration's would be."""
    data = _declaration()
    data["arm_order"]["sequence"] = list(reversed(data["arm_order"]["sequence"]))
    with pytest.raises(calibration.DeclarationRefused, match="an order chosen by hand"):
        calibration.parse_discrimination_declaration(data)


def test_tolerance_must_be_a_positive_integer() -> None:
    data = _declaration()
    data["tolerance"]["non_evaluable_per_arm"] = 0
    with pytest.raises(calibration.DeclarationRefused, match="tolerance.non_evaluable_per_arm"):
        calibration.parse_discrimination_declaration(data)


def test_calibration_declaration_parsing_is_unaffected_by_the_refactor() -> None:
    """The extraction (`_parse_schedule_and_identities`) must not change
    `parse_declaration`'s own behavior for its existing kind - loaded here
    from the real, previously-approved #204 manifest."""
    declaration = calibration.load_declaration(ROOT / "evals" / "calibration-204" / "run-manifest.json")
    calibration.require_approved(declaration, ROOT)
