"""Tests for `skillc profile validate` (#265).

Every refusal the profile spec names is driven by a committed known-bad input
here, beside the known-good one it departs from: a validator proven only on the
valid case would report the same green after going blind. The fixtures are
directory snapshots built per test, because CI has no git; the one git test
skips there and SAYS so, and is run on the host before merge.

The unrelated-collection control declares a different layout, different helper
conventions and different install roots, and validates with no change to the
module - the proof that nothing in `skillc/profile.py` branches on one subject.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from skillc import cli
from skillc import profile as p

REPO = Path(__file__).resolve().parent.parent
CPP_PROFILE = REPO / "evals" / "subjects" / "cpp-codex-flow-check" / "profile.json"
CPP_INVENTORY = REPO / "evals" / "subjects" / "cpp-codex-flow-check" / "evidence" / "inventory.json"

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


# ------------------------------------------------------------------ fixture

SKILL_MD = """---
name: gate-check
description: Run the project's gates without committing
---
# Gate check

Follow [the procedure](procedure.md) exactly.
"""

PROCEDURE = """# Procedure

Run `~/.helpers/run-gate.sh --summary`.
The checkout is found at ~/Work/kit, or `/opt/kit` on shared hosts.
Its core lives at $KIT_DIR/lib/core/__init__.py.
"""

RUN_GATE = """#!/usr/bin/env bash
# sources its library from the installed helper directory
. ~/.helpers/common.sh
"""

COMMON = "#!/usr/bin/env bash\ngate() { :; }\n"


def _write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)


def _source(root: Path) -> Path:
    """A small subject source with one transitive edge: procedure.md ->
    run-gate.sh -> common.sh. common.sh is reachable ONLY through run-gate.sh."""
    _write(root / "pack" / "skills" / "gate-check" / "SKILL.md", SKILL_MD)
    _write(root / "pack" / "skills" / "gate-check" / "procedure.md", PROCEDURE)
    _write(root / "pack" / "skills" / "gate-check" / "scripts" / "run-gate.sh", RUN_GATE, True)
    _write(root / "pack" / "skills" / "other" / "SKILL.md",
           "---\nname: other\ndescription: An unrelated neighbour\n---\nNothing to see.\n")
    _write(root / "tools" / "run-gate.sh", RUN_GATE, True)
    _write(root / "tools" / "common.sh", COMMON, True)
    _write(root / "lib" / "core" / "__init__.py", "VALUE = 1\n")
    _write(root / "lib" / "core" / "deep.py", "# mentions ~/.never/looked-at.sh\n")
    _write(root / "pyproject.toml", "[project]\nname = 'kit'\n")
    return root


SUBJECT = {
    "subject_schema": 1,
    "locator": "example.invalid/kit",
    "revision": "0" * 40,
    "surface": "codex-skills",
    "skills_root": "pack/skills",
    "select": "all",
    "client": {"name": "codex", "version": "0.157.1"},
}

PROFILE: dict[str, object] = {
    "profile_schema": 1,
    "name": "kit-gate-check",
    "subject": "subject.json",
    "select": ["gate-check"],
    "treatment_question": "product",
    "allowed_destinations": [".codex/skills", ".helpers", "Work/kit"],
    "reference_patterns": [
        {"name": "home", "class": "home-relative",
         "pattern": r"~/[A-Za-z0-9._/-]*[A-Za-z0-9_-]"},
        {"name": "kit-dir", "class": "variable-rooted",
         "pattern": r"\$KIT_DIR/[A-Za-z0-9._/-]*[A-Za-z0-9_-]"},
        {"name": "abs", "class": "absolute",
         "pattern": r"(?<![\w.~}$/-])/opt/[A-Za-z0-9._/-]*[A-Za-z0-9_-]"},
    ],
    "dependencies": [
        {"id": "helper-run-gate", "kind": "helper", "scope": "treatment",
         "source_root": "tools", "paths": ["run-gate.sh"], "destination": ".helpers",
         "satisfies": [{"reference": "~/.helpers/run-gate.sh", "path": "run-gate.sh"}]},
        {"id": "helper-common", "kind": "helper", "scope": "treatment",
         "source_root": "tools", "paths": ["common.sh"], "destination": ".helpers",
         "satisfies": [{"reference": "~/.helpers/common.sh", "path": "common.sh"}]},
        {"id": "kit-checkout", "kind": "library", "scope": "treatment",
         "paths": ["pyproject.toml", "lib/core"], "destination": "Work/kit",
         "traverse": False, "no_traverse_reason": "python imports, not path text",
         "satisfies": [
             {"reference": "~/Work/kit", "path": None},
             {"reference": "$KIT_DIR/lib/core/__init__.py", "path": "lib/core/__init__.py"},
         ]},
        {"id": "tool-bash", "kind": "tool", "scope": "common", "version": "any",
         "supply": "the image", "unreferenced_reason": "a command word"},
    ],
    "unsupported": [
        {"reference": "/opt/kit", "reason": "absolute alternative location outside any home"},
    ],
    "mirrors": [
        {"generated": "pack/skills/gate-check/scripts/run-gate.sh", "source": "tools/run-gate.sh"},
    ],
    "generated_from": [],
    "declared_empty_kinds": ["startup-context"],
    "client_profiles": {
        "codex": {"status": "declared", "reason": "the subject's own surface"},
        "claude-code": {"status": "unsupported", "reason": "another surface"},
    },
}


def _profile(tmp_path: Path, subject: dict[str, Any] | None = None,
             **changes: Any) -> p.Profile:
    data = copy.deepcopy(PROFILE)
    data.update(changes)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "subject.json").write_text(json.dumps(subject or SUBJECT), encoding="utf-8")
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return p.Profile.load(path)


def _run(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    src = tmp_path / "src"
    if not src.exists():
        _source(src)
    return p.validate(_profile(tmp_path, **changes), p.DirTree(src))


def _deps() -> list[dict[str, Any]]:
    deps = copy.deepcopy(PROFILE["dependencies"])
    assert isinstance(deps, list)
    return deps


# --------------------------------------------------------- the known-good case


def test_a_valid_transitive_profile_yields_a_closed_inventory(tmp_path: Path) -> None:
    inv = _run(tmp_path)
    assert inv["treatment"] == "targeted"
    assert inv["treatment_question"] == "product"
    assert inv["selection"] == ["gate-check"]
    deps = {d["id"]: d for d in inv["dependencies"]}
    # Transitive: common.sh is named only inside run-gate.sh, never by the skill.
    assert deps["helper-common"]["referenced_by"] == [
        "pack/skills/gate-check/scripts/run-gate.sh", "tools/run-gate.sh",
    ]
    assert [f["destination"] for f in deps["helper-common"]["files"]] == [".helpers/common.sh"]
    # Every installed file carries a content digest and its mode.
    lib = deps["kit-checkout"]
    assert lib["traversed"] is False and lib["no_traverse_reason"]
    assert {f["destination"] for f in lib["files"]} == {
        "Work/kit/pyproject.toml", "Work/kit/lib/core/__init__.py", "Work/kit/lib/core/deep.py",
    }
    assert all(str(f["digest"]).startswith("sha256:") for f in lib["files"])
    # git's own identity for the same bytes, so a blob-keyed inventory can be cross-checked.
    assert {f["git_blob"] for f in lib["files"]} >= {p.git_blob_id(b"VALUE = 1\n")}
    assert inv["mirrors"][0]["status"] == "identical"
    assert inv["unsupported"] == [
        {"reference": "/opt/kit", "reason": "absolute alternative location outside any home"},
    ]
    skill = inv["skills"][0]
    assert skill["required_references"] == ["procedure.md"]
    assert str(skill["description_digest"]).startswith("sha256:")
    assert inv["helper_parity"] == {
        "common": ["tool-bash"], "treatment": ["helper-common", "helper-run-gate", "kit-checkout"],
        "bundled": [{"path": "pack/skills/gate-check/scripts/run-gate.sh", "supplied_by": None}],
    }
    assert "installation into any home" in inv["does_not_establish"]


def test_an_untraversed_library_is_recorded_not_followed(tmp_path: Path) -> None:
    """deep.py mentions ~/.never/looked-at.sh, which nothing satisfies. With
    traverse false that is NOT an unresolved reference - and the inventory says
    the tree was not traversed, so the hole is visible rather than silent."""
    inv = _run(tmp_path)
    assert not any(r["reference"] == "~/.never/looked-at.sh" for r in inv["references"])
    deps = _deps()
    deps[2]["traverse"] = True
    deps[2].pop("no_traverse_reason")
    with pytest.raises(p.Refused, match=r"unresolved reference.*~/.never/looked-at.sh"):
        _run(tmp_path / "t", dependencies=deps)


def test_full_pack_selects_every_skill(tmp_path: Path) -> None:
    inv = _run(tmp_path, select="all")
    assert inv["treatment"] == "full-pack"
    assert inv["selection"] == ["gate-check", "other"]


# ------------------------------------------------------- the refusals (red cases)


def test_empty_selection_is_refused(tmp_path: Path) -> None:
    with pytest.raises(p.Refused, match="empty selection"):
        _run(tmp_path, select=[])


def test_a_missing_reference_is_refused(tmp_path: Path) -> None:
    src = _source(tmp_path / "src")
    (src / "pack" / "skills" / "gate-check" / "procedure.md").unlink()
    with pytest.raises(p.Refused, match=r"references missing file.*procedure.md"):
        _run(tmp_path)


def test_a_missing_helper_is_refused(tmp_path: Path) -> None:
    src = _source(tmp_path / "src")
    (src / "tools" / "common.sh").unlink()
    with pytest.raises(p.Refused, match=r"missing helper helper-common: tools/common.sh"):
        _run(tmp_path)


def test_a_reference_into_a_library_file_it_does_not_carry_is_refused(tmp_path: Path) -> None:
    deps = _deps()
    deps[2]["paths"] = ["pyproject.toml"]
    with pytest.raises(p.Refused, match=r"missing library file.*lib/core/__init__.py"):
        _run(tmp_path, dependencies=deps)


def test_a_stale_mirror_is_refused(tmp_path: Path) -> None:
    src = _source(tmp_path / "src")
    (src / "tools" / "run-gate.sh").write_text(RUN_GATE + "# upstream moved on\n", encoding="utf-8")
    with pytest.raises(p.Refused, match="stale mirror.*bytes differ"):
        _run(tmp_path)


def test_a_mirror_whose_mode_drifted_is_stale(tmp_path: Path) -> None:
    src = _source(tmp_path / "src")
    (src / "tools" / "run-gate.sh").chmod(0o644)
    with pytest.raises(p.Refused, match="stale mirror.*modes differ"):
        _run(tmp_path)


def test_two_dependencies_claiming_one_destination_conflict(tmp_path: Path) -> None:
    deps = _deps()
    deps.append({"id": "rogue", "kind": "helper", "scope": "treatment", "source_root": "tools",
                 "paths": ["common.sh"], "destination": ".helpers",
                 "unreferenced_reason": "planted"})
    with pytest.raises(p.Refused, match="conflicting destination .helpers/common.sh"):
        _run(tmp_path, dependencies=deps)


def test_a_dependency_overwriting_a_skill_file_conflicts(tmp_path: Path) -> None:
    deps = _deps()
    deps.append({"id": "rogue", "kind": "helper", "scope": "treatment", "source_root": "tools",
                 "paths": ["run-gate.sh"], "destination": ".codex/skills/gate-check/scripts",
                 "unreferenced_reason": "planted"})
    with pytest.raises(p.Refused, match="conflicting destination .codex/skills/gate-check/scripts/run-gate.sh"):
        _run(tmp_path, dependencies=deps)


def test_an_unresolved_reference_is_refused(tmp_path: Path) -> None:
    with pytest.raises(p.Refused, match=r"unresolved reference.*/opt/kit.*absolute"):
        _run(tmp_path, unsupported=[])


def test_an_absolute_path_cannot_be_satisfied_by_an_installation(tmp_path: Path) -> None:
    deps = _deps()
    deps[2]["satisfies"].append({"reference": "/opt/kit", "path": None})
    with pytest.raises(p.Refused, match="absolute reference /opt/kit.*declare it unsupported"):
        _run(tmp_path, dependencies=deps, unsupported=[])


def test_a_destination_outside_the_allowed_roots_is_refused(tmp_path: Path) -> None:
    with pytest.raises(p.Refused, match="destination Work/kit/.* is outside allowed_destinations"):
        _run(tmp_path, allowed_destinations=[".codex/skills", ".helpers"])


def test_prose_requires_helper_parity(tmp_path: Path) -> None:
    with pytest.raises(p.Refused, match="helper parity"):
        _run(tmp_path, treatment_question="prose")
    deps = _deps()
    for dep in deps:
        dep["scope"] = "common"
    inv = _run(tmp_path / "parity", treatment_question="prose", dependencies=deps)
    assert inv["helper_parity"]["treatment"] == []
    # The bundled copy reaches the expanded-instruction arm through the common helper.
    assert inv["helper_parity"]["bundled"] == [
        {"path": "pack/skills/gate-check/scripts/run-gate.sh", "supplied_by": "helper-run-gate"},
    ]


def test_prose_parity_needs_the_same_mode_not_only_the_same_bytes(tmp_path: Path) -> None:
    """Codex re-review, #265: identical bytes, executable in the skill arm only."""
    src = _source(tmp_path / "src")
    deps = _deps()
    for dep in deps:
        dep["scope"] = "common"
    deps[0]["source_root"] = "plain"
    _write(src / "plain" / "run-gate.sh", RUN_GATE, executable=False)
    with pytest.raises(p.Refused, match=r"bundled file\(s\) \['pack/skills/gate-check/scripts/run-gate.sh'\]"):
        _run(tmp_path, treatment_question="prose", dependencies=deps)


