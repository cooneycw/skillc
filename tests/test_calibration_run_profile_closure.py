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
from typing import Any

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


def _write_declaration(declaration_root: Path, revision: str, **profile_changes: object) -> None:
    declaration_root.mkdir(parents=True)
    (declaration_root / "subject.json").write_text(
        json.dumps({**SUBJECT_DICT, "revision": revision}), encoding="utf-8",
    )
    (declaration_root / "profile.json").write_text(
        json.dumps({**PROFILE_DICT, **profile_changes}), encoding="utf-8",
    )


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
        return cr._ClosureResult(home_files=files, tools=result.tools, gate_entrypoint=result.gate_entrypoint)

    monkeypatch.setattr(cr, "_closure_home_files", _tampered)
    with pytest.raises(cr.CalibrationRefused, match="disagrees with the skill surface"):
        cr.build_treatment(acquired, subject_profile=subject_profile, root=root)


# --------------------------------------------------------------- gate_entrypoint


@needs_git
def test_build_treatment_carries_a_declared_gate_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """skillc#334: a profile's own declared `gate_entrypoint` reaches
    `Treatment` unchanged - a fact about the subject, never re-derived
    from `verify_home_files`' own membership."""
    content_repo, revision = _build_content_repo(tmp_path)
    root = tmp_path / "root"
    subject_profile = "subject-profile"
    entrypoint = ".codex/skills/gate-check/SKILL.md"
    _write_declaration(root / subject_profile, revision, gate_entrypoint=entrypoint)

    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("whatever", tmp_path / "base", checkout=content_repo)

    prof = p.Profile.load(root / subject_profile / "profile.json")
    tree = p.GitTree(content_repo, revision)
    committed_inventory = p.validate(prof, tree)
    assert committed_inventory["gate_entrypoint"] == entrypoint
    (root / subject_profile / "evidence").mkdir()
    (root / subject_profile / "evidence" / "inventory.json").write_text(
        json.dumps(committed_inventory), encoding="utf-8",
    )

    treatment = cr.build_treatment(acquired, subject_profile=subject_profile, root=root)
    assert treatment.gate_entrypoint == entrypoint


