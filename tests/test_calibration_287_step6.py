"""#287 step-6 redesign: the variant task and its two declarations.

The variant must be the qualified gate-stops-early task with ONLY its prompt
changed, so the grader certification carries over. That is pinned by the
grader's own digest and the task-surface digest, not by reading the files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillc import calibration, trial, verify
from skillc import collection_conformance as cc

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = ROOT / "evals/level3/gate-stops-early"
VARIANT = ROOT / "evals/level3/gate-stops-early-step6"
PRECHECK = ROOT / "evals/calibration-287/precheck-step6-declaration.json"
FULL = ROOT / "evals/calibration-287/pilot-discrimination-step6-declaration.json"
PRECHECK_DIGEST = "sha256:ab45fef07f6c9ab5cda4c3f4638ccce32a012e2a99b9f0d0fe8bafdd0bcd107d"
FULL_DIGEST = "sha256:27aefafee336186289d448696f990e3ba3f5a16bda078148d40041499bb87ef5"


def _fixture_digest(task: Path) -> str:
    files = cc.task_surface(task / "discrimination/fixture")
    return trial.sha256_bytes(trial.canonical([[p, x, trial.sha256_bytes(b)] for p, b, x in files]))


def test_the_variant_grader_is_byte_identical_to_the_qualified_task() -> None:
    original, variant = verify.GraderDef.load(ORIGINAL), verify.GraderDef.load(VARIANT)
    assert (variant.id, variant.revision) == (original.id, original.revision) == ("gate-stops-early", "5")
    assert variant.digest() == original.digest()


def test_the_variant_fixture_is_byte_identical_to_the_qualified_task() -> None:
    assert _fixture_digest(VARIANT) == _fixture_digest(ORIGINAL)


def test_the_variant_prompt_differs_only_in_its_finish_paragraph() -> None:
    original = (ORIGINAL / "goal.md").read_text(encoding="utf-8")
    variant = (VARIANT / "goal.md").read_text(encoding="utf-8")
    assert "do not infer" in original and "do not infer" not in variant
    assert "installed `flow-check` skill" in variant and "check summary" in variant
    head = original.split("You may add or change other files")[0]
    assert variant.startswith(head), "everything before the finish paragraph is unchanged"


def test_a_changed_variant_grader_would_be_caught(tmp_path: Path) -> None:
    """The digest equality above can fail: one byte in the judge moves it."""
    import shutil
    copy = tmp_path / "variant"
    shutil.copytree(VARIANT, copy)
    judge = copy / "grade_gate_stops_early.py"
    judge.write_bytes(judge.read_bytes() + b"\n")
    assert verify.GraderDef.load(copy).digest() != verify.GraderDef.load(ORIGINAL).digest()


@pytest.mark.parametrize("path, digest, n", [(PRECHECK, PRECHECK_DIGEST, 1), (FULL, FULL_DIGEST, 10)],
                         ids=["precheck", "full"])
def test_the_step6_declarations_name_the_variant_and_pass_the_p3_checks(path: Path, digest: str, n: int) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert calibration.declaration_digest(data) == digest
    assert data["task"]["path"] == "evals/level3/gate-stops-early-step6" and data["attempts_per_arm"] == n
    declaration = calibration.parse_discrimination_declaration(data)
    assert len(declaration.arm_order) == 2 * n


def test_the_precheck_carries_the_owners_preapproval_and_authorizes() -> None:
    data = json.loads(PRECHECK.read_text(encoding="utf-8"))
    assert "you can run it (approving in advance)" in data["approval"]["source"]
    assert data["approval"]["declaration_digest"] == PRECHECK_DIGEST
    calibration.require_approved_discrimination(calibration.parse_discrimination_declaration(data), ROOT)


def test_the_full_pilot_is_committed_unapproved() -> None:
    """Its approval is conditional on the pre-check, so it is stamped only after
    the condition passes, never in advance."""
    data = json.loads(FULL.read_text(encoding="utf-8"))
    assert data["approval"] is None
    with pytest.raises(calibration.DeclarationRefused):
        calibration.require_approved_discrimination(calibration.parse_discrimination_declaration(data), ROOT)