def test_prose_refuses_a_bundled_helper_only_the_skill_arm_has(tmp_path: Path) -> None:
    """Codex review, #265: every explicit dependency common, but a non-Markdown
    file lives only inside the skill - the expanded-instruction arm never gets it."""
    src = _source(tmp_path / "src")
    _write(src / "pack" / "skills" / "gate-check" / "scripts" / "lint.sh", "#!/bin/sh\n", True)
    deps = _deps()
    for dep in deps:
        dep["scope"] = "common"
    with pytest.raises(p.Refused, match=r"bundled file\(s\) \['pack/skills/gate-check/scripts/lint.sh'\]"):
        _run(tmp_path, treatment_question="prose", dependencies=deps)


def test_an_unreferenced_dependency_is_walked_too(tmp_path: Path) -> None:
    """Codex review, #265: a startup file the client loads by itself is seeded
    after the referenced closure - and its own references are still resolved."""
    src = _source(tmp_path / "src")
    _write(src / "startup" / "AGENTS.md", "Before anything, run ~/.helpers/missing.sh.\n")
    deps = _deps()
    deps.append({"id": "startup", "kind": "startup-context", "scope": "common",
                 "paths": ["startup/AGENTS.md"], "destination": ".codex",
                 "unreferenced_reason": "the client loads it at startup"})
    with pytest.raises(p.Refused, match=r"unresolved reference.*~/.helpers/missing.sh"):
        _run(tmp_path, dependencies=deps, declared_empty_kinds=[],
             allowed_destinations=[*PROFILE["allowed_destinations"], ".codex"])  # type: ignore[misc]
    # A dependency reached ONLY through that startup file is referenced, not padding.
    _write(src / "tools" / "missing.sh", "#!/bin/sh\n", True)
    deps.append({"id": "helper-missing", "kind": "helper", "scope": "common",
                 "source_root": "tools", "paths": ["missing.sh"], "destination": ".helpers",
                 "satisfies": [{"reference": "~/.helpers/missing.sh", "path": "missing.sh"}]})
    inv = _run(tmp_path, dependencies=deps, declared_empty_kinds=[],
               allowed_destinations=[*PROFILE["allowed_destinations"], ".codex"])  # type: ignore[misc]
    by_id = {d["id"]: d for d in inv["dependencies"]}
    assert by_id["helper-missing"]["referenced_by"] == ["startup/AGENTS.md"]