@needs_git
def test_build_treatment_gate_entrypoint_defaults_to_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile that declares no `gate_entrypoint` at all must leave
    `Treatment.gate_entrypoint` as `None` - never inferred from anything
    the closure happens to install."""
    content_repo, revision = _build_content_repo(tmp_path)
    root = tmp_path / "root"
    subject_profile = "subject-profile"
    _write_declaration(root / subject_profile, revision)  # PROFILE_DICT, unmodified

    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("whatever", tmp_path / "base", checkout=content_repo)

    prof = p.Profile.load(root / subject_profile / "profile.json")
    tree = p.GitTree(content_repo, revision)
    committed_inventory = p.validate(prof, tree)
    assert committed_inventory["gate_entrypoint"] is None
    (root / subject_profile / "evidence").mkdir()
    (root / subject_profile / "evidence" / "inventory.json").write_text(
        json.dumps(committed_inventory), encoding="utf-8",
    )

    treatment = cr.build_treatment(acquired, subject_profile=subject_profile, root=root)
    assert treatment.gate_entrypoint is None


@needs_git
def test_red_case_a_gate_entrypoint_this_closure_never_installs_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """skillc#334's own named red case, exercised end to end through
    `build_treatment`: a declared `gate_entrypoint` this profile's closure
    never actually installs is refused - caught by `profile.validate()`
    itself (the earliest possible point, before any container exists),
    never silently accepted as a fact that could never be honoured."""
    content_repo, revision = _build_content_repo(tmp_path)
    root = tmp_path / "root"
    subject_profile = "subject-profile"
    _write_declaration(root / subject_profile, revision, gate_entrypoint=".codex/skills/does-not-exist.sh")

    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("whatever", tmp_path / "base", checkout=content_repo)

    with pytest.raises(p.Refused, match="gate_entrypoint '.codex/skills/does-not-exist.sh' is not installed"):
        cr.build_treatment(acquired, subject_profile=subject_profile, root=root)


@needs_git
@pytest.mark.parametrize(("with_profile", "fault", "runtime"), [
    (True, None, None), (False, None, None), (True, "missing-profile", None),
    (True, "invalid-profile", None), (True, "malformed-inventory", None),
    (True, None, "selected"), (True, None, "relocated"),
    (True, "missing-receipt", "selected"), (True, "bad-receipt", "selected"),
    (True, "wrong-image", "selected"), (True, "changed-metadata", "selected"),
    (True, "unrelated-receipt", None),
])
def test_calibration_cli_carries_the_declared_profile_to_the_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    with_profile: bool, fault: str | None, runtime: str | None,
) -> None:
    """Parse the real CLI and build a real closure; stop at agent dispatch.

    Approval/image resolution and acquisition are supplied local fixtures.
    Neither treatment construction nor calibration/collection forwarding is mocked.
    """
    from test_calibration_run import _declaration_data
    from test_runtime_supply import RECEIPT

    from skillc import (
        agent_trial,
        calibration,
        cli,
        docker_backend,
        runtime_supply,
        trial,
        trial_bootstrap,
    )

    content_repo, revision = _build_content_repo(tmp_path)
    root = tmp_path / "root"
    entrypoint = ".codex/skills/gate-check/SKILL.md"
    profile_name = "relocated/identical-profile" if runtime == "relocated" else "subject-profile"
    dependencies = json.loads(json.dumps(PROFILE_DICT["dependencies"]))
    if runtime:
        dependencies[-1]["probes"] = [{"kind": "python-import", "modules": ["json"], "uv_project": "Work/kit"}]
        # A synthetic supported pin exercises the actual classifier with real
        # validated closures. It does not claim this fixture is CPP evidence.
        policy = runtime_supply.supported_policy()
        policy.update(subject_locator=SUBJECT_DICT["locator"], subject_revision=revision,
                      gate_entrypoint=entrypoint, project="Work/kit")
        # Receipt validation still uses its independent package policy; replace
        # only the selector's policy lookup in this synthetic routing fixture.
        real_selector = runtime_supply.requires_supply
        digest = materialize.sha256_bytes(b"[project]\nname = 'kit'\n")

        def select_fixture(**kwargs):
            with monkeypatch.context() as local:
                local.setattr(runtime_supply, "supported_policy", lambda: policy)
                local.setattr(runtime_supply, "metadata", lambda ignored: {"Work/kit/pyproject.toml":
                             "sha256:" + "0" * 64 if fault == "changed-metadata" else digest})
                return real_selector(**kwargs)

        monkeypatch.setattr(runtime_supply, "requires_supply", select_fixture)
        # #279 policy B: the synthetic subject can never be a supported pin, so
        # selection is stubbed; the receipt's own pin check is waived with it -
        # only the kind is checked here (the pin check's reds: test_runtime_policy_b).
        real_require_kind = runtime_supply.require_kind
        monkeypatch.setattr(runtime_supply, "require_kind",
                            lambda supply, selected, revision=None: real_require_kind(supply, selected))
    _write_declaration(root / profile_name, revision, gate_entrypoint=entrypoint, dependencies=dependencies)
    inventory = p.validate(p.Profile.load(root / profile_name / "profile.json"),
                           p.GitTree(content_repo, revision))
    evidence = root / profile_name / "evidence"
    evidence.mkdir()
    (evidence / "inventory.json").write_text(json.dumps(inventory))
    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("fixture", tmp_path / "acquisition", checkout=content_repo)
    data = _declaration_data(attempts=1)
    arms = data["arms"]
    assert isinstance(arms, list)
    declared_subject = next(arm["subject"] for arm in arms if isinstance(arm["subject"], dict))
    declared_subject.update(name="fixture", locator=subject.locator, revision=revision)
    if with_profile:
        declared_subject["profile"] = profile_name
    else:
        declared_subject.pop("profile", None)
    shared = data["shared"]
    assert isinstance(shared, dict)
    if runtime or fault == "unrelated-receipt":
        shared["image"]["digest"] = json.loads(RECEIPT)["image_id"]
    declaration = tmp_path / "declaration.json"
    declaration.write_text(json.dumps(data))
    monkeypatch.setattr(cr, "ROOT", root)
    monkeypatch.setattr(calibration, "require_approved", lambda *args, **kwargs: None)
    shared = data["shared"]
    assert isinstance(shared, dict)
    monkeypatch.setattr(trial_bootstrap, "pinned_cli_version", lambda key: shared["client"]["version"])
    monkeypatch.setattr(demo, "resolve_image_digest", lambda *args: shared["image"]["digest"])
    acquisition_paths: list[Path] = []

    def acquire_fixture(name: str, run_dir: Path) -> cc.AcquiredCollection:
        for suffix in ("checkout", "staging"):
            path = run_dir / f"{name}-{suffix}"
            path.mkdir()
            acquisition_paths.append(path)
        return acquired

    monkeypatch.setattr(cc, "acquire_collection", acquire_fixture)
    if fault == "missing-profile":
        (root / profile_name / "profile.json").unlink()
    elif fault == "invalid-profile":
        (root / profile_name / "profile.json").write_text("{}")
    elif fault == "malformed-inventory":
        (evidence / "inventory.json").write_text("{broken")
    seen: list[dict[str, object]] = []

    def observe_attempt(**kwargs: object) -> dict[str, object]:
        seen.append(kwargs)
        experiment = kwargs["experiment"]
        assert isinstance(experiment, trial.Experiment)
        return trial.finalize(experiment, str(kwargs["attempt_id"]), disposition="unavailable",
                              reason="CLI control stops before subject dispatch")

    monkeypatch.setattr(agent_trial, "run_one_attempt", observe_attempt)
    args = ["calibration-run", str(declaration), "--image", shared["image"]["tag"],
            "--private-dir", str(tmp_path / "private")]
    if (runtime or fault == "unrelated-receipt") and fault != "missing-receipt":
        receipt = tmp_path / "runtime-receipt.json"
        receipt_value = json.loads(RECEIPT)
        if fault == "wrong-image":
            receipt_value["image_id"] = "sha256:" + "f" * 64
        receipt.write_bytes(b"{}" if fault == "bad-receipt" else json.dumps(receipt_value).encode())
        args.extend(["--runtime-supply-receipt", str(receipt)])
    code = cli.main(args)
    assert len(acquisition_paths) == 2
    assert all(not path.exists() for path in acquisition_paths)
    if fault is not None:
        assert code == 2
        assert seen == []
        assert "skillc:" in capsys.readouterr().err
        return
    assert code == 1
    assert len(seen) == 2
    treated = next(call for call in seen if call["extra_home_files"])
    baseline = next(call for call in seen if not call["extra_home_files"])
    for call in seen:
        agent = call["backend"]
        grading = call["grading_backend"]
        assert isinstance(agent, docker_backend.DockerBackend)
        assert isinstance(grading, docker_backend.DockerBackend)
        assert agent.image == grading.image == shared["image"]["digest"]
        assert grading.runtime_supply is None
        if runtime:
            assert agent.runtime_supply is not None
            assert agent.runtime_supply.image_id == agent.image
        else:
            assert agent.runtime_supply is None
    assert not baseline["verify_home_files"]
    assert not baseline["preflight_tools"]
    assert baseline["gate_entrypoint"] is None
    if with_profile:
        assert treated["gate_entrypoint"] == entrypoint
        checked = treated["verify_home_files"]
        tools = treated["preflight_tools"]
        assert isinstance(checked, dict) and isinstance(tools, (tuple, list))
        assert checked["Work/kit/pyproject.toml"] == materialize.sha256_bytes(
            b"[project]\nname = 'kit'\n")
        assert [tool["id"] for tool in tools] == ["tool-bash"]
    else:
        assert treated["gate_entrypoint"] is None
        assert not treated["verify_home_files"]
        assert not treated["preflight_tools"]


def _profiled_acquisition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[cc.AcquiredCollection, Path, str]:
    content_repo, revision = _build_content_repo(tmp_path)
    root = tmp_path / "root"
    subject_profile = "subject-profile"
    _write_declaration(root / subject_profile, revision)
    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("whatever", tmp_path / "base", checkout=content_repo)
    committed = p.validate(p.Profile.load(root / subject_profile / "profile.json"), p.GitTree(content_repo, revision))
    (root / subject_profile / "evidence").mkdir()
    (root / subject_profile / "evidence" / "inventory.json").write_text(json.dumps(committed), encoding="utf-8")
    return acquired, root, subject_profile


@needs_git
def test_a_profiled_treatment_pins_exactly_what_its_inventory_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#424: the pins derived from the installed SKILL.md bytes agree with
    #354's inventory-derived pins - two routes, one answer."""
    acquired, root, subject_profile = _profiled_acquisition(tmp_path, monkeypatch)
    treatment = cr.build_treatment(acquired, subject_profile=subject_profile, root=root)
    committed = json.loads((root / subject_profile / "evidence" / "inventory.json").read_text())
    assert list(treatment.skill_digests) == sorted(p.skill_digest_pins(committed), key=lambda pin: pin["path"])
    assert [pin["path"] for pin in treatment.skill_digests] == [".codex/skills/gate-check/SKILL.md"]


