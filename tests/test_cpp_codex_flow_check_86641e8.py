"""Regression tests for skillc#376's repin: `cpp-codex-flow-check` declared
again as its OWN profile at claude-power-pack `86641e8`
(`evals/subjects/cpp-codex-flow-check-86641e8/`), the next study pin CPP
recorded in its own 0c6ffd7a. The `ea6dbfa` profile and its evidence stay
untouched, as #265/#330 left the `85e9b03` one.

Why this pin: `86641e8` carries CPP `8e0a34fb`, which gives NOT_RUN its own
flow-check report state - the stage-state distinction #376 grades. The
committed snapshot `tests/fixtures/profile-cpp-codex-flow-check-86641e8/` is
the same 97-path trim as the `ea6dbfa` snapshot, filled from the real CPP tree
at the new pin.

Red cases:
- `test_the_repin_is_what_carries_not_run`: the `ea6dbfa` snapshot must NOT
  define the state, so a repin that copied the old bytes forward fails.
- `test_the_degraded_arm_digest_is_this_pins_reference_minus_the_removed_text`:
  the same computation over the `ea6dbfa` snapshot must give the old digest,
  never the declared one.
- `test_every_live_selector_names_the_repinned_subject`: any one selector left
  at the old pin fails it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from skillc import profile as p

ROOT = Path(__file__).resolve().parent.parent
PIN = "86641e817711d8a7746270745a5dfa7cacf04b0c"
OLD_PIN = "ea6dbfa45f9308ee6ba60f032d8e7031bd6938a1"
RUNTIME_ID = "cpp-codex-flow-check-86641e8"
SUBJECT_DIR = ROOT / "evals" / "subjects" / RUNTIME_ID
SNAPSHOT = ROOT / "tests" / "fixtures" / f"profile-{RUNTIME_ID}"
OLD_SUBJECT_DIR = ROOT / "evals" / "subjects" / "cpp-codex-flow-check-ea6dbfa"
OLD_SNAPSHOT = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-check-ea6dbfa"
REFERENCE = Path("codex/skills/flow-check/reference.md")

#: `profile.inventory_digest` of the ea6dbfa evidence as #203/#287 approvals
#: and tests recorded it before #376. The repin must not move it.
OLD_INVENTORY_DIGEST = "sha256:eb9cad6f8bb74c92fab4aa002bd6f2a55f3e8eb15ff25adcd582fea21071b1ab"
#: The discrimination declaration's mutated_digest before #376 (ea6dbfa).
OLD_MUTATED_DIGEST = "sha256:9149e393bb1d9e40adb97dca85774e23f77317a21e6bff832c160055c726234d"

NOT_RUN_STATE = re.compile(r"^- \*\*NOT_RUN\*\* - Never executed because an earlier step", re.M)
NOT_RUN_ROW = re.compile(r"^\| (Tests|Typecheck) \(`make \w+`\) \| PASS/FAIL/SKIP/NOT_RUN \|", re.M)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_repinned_profile_is_clean_against_its_own_pin() -> None:
    prof = p.Profile.load(SUBJECT_DIR / "profile.json")
    report = p.diagnose(prof, p.load_tree(prof, None, SNAPSHOT))

    assert report["complete"] is True
    assert report["problems"] == []
    assert _json(SUBJECT_DIR / "subject.json")["revision"] == PIN


def test_the_repin_is_what_carries_not_run() -> None:
    new = (SNAPSHOT / REFERENCE).read_text(encoding="utf-8")
    old = (OLD_SNAPSHOT / REFERENCE).read_text(encoding="utf-8")

    assert NOT_RUN_STATE.search(new), "86641e8's reference.md must define NOT_RUN as its own state"
    assert len(NOT_RUN_ROW.findall(new)) == 2, "both later aggregate stages must be able to report NOT_RUN"
    # Red case: the bytes this repin replaces do not carry the state.
    assert not NOT_RUN_STATE.search(old)
    assert not NOT_RUN_ROW.search(old)


def test_the_snapshot_trims_the_same_paths_as_the_ea6dbfa_snapshot() -> None:
    def paths(root: Path) -> set[str]:
        return {q.relative_to(root).as_posix() for q in root.rglob("*") if q.is_file()}

    new = paths(SNAPSHOT)
    assert new == paths(OLD_SNAPSHOT)
    assert len(new) == 97


def test_the_ea6dbfa_profile_evidence_is_unchanged() -> None:
    inventory = _json(OLD_SUBJECT_DIR / "evidence" / "inventory.json")

    assert p.inventory_digest(inventory) == OLD_INVENTORY_DIGEST
    assert _json(OLD_SUBJECT_DIR / "subject.json")["revision"] == OLD_PIN


def test_every_live_selector_names_the_repinned_subject() -> None:
    policies = [_json(ROOT / "skillc" / "runtime-policy.json"),
                _json(ROOT / "docker" / "profile-trial" / "runtime-policy.json")]
    build = (ROOT / "docker" / "profile-trial" / "build.py").read_text(encoding="utf-8")

    for policy in policies:
        assert policy["runtime_id"] == RUNTIME_ID
        assert policy["subject_revision"] == PIN
        assert policy["pyproject_sha256"] == _sha256(SNAPSHOT / "pyproject.toml")
        assert policy["lock_sha256"] == _sha256(SNAPSHOT / "uv.lock")
    assert f'RUNTIME_ID = "{RUNTIME_ID}"' in build
    assert f'REVISION = "{PIN}"' in build

    for name in ("pilot-discrimination-declaration.json", "pilot-improvement-declaration.json"):
        declaration = _json(ROOT / "evals" / "calibration-287" / name)
        # A baseline arm installs no subject (`subject: null`); every arm that
        # installs one must install the repinned one, and at least one does.
        subject_arms = [arm for arm in declaration["arms"] if arm["subject"] is not None]
        assert subject_arms, name
        for arm in subject_arms:
            assert arm["subject"]["name"] == RUNTIME_ID, (name, arm["name"])
            assert arm["subject"]["profile"] == f"evals/subjects/{RUNTIME_ID}", (name, arm["name"])
            assert arm["subject"]["revision"].endswith(PIN), (name, arm["name"])
        assert declaration["approval"] is None, "a repin refreshes a draft; it never approves one"


def test_the_degraded_arm_digest_is_this_pins_reference_minus_the_removed_text() -> None:
    declaration = _json(ROOT / "evals" / "calibration-287" / "pilot-discrimination-declaration.json")
    mutation = next(arm["mutation"] for arm in declaration["arms"] if arm["name"] == "degraded")

    def degraded_digest(snapshot: Path) -> str:
        text = (snapshot / REFERENCE).read_text(encoding="utf-8")
        assert text.count(mutation["removed_text"]) == 1, "the removed sentence must occur exactly once"
        return "sha256:" + hashlib.sha256(text.replace(mutation["removed_text"], "", 1).encode()).hexdigest()

    assert mutation["mutated_digest"] == degraded_digest(SNAPSHOT)
    # Red case: the same method over the replaced pin yields the replaced value.
    assert degraded_digest(OLD_SNAPSHOT) == OLD_MUTATED_DIGEST != mutation["mutated_digest"]