def test_a_home_reference_must_resolve_to_where_it_is_installed(tmp_path: Path) -> None:
    """Codex review, #265: `~/.helpers/run-gate.sh` satisfied by a dependency
    that installs under `.helpers/wrong/` is a path no installer could honour."""
    deps = _deps()
    deps[0]["destination"] = ".helpers/wrong"
    with pytest.raises(p.Refused, match=r"names ~/.helpers/run-gate.sh, but helper-run-gate installs it at ~/.helpers/wrong/run-gate.sh"):
        _run(tmp_path, dependencies=deps)


def test_a_tool_cannot_satisfy_a_reference(tmp_path: Path) -> None:
    """Codex re-review, #265: a tool carries no file, so a home reference it
    "satisfied" would bypass the install-path check."""
    deps = _deps()
    deps[3]["satisfies"] = [{"reference": "~/.helpers/missing.sh", "path": None}]
    with pytest.raises(p.Refused, match="tool carries no path and cannot satisfy a reference"):
        _run(tmp_path, dependencies=deps)


def test_an_unreferenced_dependency_needs_a_reason(tmp_path: Path) -> None:
    deps = _deps()
    deps[3].pop("unreferenced_reason")
    with pytest.raises(p.Refused, match="tool-bash is satisfied by no reference"):
        _run(tmp_path, dependencies=deps)