@needs_git
def test_red_case_inventory_pins_that_disagree_with_the_installed_bytes_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#424 cross-check: if the inventory would pin a different body than the
    treatment installs, the pins would describe a skill nobody installed."""
    acquired, root, subject_profile = _profiled_acquisition(tmp_path, monkeypatch)
    real = p.skill_digest_pins

    def drifted(inventory: dict[str, object]) -> list[dict[str, str]]:
        return [{**pin, "body_digest": "sha256:" + "0" * 64} for pin in real(inventory)]  # type: ignore[arg-type]

    monkeypatch.setattr(p, "skill_digest_pins", drifted)
    with pytest.raises(cr.CalibrationRefused, match="disagree with the installed skills"):
        cr.build_treatment(acquired, subject_profile=subject_profile, root=root)


#: #432: a second skill the subject installs but the profile does not select -
#: the shape of every real CPP profile, whose collection is wider than its
#: selection (the 86641e8 profile selects 1 of 77).
OTHER_SKILL_MD = "---\nname: other-check\ndescription: An unrelated skill\n---\nNot this profile's.\n"


def _narrow_profile_acquisition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[cc.AcquiredCollection, Path, str]:
    """A two-skill collection (subject `select: all`) under a profile that
    selects one of them: the install is wider than the inventory's pins."""
    repo = tmp_path / "content-repo"
    for name, text in (("gate-check", SKILL_MD), ("other-check", OTHER_SKILL_MD)):
        (repo / "pack" / "skills" / name).mkdir(parents=True)
        (repo / "pack" / "skills" / name / "SKILL.md").write_text(text, encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = 'kit'\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "fixture")
    revision = _git(repo, "rev-parse", "HEAD")
    root = tmp_path / "root"
    subject_profile = "subject-profile"
    _write_declaration(root / subject_profile, revision)
    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("whatever", tmp_path / "base", checkout=repo)
    committed = p.validate(p.Profile.load(root / subject_profile / "profile.json"), p.GitTree(repo, revision))
    (root / subject_profile / "evidence").mkdir()
    (root / subject_profile / "evidence" / "inventory.json").write_text(json.dumps(committed), encoding="utf-8")
    return acquired, root, subject_profile


