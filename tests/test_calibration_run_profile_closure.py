"""End-to-end test for skillc#334's `build_treatment` profile-closure
wiring: a minimal synthetic profile (reusing `tests/test_profile.py`'s own
fixture shape - one skill at `skills_root`, one dependency OUTSIDE it,
`kit-checkout`) installed from a REAL git checkout, merged into the
treatment's home files alongside the selected skill surface.

Needs a real `git` binary (CI has none - `needs_git`, matching every
other git-mode test in this repo). `subject.json`/`profile.json` live in
a PLAIN directory (never inside the git repo they describe) - the
committed real subjects (`evals/subjects/*/subject.json`) work the same
way: the declaration lives in skillc's own history, the revision it
NAMES is a commit in a DIFFERENT repository.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from skillc import calibration_run as cr
from skillc import collection_conformance as cc
from skillc import demo, materialize
from skillc import profile as p

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

SKILL_MD = "---\nname: gate-check\ndescription: Run the project's gates\n---\nFollow the procedure.\n"

SUBJECT_DICT = {
    "subject_schema": 1, "locator": "example.invalid/kit", "revision": "0" * 40,
    "surface": "codex-skills", "skills_root": "pack/skills", "select": "all",
    "client": {"name": "codex", "version": "0.157.1"},
}

PROFILE_DICT: dict[str, object] = {
    "profile_schema": 1,
    "name": "kit-gate-check",
    "subject": "subject.json",
    "select": ["gate-check"],
    "treatment_question": "product",
    "allowed_destinations": [".codex/skills", "Work/kit"],
    "reference_patterns": [
        {"name": "home", "class": "home-relative", "pattern": r"~/[A-Za-z0-9._/-]*[A-Za-z0-9_-]"},
    ],
    "dependencies": [
        {"id": "kit-checkout", "kind": "library", "scope": "treatment",
         "paths": ["pyproject.toml"], "destination": "Work/kit",
         "traverse": False, "no_traverse_reason": "no path text to scan",
         "unreferenced_reason": "nothing in this minimal fixture names it by text"},
        {"id": "tool-bash", "kind": "tool", "scope": "common", "version": "any",
         "supply": "the image", "unreferenced_reason": "a command word"},
    ],
    "unsupported": [],
    "mirrors": [],
    "generated_from": [],
    "declared_empty_kinds": ["startup-context", "helper"],
    "client_profiles": {"codex": {"status": "declared", "reason": "the subject's own surface"}},
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def _build_content_repo(tmp_path: Path) -> tuple[Path, str]:
    """The claude-power-pack-equivalent checkout: skill content under
    `pack/skills`, plus `pyproject.toml` at the repo root - OUTSIDE
    `skills_root`, exactly like the real `checkout-libraries` dependency."""
    repo = tmp_path / "content-repo"
    (repo / "pack" / "skills" / "gate-check").mkdir(parents=True)
    (repo / "pack" / "skills" / "gate-check" / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = 'kit'\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "fixture")
    return repo, _git(repo, "rev-parse", "HEAD")


def _write_declaration(declaration_root: Path, revision: str) -> None:
    declaration_root.mkdir(parents=True)
    (declaration_root / "subject.json").write_text(
        json.dumps({**SUBJECT_DICT, "revision": revision}), encoding="utf-8",
    )
    (declaration_root / "profile.json").write_text(json.dumps(PROFILE_DICT), encoding="utf-8")


@needs_git
def test_build_treatment_merges_the_profile_closure_with_the_skill_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_repo, revision = _build_content_repo(tmp_path)
    root = tmp_path / "root"
    subject_profile = "subject-profile"
    _write_declaration(root / subject_profile, revision)

    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("whatever", tmp_path / "base", checkout=content_repo)
    assert acquired.repo == content_repo

    # The committed evidence: computed once here, standing in for what a
    # real #265-style PR would have already committed alongside the profile.
    prof = p.Profile.load(root / subject_profile / "profile.json")
    tree = p.GitTree(content_repo, revision)
    committed_inventory = p.validate(prof, tree)
    (root / subject_profile / "evidence").mkdir()
    (root / subject_profile / "evidence" / "inventory.json").write_text(
        json.dumps(committed_inventory), encoding="utf-8",
    )

    treatment = cr.build_treatment(acquired, subject_profile=subject_profile, root=root)
    assert treatment.home_files[".codex/skills/gate-check/SKILL.md"] == SKILL_MD.encode()
    assert treatment.home_files["Work/kit/pyproject.toml"] == b"[project]\nname = 'kit'\n"
    # #334: every closure file's digest is carried for in-container
    # re-verification, and the profile's tool dependencies (here,
    # tool-bash - declared with no probes, since PROFILE_DICT predates
    # #334's probe requirement) are carried for the live preflight.
    assert treatment.verify_home_files[".codex/skills/gate-check/SKILL.md"] == \
        materialize.sha256_bytes(SKILL_MD.encode())
    assert treatment.verify_home_files["Work/kit/pyproject.toml"] == \
        materialize.sha256_bytes(b"[project]\nname = 'kit'\n")
    assert [t["id"] for t in treatment.preflight_tools] == ["tool-bash"]


@needs_git
def test_build_treatment_requires_subject_profile_and_root_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_repo, revision = _build_content_repo(tmp_path)
    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("whatever", tmp_path / "base", checkout=content_repo)
    with pytest.raises(cr.CalibrationRefused, match="must be given together"):
        cr.build_treatment(acquired, subject_profile="subject-profile")


@needs_git
def test_red_case_a_stale_committed_inventory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation check: the committed evidence disagrees with what the
    live checkout actually validates to (simulated by committing evidence
    for a DIFFERENT, unrelated profile shape) - must refuse, never
    silently install a closure that was never actually validated against
    this subject source."""
    content_repo, revision = _build_content_repo(tmp_path)
    root = tmp_path / "root"
    subject_profile = "subject-profile"
    _write_declaration(root / subject_profile, revision)
    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("whatever", tmp_path / "base", checkout=content_repo)

    (root / subject_profile / "evidence").mkdir()
    (root / subject_profile / "evidence" / "inventory.json").write_text(
        json.dumps({"inventory_schema": 1, "not": "the real inventory"}), encoding="utf-8",
    )
    with pytest.raises(cr.CalibrationRefused, match="is stale against the current subject source"):
        cr.build_treatment(acquired, subject_profile=subject_profile, root=root)