def test_an_untraversed_tree_needs_a_reason(tmp_path: Path) -> None:
    deps = _deps()
    deps[2].pop("no_traverse_reason")
    with pytest.raises(p.Refused, match="traverse is false with no no_traverse_reason"):
        _run(tmp_path, dependencies=deps)


def test_a_kind_neither_declared_nor_declared_empty_is_refused(tmp_path: Path) -> None:
    with pytest.raises(p.Refused, match=r"neither declared nor declared empty: \['startup-context'\]"):
        _run(tmp_path, declared_empty_kinds=[])


def test_no_reference_patterns_is_refused_rather_than_reading_as_closed(tmp_path: Path) -> None:
    """The blindness control: a walk with nothing to look for finds nothing."""
    with pytest.raises(p.Refused, match="reference_patterns is empty"):
        _run(tmp_path, reference_patterns=[])


@pytest.mark.parametrize("clients, message", [
    ({"codex": {"status": "declared", "reason": "x"},
      "claude-code": {"status": "declared", "reason": "x"}}, "another client needs its own readiness proof"),
    ({"codex": {"status": "ready", "reason": "x"}}, "never by a manifest"),
    ({"claude-code": {"status": "unsupported", "reason": "x"}}, "does not declare the subject's own client"),
    ({"codex": {"status": "declared"}}, "gives no reason"),
])
def test_client_profiles_cannot_claim_parity(tmp_path: Path, clients: object, message: str) -> None:
    with pytest.raises(p.Refused, match=message):
        _run(tmp_path, client_profiles=clients)