@needs_git
def test_a_profile_narrower_than_its_install_builds_and_pins_every_installed_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#432 regression: the inventory pins only the selected skill, the
    treatment installs both. Equality refused this; the per-path subset check
    accepts it, and the ledger pins stay EVERY installed skill, from its bytes."""
    acquired, root, subject_profile = _narrow_profile_acquisition(tmp_path, monkeypatch)
    committed = json.loads((root / subject_profile / "evidence" / "inventory.json").read_text())
    assert [pin["path"] for pin in p.skill_digest_pins(committed)] == [".codex/skills/gate-check/SKILL.md"]
    treatment = cr.build_treatment(acquired, subject_profile=subject_profile, root=root)
    assert [pin["path"] for pin in treatment.skill_digests] == [
        ".codex/skills/gate-check/SKILL.md", ".codex/skills/other-check/SKILL.md"]
    by_path = {pin["path"]: pin for pin in treatment.skill_digests}
    for pin in p.skill_digest_pins(committed):
        assert by_path[pin["path"]] == pin


@needs_git
@pytest.mark.parametrize("field, named", [
    ("body_digest", "body_digest"),
    ("description_digest", "description_digest"),
])
def test_red_case_a_narrow_profile_pin_whose_digest_differs_at_the_same_path_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, named: str,
) -> None:
    """#432: the subset check compares digests PER PATH, both of them - a
    membership-only check would let a drifted description through."""
    acquired, root, subject_profile = _narrow_profile_acquisition(tmp_path, monkeypatch)
    real = p.skill_digest_pins

    def drifted(inventory: dict[str, object]) -> list[dict[str, str]]:
        return [{**pin, field: "sha256:" + "0" * 64} for pin in real(inventory)]  # type: ignore[arg-type]

    monkeypatch.setattr(p, "skill_digest_pins", drifted)
    with pytest.raises(cr.CalibrationRefused, match=f"gate-check/SKILL.md.*{named}"):
        cr.build_treatment(acquired, subject_profile=subject_profile, root=root)


@needs_git
def test_red_case_an_inventory_pin_for_a_skill_that_is_not_installed_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#432: a pin the treatment cannot honour - its path is not installed at
    all - describes a skill nobody delivered."""
    acquired, root, subject_profile = _narrow_profile_acquisition(tmp_path, monkeypatch)
    real = p.skill_digest_pins

    def phantom(inventory: dict[str, object]) -> list[dict[str, str]]:
        pins = real(inventory)  # type: ignore[arg-type]
        return [*pins, {**pins[0], "path": ".codex/skills/never-installed/SKILL.md"}]

    monkeypatch.setattr(p, "skill_digest_pins", phantom)
    with pytest.raises(cr.CalibrationRefused, match="never-installed/SKILL.md.*not installed"):
        cr.build_treatment(acquired, subject_profile=subject_profile, root=root)


