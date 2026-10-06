"""Committed fake-source controls; no real client or external checkout."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from skillc import profile as p

FIXTURE = Path(__file__).parent / "fixtures/profile-install-synthetic"
CLASSIFIER = (Path(__file__).resolve().parents[1]
              / "evals/subjects/cpp-codex-flow-check/gate_path.py")
spec = importlib.util.spec_from_file_location("subject_gate_path", CLASSIFIER)
assert spec is not None and spec.loader is not None
classifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classifier)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    return source


def change(source: Path, **fields: Any) -> None:
    path = source / "profile.json"
    data = json.loads(path.read_text())
    data["dependencies"][1].update(fields)
    path.write_text(json.dumps(data))


def inventory(source: Path) -> tuple[dict[str, Any], p.Tree]:
    tree = p.DirTree(source)
    return p.validate(p.Profile.load(source / "profile.json"), tree), tree


def installed(source: Path, tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    inv, tree = inventory(source)
    home = tmp_path / "home"
    home.mkdir()
    return inv, p.install(inv, tree, home), home


def test_valid_synthetic_install(source: Path, tmp_path: Path) -> None:
    inv, receipt, home = installed(source, tmp_path)
    target = home / "checkout/MARKER.md"
    assert target.read_bytes() == b"# Synthetic marker\n"
    assert target.stat().st_mode & 0o7777 == 0o644
    record = next(r for r in receipt["files"] if r["origin"] == "synthetic")
    assert record["mode"] == "100644"
    assert record["replaces_pinned_digest"] is None
    assert all(r["status"] == "satisfied" for r in p.verify_installed(inv, home)["files"])


def test_receipt_distinguishes_origins(source: Path, tmp_path: Path) -> None:
    _, receipt, _ = installed(source, tmp_path)
    by_origin = {
        origin: {r["destination"] for r in receipt["files"] if r["origin"] == origin}
        for origin in ("synthetic", "pinned")
    }
    assert by_origin["synthetic"] == {"checkout/MARKER.md"}
    assert by_origin["pinned"] == {".codex/skills/tiny-check/SKILL.md", "checkout/gate.py"}


@pytest.mark.parametrize("replaces", [False, None])
def test_undeclared_shadow_refused(source: Path, replaces: bool | None) -> None:
    # paths[0] names BOTH where this installs (destination/paths[0]) and what
    # it shadows (source_root/paths[0]) - the review finding this fixture
    # exists to pin: a destination and a shadow-check that could be declared
    # independently is exactly the gap that let a shadowing substitution pass
    # silently. Pointing paths at a real pinned file is now the ONLY way to
    # exercise the shadow path at all.
    change(source, paths=["INSTRUCTIONS.md"])
    if replaces is not None:
        change(source, replaces_pinned=replaces)
    with pytest.raises(p.Refused, match="silently substitute.*INSTRUCTIONS.md"):
        inventory(source)


def test_declared_replacement(source: Path, tmp_path: Path) -> None:
    change(source, paths=["INSTRUCTIONS.md"],
           replaces_pinned=True, replacement_reason="Exclude instructions, preserve existence")
    inv, receipt, home = installed(source, tmp_path)
    expected = "sha256:" + hashlib.sha256(p.DirTree(source).read("INSTRUCTIONS.md")).hexdigest()
    record = next(r for r in receipt["files"] if r["origin"] == "synthetic")
    assert record["replaces_pinned_digest"] == expected
    assert inv["dependencies"][1]["files"][0]["replaces_pinned_digest"] == expected
    assert (home / "checkout/INSTRUCTIONS.md").read_text() == "# Synthetic marker\n"


def test_destination_collision_uses_claim(source: Path) -> None:
    # Redirect source_root away from "." so the shadow-check (source_root/
    # paths[0]) finds nothing, isolating this from test_undeclared_shadow_
    # refused above: this test is purely about _claim()'s own destination-
    # collision refusal, not the shadow check.
    change(source, source_root="nonexistent-subdir", paths=["gate.py"])
    with pytest.raises(p.Refused, match=(
        "^conflicting destination checkout/gate.py: claimed by gate and marker with different content$"
    )):
        inventory(source)


def test_shadow_cannot_diverge_from_destination(source: Path, tmp_path: Path) -> None:
    """The review finding itself, as a positive demonstration: paths[0] is
    the ONLY relative-path value an author supplies, so the installed
    destination (destination/paths[0]) and the shadow check
    (source_root/paths[0]) can never name different files - there is no
    field left to point them apart. Confirmed here by installing against
    a path that IS real (INSTRUCTIONS.md) and checking both halves land on
    the identical relative name."""
    change(source, paths=["INSTRUCTIONS.md"],
           replaces_pinned=True, replacement_reason="Exclude instructions, preserve existence")
    inv, _, home = installed(source, tmp_path)
    record = inv["dependencies"][1]["files"][0]
    assert record["destination"].rsplit("/", 1)[-1] == "INSTRUCTIONS.md"
    assert (home / "checkout" / "INSTRUCTIONS.md").exists()


@pytest.mark.parametrize("field,value", [("mode", "100755"), ("executable", True)])
def test_executable_refused(source: Path, field: str, value: object) -> None:
    change(source, **{field: value})
    with pytest.raises(p.Refused, match="unknown keys"):
        inventory(source)


@pytest.mark.parametrize("content", ["x" * 4097, "é" * 2049, "\ud800", "x\0y"],
                         ids=["ascii-limit", "utf8-limit", "surrogate", "nul"])
def test_bounded_text(source: Path, content: str) -> None:
    change(source, content=content)
    with pytest.raises(p.Refused, match="exceeds|UTF-8|NUL"):
        inventory(source)


@pytest.mark.parametrize("fields", [
    {"replaces_pinned": True},
    {"replaces_pinned": "true"},
    {"source_root": ".."},
    {"paths": ["../marker"]},
    {"paths": ["a", "b"]},
    {"paths": []},
    {"unreferenced_reason": ""},
    {"role": ""},
    {"satisfies": ["~/checkout/MARKER.md"]},
])
def test_invalid_schema(source: Path, fields: dict[str, Any]) -> None:
    change(source, **fields)
    with pytest.raises(p.Refused):
        inventory(source)


@pytest.mark.parametrize("text,expected", [
    (classifier.REAL + " fake)", "real-runner"),
    (classifier.FALLBACK_NOTE + "   -   " + classifier.FALLBACK_ACTION, "fallback"),
    ("", "unknown"),
    (classifier.REAL.replace("deterministic", "reliable"), "unknown"),
    (classifier.REAL[:-5], "unknown"),
    (classifier.FALLBACK_NOTE + "\n" + classifier.FALLBACK_ACTION, "unknown"),
    (classifier.REAL + "\n" + classifier.FALLBACK_NOTE + classifier.FALLBACK_ACTION, "unknown"),
])
def test_classifier(text: str, expected: str) -> None:
    assert classifier.classify_gate_output(text) == expected


@pytest.mark.parametrize("marker,expected", [(True, "real-runner"), (False, "fallback")])
def test_gate_path_recorded(source: Path, tmp_path: Path, marker: bool, expected: str) -> None:
    if not marker:
        path = source / "profile.json"
        data = json.loads(path.read_text())
        data["dependencies"].pop()
        path.write_text(json.dumps(data))
    _, _, home = installed(source, tmp_path)
    run = subprocess.run([sys.executable, str(home / "checkout/gate.py")],
                         env={"HOME": str(home), "PATH": os.defpath},
                         capture_output=True, text=True, check=True)
    observation = {"output": run.stdout, "gate_path": classifier.classify_gate_output(run.stdout)}
    (tmp_path / "gate-observation.json").write_text(json.dumps(observation))
    assert json.loads((tmp_path / "gate-observation.json").read_text())["gate_path"] == expected