def test_a_symlink_in_the_closure_is_refused_and_one_elsewhere_is_not(tmp_path: Path) -> None:
    src = _source(tmp_path / "src")
    os.symlink("../tools", src / "elsewhere-link")
    # Codex review, #265: an unselected neighbour's ancillary link is not this
    # treatment's defect - but selecting that neighbour puts it in the closure.
    os.symlink("SKILL.md", src / "pack" / "skills" / "other" / "doc-link")
    _run(tmp_path)  # unreached links: fine
    with pytest.raises(p.Refused, match="symlink in the closure: pack/skills/other/doc-link"):
        _run(tmp_path, select="all")
    (src / "pack" / "skills" / "other" / "doc-link").unlink()
    (src / "tools" / "common.sh").unlink()
    os.symlink("run-gate.sh", src / "tools" / "common.sh")
    with pytest.raises(p.Refused, match="symlink in the closure: tools/common.sh"):
        _run(tmp_path)


def test_a_linked_skill_directory_blocks_discovery_for_any_selection(tmp_path: Path) -> None:
    src = _source(tmp_path / "src")
    os.symlink("other", src / "pack" / "skills" / "alias")
    with pytest.raises(p.Refused, match="blocks name discovery: pack/skills/alias"):
        _run(tmp_path)


def test_a_nested_example_skill_link_in_a_neighbour_does_not_block(tmp_path: Path) -> None:
    """Codex re-review, #265: `other/examples/SKILL.md` as a link does not hide
    `other`'s name (its own SKILL.md is real), so a targeted profile stays green;
    selecting `other` puts the link in the closure."""
    src = _source(tmp_path / "src")
    (src / "pack" / "skills" / "other" / "examples").mkdir()
    os.symlink("../SKILL.md", src / "pack" / "skills" / "other" / "examples" / "SKILL.md")
    _run(tmp_path)
    with pytest.raises(p.Refused, match="symlink in the closure: pack/skills/other/examples/SKILL.md"):
        _run(tmp_path, select="all")