@needs_git
def test_protocol_is_bound_to_revalidated_inventory_and_fixture_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_gate_state import CONFIG

    from skillc import gate_state
    content_repo, revision = _build_content_repo(tmp_path)
    root = tmp_path / "root"
    name = "subject-profile"
    _write_declaration(root / name, revision, gate_entrypoint=".codex/skills/gate-check/SKILL.md",
                       gate_state_protocol=CONFIG)
    subject = materialize.Subject.from_dict({**SUBJECT_DICT, "revision": revision})
    monkeypatch.setattr(demo, "load_demo_subject", lambda name: subject)
    acquired = cc.acquire_collection("fixture", tmp_path / "base", checkout=content_repo)
    inventory = p.validate(p.Profile.load(root / name / "profile.json"), p.GitTree(content_repo, revision))
    (root / name / "evidence").mkdir()
    evidence = root / name / "evidence/inventory.json"
    evidence.write_text(json.dumps(inventory))
    with pytest.raises(cr.CalibrationRefused, match="fixture-live"):
        cr.build_treatment(acquired, subject_profile=name, root=root)
    treatment = cr.build_treatment(acquired, subject_profile=name, root=root, fixture_gate_state=True)
    assert treatment.gate_state_protocol == gate_state.Protocol.from_inventory(inventory)
    assert treatment.gate_state_protocol.producer_revision == revision
    inventory["gate_state_protocol"]["version"] = 2
    evidence.write_text(json.dumps(inventory))
    with pytest.raises(cr.CalibrationRefused, match="stale"):
        cr.build_treatment(acquired, subject_profile=name, root=root, fixture_gate_state=True)


@pytest.mark.parametrize("route", ["normal", "discrimination", "degrade"])
def test_unsupported_routes_refuse_reused_protocol_before_store(tmp_path: Path, route: str) -> None:
    from test_gate_state import PROTOCOL
    t = cr.Treatment({}, "digest", None, gate_state_protocol=PROTOCOL)
    kwargs: dict[str, Any] = {"run_dir": tmp_path / "run", "image_digest": None,
              "backends": lambda: pytest.fail("backend"), "argv_for": lambda _: [], "root": tmp_path}
    with pytest.raises(cr.CalibrationRefused, match="fixture-only"):
        if route == "normal":
            cr.run_calibration(None, treatment=t, **kwargs)  # type: ignore[arg-type]
        elif route == "discrimination":
            cr.run_discrimination(None, intact=t, **kwargs)  # type: ignore[arg-type]
        else:
            cr.degraded_treatment(t, None)  # type: ignore[arg-type]
    assert not (tmp_path / "run").exists()
