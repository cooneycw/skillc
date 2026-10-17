"""#287 P2, orchestrator ruling D-P2a: an approval binds the WHOLE declaration.

`approval.declaration_digest` must equal the declaration's own canonical
digest (minus `approval`) for both declaration kinds, so any field changed
after approval is refused. The four committed approvals that predate the rule
keep their meaning through a pin of their own digests
(`calibration.LEGACY_APPROVED_DECLARATION_DIGESTS`), and that pin cannot be
borrowed: editing one of them changes its digest."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import stamp_approval
from test_calibration import _approved as _approved_calibration
from test_calibration_discrimination_declaration import _approved as _approved_discrimination

from skillc import calibration

ROOT = Path(__file__).resolve().parent.parent
LEGACY = calibration.LEGACY_APPROVED_DECLARATION_DIGESTS


def test_every_pinned_legacy_digest_is_its_committed_declaration_exactly() -> None:
    """The pin names each file by the digest of its CURRENT committed bytes;
    a committed approval edited later falls out of the pin and fails here
    first, rather than silently losing (or keeping) its exemption."""
    for digest, path in LEGACY.items():
        assert calibration.declaration_digest(json.loads((ROOT / path).read_text(encoding="utf-8"))) == digest, path


def test_every_committed_approved_declaration_is_pinned_or_carries_a_digest() -> None:
    """Population check: no committed approved declaration escapes the rule."""
    for path in sorted(ROOT.glob("evals/**/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict) or data.get("kind") not in ("calibration-declaration",
                                                                   calibration.DISCRIMINATION_KIND):
            continue
        approval = data.get("approval")
        if approval is None:
            continue
        digest = calibration.declaration_digest(data)
        assert digest in LEGACY or approval.get("declaration_digest") == digest, path


@pytest.mark.parametrize("path", [p for p in LEGACY.values() if "203-c3" not in p])
def test_a_legacy_approval_still_authorizes(path: str) -> None:
    calibration.require_approved(calibration.load_declaration(ROOT / path), ROOT)


def test_the_c3_legacy_approval_fails_only_for_its_pre_existing_grader_reason() -> None:
    """calibration-203-c3 was already refused on main (its task's grader moved
    from revision 1 to 2 on disk); the new rule must not be what refuses it."""
    with pytest.raises(calibration.DeclarationRefused, match="grader") as refused:
        calibration.require_approved(calibration.load_declaration(ROOT / "evals/calibration-203-c3/run-manifest.json"),
                                     ROOT)
    assert "does not bind" not in str(refused.value)


def test_an_edited_legacy_declaration_loses_its_exemption() -> None:
    data = json.loads((ROOT / "evals/calibration-204/run-manifest.json").read_text(encoding="utf-8"))
    data["shared"]["model"] = data["shared"]["model"] + "-edited"
    with pytest.raises(calibration.DeclarationRefused, match="does not bind this exact declaration"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


def _reseed(data: dict[str, Any]) -> None:
    names = [a["name"] for a in data["arms"]]
    seed = data["arm_order"]["seed"] + 1
    data["arm_order"] = {"seed": seed, "sequence": calibration.derive_arm_order(seed, names, data["attempts_per_arm"])}


#: Each field the ruling names, changed AFTER the approval was stamped.
CHANGES: dict[str, Callable[[dict[str, Any]], None]] = {
    "client": lambda d: d["shared"]["client"].update(version=d["shared"]["client"]["version"] + ".1"),
    "model": lambda d: d["shared"].update(model=d["shared"]["model"] + "-other"),
    "effort": lambda d: d["shared"].update(reasoning_effort="low" if d["shared"]["reasoning_effort"] != "low"
                                           else "high"),
    "image": lambda d: d["shared"]["image"].update(digest="sha256:" + "9" * 64),
    "caps": lambda d: d["shared"].update(per_attempt_seconds=d["shared"]["per_attempt_seconds"] - 1),
    "seed": _reseed,
}


def _approved_calibration_stamped() -> dict[str, Any]:
    return stamp_approval(copy.deepcopy(_approved_calibration()))


def _approved_discrimination_stamped() -> dict[str, Any]:
    return stamp_approval(copy.deepcopy(_approved_discrimination()))


@pytest.mark.parametrize("field", sorted(CHANGES))
def test_a_calibration_field_changed_after_approval_is_refused(field: str) -> None:
    data = _approved_calibration_stamped()
    calibration.require_approved(calibration.parse_declaration(data), ROOT)  # the stamped one authorizes
    CHANGES[field](data)
    with pytest.raises(calibration.DeclarationRefused, match="does not bind this exact declaration"):
        calibration.require_approved(calibration.parse_declaration(data), ROOT)


@pytest.mark.parametrize("field", sorted(CHANGES))
def test_a_discrimination_field_changed_after_approval_is_refused(field: str) -> None:
    data = _approved_discrimination_stamped()
    calibration.require_approved_discrimination(calibration.parse_discrimination_declaration(data), ROOT)
    CHANGES[field](data)
    with pytest.raises(calibration.DeclarationRefused, match="does not bind this exact declaration"):
        calibration.require_approved_discrimination(calibration.parse_discrimination_declaration(data), ROOT)


@pytest.mark.parametrize("kind", ["calibration", "discrimination"])
def test_an_approval_with_no_declaration_digest_is_refused(kind: str) -> None:
    """Red case for the rule itself: before D-P2a an approval recording only
    by/at/attempts_per_arm (and mutated_digest) authorized; now it does not."""
    if kind == "calibration":
        data = _approved_calibration_stamped()
        del data["approval"]["declaration_digest"]
        with pytest.raises(calibration.DeclarationRefused, match="does not bind"):
            calibration.require_approved(calibration.parse_declaration(data), ROOT)
    else:
        data = _approved_discrimination_stamped()
        del data["approval"]["declaration_digest"]
        with pytest.raises(calibration.DeclarationRefused, match="does not bind"):
            calibration.require_approved_discrimination(calibration.parse_discrimination_declaration(data), ROOT)