def test_a_whole_source_dependency_refuses_a_link_anywhere(tmp_path: Path) -> None:
    """Codex re-review, #265: `paths: ["."]` reaches every entry, links included."""
    src = _source(tmp_path / "src")
    os.symlink("tools", src / "vendor-link")
    deps = _deps()
    deps[2]["paths"] = ["."]
    with pytest.raises(p.Refused, match="symlink in the closure: vendor-link"):
        _run(tmp_path, dependencies=deps)


def test_unknown_profile_keys_are_refused(tmp_path: Path) -> None:
    with pytest.raises(p.Refused, match="unknown keys"):
        _run(tmp_path, installs_everything=True)


# --------------------------------------------- the unrelated-collection control


def test_an_unrelated_collection_validates_without_a_code_branch(tmp_path: Path) -> None:
    """Different layout (skills at the source root), different helper home
    (~/.local/bin), a startup-context dependency, and no library: the same module
    validates it from data alone."""
    src = tmp_path / "other-src"
    _write(src / "summarize" / "SKILL.md",
           "---\nname: summarize\ndescription: Summarize a file\n---\nRun `~/.local/bin/wc-lite`.\n")
    _write(src / "bin" / "wc-lite", "#!/bin/sh\nwc -l \"$1\"\n", True)
    _write(src / "AGENTS.fragment.md", "Prefer short summaries.\n")
    subject = dict(SUBJECT, locator="example.invalid/unrelated", skills_root=".")
    (tmp_path / "subject.json").write_text(json.dumps(subject), encoding="utf-8")
    data = {
        "profile_schema": 1, "name": "unrelated", "subject": "subject.json",
        "select": "all", "treatment_question": "prose",
        "allowed_destinations": [".codex/skills", ".local/bin", ".codex"],
        "reference_patterns": [{"name": "home", "class": "home-relative",
                                "pattern": r"~/[A-Za-z0-9._/-]*[A-Za-z0-9_-]"}],
        "dependencies": [
            {"id": "wc-lite", "kind": "helper", "scope": "common", "source_root": "bin",
             "paths": ["wc-lite"], "destination": ".local/bin",
             "satisfies": [{"reference": "~/.local/bin/wc-lite", "path": "wc-lite"}]},
            {"id": "agents", "kind": "startup-context", "scope": "common",
             "paths": ["AGENTS.fragment.md"], "destination": ".codex",
             "unreferenced_reason": "loaded by the client at startup, not named by any file"},
            {"id": "sh", "kind": "tool", "scope": "common", "version": "posix",
             "supply": "image", "unreferenced_reason": "shebang"},
        ],
        "declared_empty_kinds": ["library"],
        "client_profiles": {"codex": {"status": "declared", "reason": "own surface"}},
    }
    (tmp_path / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    inv = p.validate(p.Profile.load(tmp_path / "profile.json"), p.DirTree(src))
    assert inv["treatment"] == "full-pack" and inv["treatment_question"] == "prose"
    assert inv["selection"] == ["summarize"]
    kinds = {d["id"]: d["kind"] for d in inv["dependencies"]}
    assert kinds == {"wc-lite": "helper", "agents": "startup-context", "sh": "tool"}


# ----------------------------------------------------------- git and the CLI


@needs_git
def test_a_git_source_matches_the_same_snapshot_and_refuses_a_wrong_pin(tmp_path: Path) -> None:
    src = _source(tmp_path / "src")
    os.symlink("../tools", src / "elsewhere-link")

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(src), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "fixture")
    sha = git("rev-parse", "HEAD")
    prof = _profile(tmp_path, subject=dict(SUBJECT, revision=sha))
    from_git = p.validate(prof, p.GitTree(src, sha))
    from_dir = p.validate(prof, p.DirTree(src))
    assert from_git["subject"]["revision"] == sha
    assert from_git["installed_surface"] == from_dir["installed_surface"]
    assert from_git["references"] == from_dir["references"]
    listed = git("rev-parse", f"{sha}:tools/common.sh")
    common = next(d for d in from_git["dependencies"] if d["id"] == "helper-common")
    assert common["files"][0]["git_blob"] == listed
    with pytest.raises(p.Refused, match="does not resolve"):
        p.GitTree(src, "1" * 40)


