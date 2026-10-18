"""Offline controls for the local CI/CD capability profile (skillc#280).

`evals/subjects/cpp-codex-cicd-86641e8/` declares CPP's six cicd skills at the
flow-check profile's pin. These tests need no Docker and no network:

- the profile closes cleanly over its committed snapshot, and the evidence
  inventory (computed against a REAL git checkout at the pin) names exactly
  the snapshot's bytes;
- each manifest refusal the issue names fires: a dependency removed leaves a
  reference unresolved; an ambient host location left undeclared is
  unresolved rather than borrowed; a missing or too-old curl is `violated`;
  a tool with no probes is refused before any container call;
- the real closure selects the cicd runtime and the flow-check closure still
  selects its own.

The live counterpart is tests/test_cicd_profile_live.py.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import agent_trial as at
from skillc import materialize as m
from skillc import profile as p
from skillc import runtime_supply as rs

ROOT = Path(__file__).resolve().parent.parent
PIN = "86641e817711d8a7746270745a5dfa7cacf04b0c"
SUBJECT_DIR = ROOT / "evals" / "subjects" / "cpp-codex-cicd-86641e8"
SNAPSHOT = ROOT / "tests" / "fixtures" / "profile-cpp-codex-cicd-86641e8"
FLOW_CHECK_DIR = ROOT / "evals" / "subjects" / "cpp-codex-flow-check-86641e8"
FLOW_CHECK_SNAPSHOT = ROOT / "tests" / "fixtures" / "profile-cpp-codex-flow-check-86641e8"
CPP_CHECKOUT = Path.home() / "Projects" / "claude-power-pack"
SKILLS = ["cicd-check", "cicd-health", "cicd-init", "cicd-pipeline", "cicd-smoke", "cicd-verify"]


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _profile(**edits: Any) -> p.Profile:
    raw = _json(SUBJECT_DIR / "profile.json")
    raw.update(edits)
    return p.Profile.from_dict(raw, SUBJECT_DIR)


def _problems(prof: p.Profile) -> list[dict[str, Any]]:
    report = p.diagnose(prof, p.load_tree(prof, None, SNAPSHOT))
    assert report["complete"] is True
    problems: list[dict[str, Any]] = report["problems"]
    return problems


def test_the_profile_closes_over_its_pin_snapshot() -> None:
    assert _problems(p.Profile.load(SUBJECT_DIR / "profile.json")) == []
    assert _json(SUBJECT_DIR / "subject.json")["revision"] == PIN
    inventory = _json(SUBJECT_DIR / "evidence" / "inventory.json")
    assert inventory["subject"]["revision"] == PIN and inventory["subject"]["source_kind"] == "git"
    assert inventory["selection"] == SKILLS
    assert inventory["gate_entrypoint"] is None


def _records(inventory: dict[str, Any]) -> list[tuple[str, str, str]]:
    # A synthetic record has no source path.
    return sorted((str(r["source"]), r["destination"], r["digest"])
                  for group in ("skills", "dependencies") for entry in inventory[group] for r in entry["files"])


def test_the_evidence_inventory_names_exactly_the_snapshots_bytes() -> None:
    """The git-derived evidence and a fresh snapshot walk agree file for file."""
    evidence = _json(SUBJECT_DIR / "evidence" / "inventory.json")
    prof = p.Profile.load(SUBJECT_DIR / "profile.json")
    fresh = p.validate(prof, p.load_tree(prof, None, SNAPSHOT))
    assert _records(evidence) == _records(fresh)
    pinned = [r for group in ("skills", "dependencies") for entry in evidence[group]
              for r in entry["files"] if r["origin"] == "pinned"]
    assert len(pinned) == 54  # 55 snapshot files, CLAUDE.md replaced by the synthetic marker
    for record in pinned:
        data = (SNAPSHOT / record["source"]).read_bytes()
        assert record["digest"] == "sha256:" + hashlib.sha256(data).hexdigest(), record["source"]


def test_a_removed_dependency_leaves_its_reference_unresolved() -> None:
    raw = _json(SUBJECT_DIR / "profile.json")
    deps = [dep for dep in raw["dependencies"] if dep["id"] != "checkout-templates"]
    problems = _problems(_profile(dependencies=deps))
    unresolved = {prob["detail"].split(" (in ")[0] for prob in problems if prob["category"] == "unresolved-reference"}
    assert unresolved == {"unresolved reference: $CPP_DIR/templates/Makefile.example",
                          "unresolved reference: $CPP_DIR/templates/makefiles"}


def test_the_cicd_init_config_template_is_installed_and_its_removal_refused(tmp_path: Path) -> None:
    """cicd-init/reference.md:104 generates the project's cicd.yml from
    templates/cicd.yml.example - a bare relative path no reference pattern
    reads, so the closure must carry it by declaration. Removing it from the
    source must refuse, never install a closure without it."""
    prof = p.Profile.load(SUBJECT_DIR / "profile.json")
    tree = p.load_tree(prof, None, SNAPSHOT)
    installed = p.installed_home_files(p.validate(prof, tree), tree)
    template = "Projects/claude-power-pack/templates/cicd.yml.example"
    assert installed[template] == (SNAPSHOT / "templates" / "cicd.yml.example").read_bytes()
    assert "templates/cicd.yml.example" in _installed_reference(installed, "cicd-init")
    stripped = tmp_path / "snapshot"
    shutil.copytree(SNAPSHOT, stripped)
    (stripped / "templates" / "cicd.yml.example").unlink()
    with pytest.raises(p.Refused, match="cicd.yml.example"):
        p.validate(prof, p.load_tree(prof, None, stripped))


def _installed_reference(installed: dict[str, bytes], skill: str) -> str:
    return installed[f".codex/skills/{skill}/reference.md"].decode("utf-8")


def test_an_undeclared_ambient_checkout_is_unresolved_never_borrowed() -> None:
    """`~/.claude-power-pack` exists on many operator hosts; the profile must
    neither supply nor silently tolerate it."""
    raw = _json(SUBJECT_DIR / "profile.json")
    unsupported = [u for u in raw["unsupported"] if u["reference"] != "~/.claude-power-pack"]
    problems = _problems(_profile(unsupported=unsupported))
    assert {prob["category"] for prob in problems} == {"unresolved-reference"}
    assert all("~/.claude-power-pack" in prob["detail"] for prob in problems)
    assert len(problems) == 5  # one per skill that probes it


def _curl_probe() -> dict[str, Any]:
    dep, = [dep for dep in _json(SUBJECT_DIR / "profile.json")["dependencies"] if dep["id"] == "tool-curl"]
    probe: dict[str, Any] = dep["probes"][0]
    return probe


@pytest.mark.parametrize(("outcome", "status"), [
    (p.CommandProbeOutcome(present=True, version_output="curl 7.88.1 (x86_64-pc-linux-gnu)", version_exit_code=0),
     "satisfied"),
    (p.CommandProbeOutcome(present=False), "violated"),
    (p.CommandProbeOutcome(present=True, version_output="curl 6.1.0 (stub)", version_exit_code=0), "violated"),
], ids=["present", "missing", "wrong-version"])
def test_curl_is_satisfied_only_when_present_at_a_supported_version(outcome: p.CommandProbeOutcome,
                                                                    status: str) -> None:
    assert p.evaluate_command_probe(_curl_probe(), outcome)["status"] == status


def test_a_tool_with_no_probes_is_refused_before_any_container_call() -> None:
    class NoBackend:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"preflight touched the backend ({name}) before refusing")

    tool = {**copy.deepcopy(_json(SUBJECT_DIR / "profile.json")["dependencies"][-1]), "probes": []}
    with pytest.raises(at.HomeFileVerificationRefused, match="'tool-curl' declares no probes"):
        at._preflight_in_container(NoBackend(), object(), None, {"x": "sha256:" + "0" * 64}, [tool])  # type: ignore[arg-type]


def _selection(subject_dir: Path, snapshot: Path) -> str | None:
    prof = p.Profile.load(subject_dir / "profile.json")
    tree = p.load_tree(prof, None, snapshot)
    inventory = p.validate(prof, tree)
    files = {k: m.sha256_bytes(v) for k, v in p.installed_home_files(inventory, tree).items()}
    tools = [dep for dep in inventory["dependencies"] if dep["kind"] == "tool"]
    subject = _json(subject_dir / "subject.json")
    return rs.selected_runtime(locator=subject["locator"], revision=subject["revision"],
                               gate_entrypoint=inventory["gate_entrypoint"], files=files, tools=tools)


def test_each_real_closure_selects_its_own_runtime() -> None:
    assert _selection(SUBJECT_DIR, SNAPSHOT) == rs.CICD_RUNTIME
    assert _selection(FLOW_CHECK_DIR, FLOW_CHECK_SNAPSHOT) == rs.PROFILE_RUNTIME


def _freezer() -> Any:
    spec = importlib.util.spec_from_file_location("freeze_cpp_fixture", ROOT / "scripts" / "freeze_cpp_fixture.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_pin() -> bool:
    """A claude-power-pack clone holding the pin. Only consulted where git
    exists: a missing git is its own skip, named as git (ci/check_git_tests_ran.py
    refuses that in CI, where git is installed); a missing clone is not git."""
    if shutil.which("git") is None or not CPP_CHECKOUT.is_dir():
        return False
    return subprocess.run(["git", "-C", str(CPP_CHECKOUT), "cat-file", "-e", f"{PIN}^{{commit}}"],
                          capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
@pytest.mark.skipif(shutil.which("git") is not None and not _has_pin(),
                    reason="no claude-power-pack clone holding the pin at ~/Projects/claude-power-pack")
def test_the_snapshot_is_reproducible_from_the_pin_and_a_drift_is_named(tmp_path: Path) -> None:
    freezer = _freezer()
    assert freezer.check("profile-cpp-codex-cicd-86641e8", CPP_CHECKOUT, SNAPSHOT) == []
    copy_dir = tmp_path / "snapshot"
    shutil.copytree(SNAPSHOT, copy_dir)
    target = copy_dir / "lib" / "cicd" / "health.py"
    target.write_bytes(target.read_bytes() + b"\n")
    (copy_dir / "extra.txt").write_text("x")
    assert freezer.check("profile-cpp-codex-cicd-86641e8", CPP_CHECKOUT, copy_dir) == [
        "extra: extra.txt", "differs: lib/cicd/health.py"]


def _provider_docs(github_runs: list[str], woodpecker_commands: list[str]) -> dict[str, Any]:
    return {"github": {"jobs": {"ci": {"steps": [{"uses": "actions/checkout@v4"},
                                                 *({"run": r} for r in github_runs)]}}},
            "woodpecker": {"steps": [{"name": "s", "commands": woodpecker_commands}]}}


def test_provider_make_targets_use_a_bounded_grammar() -> None:
    """The live test's provider comparison: `make lint deploy` must be refused,
    never read as `lint`; a separate `make deploy` must show up as a target."""
    from test_cicd_profile_live import _make_targets

    generated = _provider_docs(["pip install uv\nuv sync\n", "make lint", "make test", "make typecheck"],
                               ["pip install uv", "uv sync", "make lint", "make test", "make typecheck"])
    assert _make_targets(generated) == {"github": {"lint", "test", "typecheck"},
                                        "woodpecker": {"lint", "test", "typecheck"}}
    with pytest.raises(AssertionError, match="unsupported make command"):
        _make_targets(_provider_docs(["make lint deploy", "make test", "make typecheck"], []))
    with pytest.raises(AssertionError, match="unsupported make command"):
        _make_targets(_provider_docs([], ["make -C sub lint"]))
    extra = _make_targets(_provider_docs(["make lint", "make test", "make typecheck", "make deploy"], []))
    assert extra["github"] == {"lint", "test", "typecheck", "deploy"}


def test_the_live_teardown_removes_only_images_it_created() -> None:
    """#414's shared-host rule for tests/test_cicd_profile_live.py: an image
    that existed before the run, even one the run's own cached build returned,
    is never removed."""
    from test_cicd_profile_live import _images_to_remove

    base, layered, other = ("sha256:" + c * 64 for c in "bcd")
    assert _images_to_remove(set(), [layered, base]) == [layered, base]
    assert _images_to_remove({base, other}, [layered, base]) == [layered]
    assert _images_to_remove({base, layered}, [layered, base]) == []
    assert _images_to_remove(set(), [layered, layered]) == [layered]


def test_an_unlocked_live_run_removes_nothing() -> None:
    """Only run-real-docker's run.lock makes "absent from my snapshot" mean
    "mine" (#414). Unlocked, even images the run plainly built stay."""
    from test_cicd_profile_live import _release_images

    base, layered = "sha256:" + "b" * 64, "sha256:" + "c" * 64
    removed: list[str] = []
    assert _release_images(set(), [layered, base], lock_held=False, remove=removed.append) == []
    assert removed == []
    assert _release_images({base}, [layered, base], lock_held=True, remove=removed.append) == [layered]
    assert removed == [layered]
