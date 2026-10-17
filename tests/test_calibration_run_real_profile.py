"""#432: `build_treatment` against the REAL committed profile
`evals/subjects/cpp-codex-flow-check-86641e8`, with the FULL treatment
install the Level-3 campaigns and the #287 calibration arm deliver.

The profile selects one skill (`flow-check`); its subject's collection is
every CPP Codex skill at that revision. #424's equality cross-check refused
exactly this pairing, and no committed test exercised it: every earlier
fixture installed precisely what it pinned.

It needs `git` and a local claude-power-pack checkout holding the pinned
revision (`SKILLC_CPP_CHECKOUT`, default `~/Projects/claude-power-pack`).
CI has neither, so there it is SKIPPED, and the skip says which one is
missing - never a silent pass. Its evidence is a local or runner run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import profile as p

ROOT = Path(__file__).resolve().parent.parent
SUBJECT = "cpp-codex-flow-check-86641e8"
SUBJECT_PROFILE = f"evals/subjects/{SUBJECT}"
REVISION = json.loads((ROOT / SUBJECT_PROFILE / "subject.json").read_text(encoding="utf-8"))["revision"]
CPP_CHECKOUT = Path(os.environ.get("SKILLC_CPP_CHECKOUT", Path.home() / "Projects" / "claude-power-pack"))


def _missing_prerequisite() -> str | None:
    if shutil.which("git") is None:
        return "git is not installed"
    if not (CPP_CHECKOUT / ".git").exists():
        return f"no claude-power-pack checkout at {CPP_CHECKOUT} (set SKILLC_CPP_CHECKOUT)"
    found = subprocess.run(["git", "-C", str(CPP_CHECKOUT), "cat-file", "-e", f"{REVISION}^{{commit}}"],
                           capture_output=True, check=False)
    if found.returncode != 0:
        return f"the claude-power-pack checkout at {CPP_CHECKOUT} does not hold commit {REVISION}"
    return None


_MISSING = _missing_prerequisite()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=f"#432 real-profile check not run: {_MISSING}")


def _acquire(tmp_path: Path) -> cc.AcquiredCollection:
    clone = tmp_path / "claude-power-pack"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(CPP_CHECKOUT), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", "--detach", REVISION], check=True)
    return cc.acquire_collection(SUBJECT, tmp_path / "base", checkout=clone)


def test_the_real_profile_with_its_full_install_builds_and_pins_every_installed_skill(tmp_path: Path) -> None:
    acquired = _acquire(tmp_path)
    treatment = cr.build_treatment(acquired, subject_profile=SUBJECT_PROFILE, root=ROOT)
    inventory = json.loads((ROOT / SUBJECT_PROFILE / "evidence" / "inventory.json").read_text(encoding="utf-8"))
    pinned = p.skill_digest_pins(inventory)
    installed = {pin["path"]: pin for pin in treatment.skill_digests}
    # The install is the whole collection; the inventory pins the selection.
    assert len(installed) == len([f for f in acquired.files if f.rel == "SKILL.md"]) == 74
    assert [pin["path"] for pin in pinned] == [".codex/skills/flow-check/SKILL.md"]
    for pin in pinned:
        assert installed[pin["path"]] == pin