def test_the_cli_writes_the_inventory_and_refuses_with_exit_2(tmp_path: Path) -> None:
    _source(tmp_path / "src")
    _profile(tmp_path)
    out = tmp_path / "inv.json"
    args = ["profile", "validate", str(tmp_path / "profile.json"), "--snapshot", str(tmp_path / "src")]
    assert cli.main([*args, "--out", str(out)]) == 0
    assert json.loads(out.read_text())["profile"] == "kit-gate-check"
    assert cli.main([*args, "--out", str(out)]) == 2  # no silent overwrite
    (tmp_path / "src" / "tools" / "common.sh").unlink()
    assert cli.main([*args, "--out", str(out), "--overwrite"]) == 2


# ------------------------------------------- the committed CPP inventory evidence


def _canonical_digest(data: object) -> str:
    return p.m.sha256_bytes(p._canonical(data))


def test_the_committed_cpp_inventory_matches_its_declaration() -> None:
    """The evidence was generated from THIS profile and THIS subject: an edit to
    either without regenerating the inventory makes the digests disagree."""
    inv = json.loads(CPP_INVENTORY.read_text(encoding="utf-8"))
    declared = json.loads(CPP_PROFILE.read_text(encoding="utf-8"))
    subject = json.loads((CPP_PROFILE.parent / declared["subject"]).read_text(encoding="utf-8"))
    assert inv["profile_digest"] == _canonical_digest(declared)
    assert inv["subject"]["declaration_digest"] == _canonical_digest(subject)
    assert inv["subject"]["revision"] == subject["revision"]
    assert inv["subject"]["source_kind"] == "git"
    assert inv["selection"] == declared["select"]
    assert {r["status"] for r in inv["references"]} == {"satisfied", "unsupported"}
    assert all(m["status"] == "identical" for m in inv["mirrors"])
    # The flow-check blobs #264's case contract cites (reference.md line numbers
    # are only meaningful at THIS blob): the two inventories describe the same bytes.
    skill_blobs = {f["source"]: f["git_blob"] for f in inv["skills"][0]["files"]}
    assert skill_blobs["codex/skills/flow-check/reference.md"] == "7419d94ac36af459a8fc8f7aa21a09c28dad1c5c"
    assert skill_blobs["codex/skills/flow-check/SKILL.md"] == "3f346d144fdd5dabb8a57345da70c1dbf5461bf1"
    assert skill_blobs["codex/skills/flow-check/scripts/flow-finish-gate.sh"] == "acf48bba1a648516f6ef9d425b7c1614c2513a42"
    assert {name: c["status"] for name, c in inv["client_profiles"].items()} == {
        "codex": "declared", "claude-code": "unsupported", "browser": "unsupported",
        "security-scanner": "unsupported", "services": "unsupported",
    }


