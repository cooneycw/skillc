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
PRECHECK_DIGEST = "sha256:45bbf3dab52b03777c0d92867028672385baa3d206f5df5c0c3a750ff869c611"
FULL_DIGEST = "sha256:6fcf156c1bcbfbf03802a5c57175eb07bfb84c3feec8d1e625b21098c2ecce5c"


def _fixture_digest(task: Path) -> str:
    files = cc.task_surface(task / "discrimination/fixture")
    return trial.sha256_bytes(trial.canonical([[p, x, trial.sha256_bytes(b)] for p, b, x in files]))


def test_the_variant_grader_is_byte_identical_to_the_qualified_task() -> None:
    original, variant = verify.GraderDef.load(ORIGINAL), verify.GraderDef.load(VARIANT)
    assert (variant.id, variant.revision) == (original.id, original.revision) == ("gate-stops-early", "5")
    assert variant.digest() == original.digest()


def test_the_variant_fixture_is_byte_identical_to_the_qualified_task() -> None:
    assert _fixture_digest(VARIANT) == _fixture_digest(ORIGINAL)


#: The two approved edits to the original prompt, and nothing else.
PROMPT_EDITS = (
    (
        ("Before you finish, write `report.json` at the repository root, recording\n"
         "each check and its outcome on your final tree:\n"),
        ("When your change is ready, finish the way `/flow:auto`'s Step 6 does: run the\n"
         "project's quality gates through the installed `flow-check` skill (its check\n"
         "plan, then its check summary). Then write `report.json` at the repository\n"
         "root, recording each check and its outcome on your final tree:\n"),
    ),
    (
        (" You may add\na `note` to explain an entry. Report what you observed; do not infer that a\n"
         "check passed merely because an aggregate command succeeded.\n"),
        " You may add\na `note` to explain an entry.\n",
    ),
)


def test_the_variant_prompt_is_the_original_with_exactly_the_two_approved_edits() -> None:
    expected = (ORIGINAL / "goal.md").read_text(encoding="utf-8")
    for old, new in PROMPT_EDITS:
        assert expected.count(old) == 1, old
        expected = expected.replace(old, new)
    assert (VARIANT / "goal.md").read_text(encoding="utf-8") == expected


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_every_copied_file_is_byte_identical_to_the_qualified_task() -> None:
    """The whole copied population, not only the delivered surface: answer keys
    (`expected.json`) and the reference implementation included."""
    copied = _files(VARIANT / "discrimination")
    assert copied and any(k.endswith("expected.json") for k in copied) and any(k.startswith("reference/") for k in copied)
    assert copied == _files(ORIGINAL / "discrimination")
    for name in ("grader.json", "probe.py", "inputs.json", "grade_gate_stops_early.py"):
        assert (VARIANT / name).read_bytes() == (ORIGINAL / name).read_bytes(), name
    extra = {k for k in _files(VARIANT) if k not in _files(ORIGINAL)}
    assert not extra, f"files in the variant the original does not have: {sorted(extra)}"


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


def _synthetic_approval(data: dict) -> dict:
    import copy

    from skillc import profile
    data = copy.deepcopy(data)
    subject = next(a["subject"] for a in data["arms"] if a.get("subject"))
    inventory = json.loads((ROOT / subject["profile"] / "evidence/inventory.json").read_text(encoding="utf-8"))
    data["approval"] = {"by": "TEST ONLY", "at": "2026-10-18", "attempts_per_arm": data["attempts_per_arm"],
                        "profile_inventory_digest": profile.inventory_digest(inventory),
                        "mutated_digest": next(a for a in data["arms"] if a["name"] == "degraded")["mutation"]["mutated_digest"],
                        "task_fixture": data["task"]["fixture"]}
    data["approval"]["declaration_digest"] = calibration.declaration_digest(data)
    return data


@pytest.mark.parametrize("path", [PRECHECK, FULL], ids=["precheck", "full"])
def test_the_step6_declarations_pass_the_complete_approval_validator(path: Path) -> None:
    """C1-C5 and the image, network and approval checks run only at approval;
    a synthetic, never-committed approval exercises them on the real content."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "gate-stops-early-step6/goal.md" in data["shared"]["public_requirements"]
    calibration.require_approved_discrimination(calibration.parse_discrimination_declaration(_synthetic_approval(data)), ROOT)
    broken = _synthetic_approval({**data, "shared": {**data["shared"], "image": {**data["shared"]["image"], "receipt_sha256": None}}})
    with pytest.raises(calibration.DeclarationRefused, match="receipt"):
        calibration.require_approved_discrimination(calibration.parse_discrimination_declaration(broken), ROOT)


@pytest.mark.parametrize("path", [PRECHECK, FULL], ids=["precheck", "full"])
def test_a_committed_step6_approval_if_present_binds_its_digest(path: Path) -> None:
    """The pre-check is stamped only on the orchestrator's go; the full pilot only
    after the pre-check condition passes. Unapproved, each must refuse."""
    data = json.loads(path.read_text(encoding="utf-8"))
    declaration = calibration.parse_discrimination_declaration(data)
    if data["approval"] is None:
        with pytest.raises(calibration.DeclarationRefused):
            calibration.require_approved_discrimination(declaration, ROOT)
    else:
        assert data["approval"]["declaration_digest"] == calibration.declaration_digest(data)
        calibration.require_approved_discrimination(declaration, ROOT)