@needs_git
def test_overlapping_but_agreeing_destinations_are_not_a_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validated profile's own closure covers the selected skill's
    bundled files too (profile.py installs skills AND dependencies
    together), so `.codex/skills/gate-check/SKILL.md` is declared by
    BOTH the skills acquisition and the profile's inventory - expected,
    not an error, as long as the bytes agree (which they do here: same
    repo, same revision, `verify_repo_matches_skills` already proved it)."""
    content_repo, revision = _build_content_repo(tmp_path)
    root = tmp_path / "root"
    subject_profile = "subject-profile"
    _write_declaration(root / subject_profile, revision)
    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("whatever", tmp_path / "base", checkout=content_repo)

    prof = p.Profile.load(root / subject_profile / "profile.json")
    tree = p.GitTree(content_repo, revision)
    committed_inventory = p.validate(prof, tree)
    assert any(r["destination"] == ".codex/skills/gate-check/SKILL.md"
              for group in ("skills", "dependencies") for entry in committed_inventory[group]
              for r in entry["files"])  # the overlap genuinely exists in this fixture
    (root / subject_profile / "evidence").mkdir()
    (root / subject_profile / "evidence" / "inventory.json").write_text(
        json.dumps(committed_inventory), encoding="utf-8",
    )
    treatment = cr.build_treatment(acquired, subject_profile=subject_profile, root=root)
    assert treatment.home_files[".codex/skills/gate-check/SKILL.md"] == SKILL_MD.encode()


@needs_git
def test_red_case_a_genuine_disagreement_between_closure_and_skill_surface_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation check: the closure and the skill surface name the SAME
    destination but DIFFERENT bytes - this must never happen if the two
    paths are reading the same revision honestly, so it is refused as a
    real disagreement rather than silently preferring either side."""
    content_repo, revision = _build_content_repo(tmp_path)
    root = tmp_path / "root"
    subject_profile = "subject-profile"
    _write_declaration(root / subject_profile, revision)
    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("whatever", tmp_path / "base", checkout=content_repo)

    prof = p.Profile.load(root / subject_profile / "profile.json")
    tree = p.GitTree(content_repo, revision)
    committed_inventory = p.validate(prof, tree)
    (root / subject_profile / "evidence").mkdir()
    (root / subject_profile / "evidence" / "inventory.json").write_text(
        json.dumps(committed_inventory), encoding="utf-8",
    )

    real_closure_home_files = cr._closure_home_files

    def _tampered(acquired: cc.AcquiredCollection, subject_profile: str, root: Path) -> cr._ClosureResult:
        result = real_closure_home_files(acquired, subject_profile, root)
        files = dict(result.home_files)
        files[".codex/skills/gate-check/SKILL.md"] = b"not the real skill content\n"
        return cr._ClosureResult(home_files=files, tools=result.tools)

    monkeypatch.setattr(cr, "_closure_home_files", _tampered)
    with pytest.raises(cr.CalibrationRefused, match="disagrees with the skill surface"):
        cr.build_treatment(acquired, subject_profile=subject_profile, root=root)