def test_the_evidence_check_sees_a_drifted_declaration() -> None:
    """Negative control for the test above: a one-field edit changes the digest."""
    declared = json.loads(CPP_PROFILE.read_text(encoding="utf-8"))
    inv = json.loads(CPP_INVENTORY.read_text(encoding="utf-8"))
    declared["select"] = ["flow-check", "flow-finish"]
    assert inv["profile_digest"] != _canonical_digest(declared)


# ------------------------------------------------------------- gate_entrypoint


def test_gate_entrypoint_defaults_to_none(tmp_path: Path) -> None:
    """Every profile before #334's mailbox-6047 field, and most after it,
    names no gate entrypoint at all - absence must mean `None`, never an
    inferred value."""
    prof = _profile(tmp_path)
    assert prof.gate_entrypoint is None
    inv = _run(tmp_path)
    assert inv["gate_entrypoint"] is None


def test_a_gate_entrypoint_installed_by_this_closure_validates(tmp_path: Path) -> None:
    inv = _run(tmp_path, gate_entrypoint=".helpers/run-gate.sh")
    assert inv["gate_entrypoint"] == ".helpers/run-gate.sh"


def test_red_case_a_gate_entrypoint_this_closure_never_installs_is_refused(tmp_path: Path) -> None:
    """Mutation check: a typo'd or stale `gate_entrypoint` must be caught
    at `validate()` time, naming the exact reason - never silently
    accepted as a fact that can never actually hold for a live attempt."""
    with pytest.raises(p.Refused, match="gate_entrypoint '.helpers/does-not-exist.sh' is not installed"):
        _run(tmp_path, gate_entrypoint=".helpers/does-not-exist.sh")


def test_gate_entrypoint_must_be_a_non_empty_string(tmp_path: Path) -> None:
    with pytest.raises(p.Refused, match="non-empty string"):
        _profile(tmp_path, gate_entrypoint="")


def test_gate_entrypoint_cannot_escape(tmp_path: Path) -> None:
    with pytest.raises(p.Refused, match="safe relative path"):
        _profile(tmp_path, gate_entrypoint="../../etc/passwd")


def test_diagnose_reports_an_unsatisfiable_gate_entrypoint_as_a_problem(tmp_path: Path) -> None:
    """`diagnose()`'s own non-strict mode (#295) must record the same
    defect as a problem, never silently drop it just because it continues
    past the first failure instead of raising."""
    src = tmp_path / "src"
    _source(src)
    prof = _profile(tmp_path, gate_entrypoint=".helpers/does-not-exist.sh")
    result = p.diagnose(prof, p.DirTree(src))
    assert any(problem["category"] == "gate-entrypoint-not-installed" for problem in result["problems"])
