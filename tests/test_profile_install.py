"""Host installation controls against one committed synthetic snapshot.

The ambient control catches fallback through the caller-supplied home argument.
It cannot observe a helper reading an absolute real-home path directly. strace
is unavailable here, so that boundary is unobserved. HOME redirection below
proves the tiny consuming path only, not container isolation.

Human-only real-pin proof: see profiles.md. It needs a real checkout, network
for locked package resolution, and a subsequent cold-container run. No test
here downloads or runs that subject.
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

FIXTURE = Path(__file__).parent / "fixtures" / "profile-install"


@pytest.fixture
def setup(tmp_path: Path) -> tuple[dict[str, Any], p.Tree, Path]:
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    prof = p.Profile.load(source / "profile.json")
    tree = p.DirTree(source)
    home = tmp_path / "home"
    home.mkdir()
    return p.validate(prof, tree), tree, home


def test_valid_installation(setup: tuple[dict[str, Any], p.Tree, Path], tmp_path: Path) -> None:
    inventory, tree, home = setup
    receipt = p.install(inventory, tree, home)
    for record in p._install_records(inventory):
        target = home / record["destination"]
        assert target.read_bytes() == tree.read(record["source"])
        assert target.stat().st_mode & 0o777 == (0o755 if record["mode"] == "100755" else 0o644)
    assert receipt["installed_surface"] == inventory["installed_surface"]
    assert receipt["tools"][0]["status"] == "satisfied"
    body = {k: v for k, v in receipt.items() if k != "digest"}
    assert receipt["digest"] == p.m.sha256_bytes(p._canonical(body))
    assert str(home) not in json.dumps(receipt)
    assert all(r["status"] == "satisfied" for r in p.verify_installed(inventory, home)["files"])
    project = tmp_path / "project"
    project.mkdir()
    (project / "ready.txt").touch()
    run = subprocess.run([str(home / ".helpers/run.sh"), str(project)],
                         env={"HOME": str(home), "PATH": os.defpath},
                         capture_output=True, check=False)
    assert run.returncode == 0 and run.stdout == b"READY\n"
    # Baseline task readiness needs no installed skill or helper.
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    assert (project / "ready.txt").is_file() and not (baseline / ".helpers").exists()


@pytest.mark.parametrize("source_file", ["helpers/run.sh", "library/common.sh"])
def test_missing_dependency(tmp_path: Path, source_file: str) -> None:
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    (source / source_file).unlink()
    with pytest.raises(p.Refused, match="absent|missing"):
        p.validate(p.Profile.load(source / "profile.json"), p.DirTree(source))


def test_wrong_tool_version(setup: tuple[dict[str, Any], p.Tree, Path]) -> None:
    inventory, tree, home = setup
    inventory = copy.deepcopy(inventory)
    inventory["dependencies"][-1]["version"] = ">=99.0"
    assert p.install(inventory, tree, home)["tools"][0]["status"] == "violated"


def test_ambient_host_only_dependency(setup: tuple[dict[str, Any], p.Tree, Path],
                                     tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inventory, tree, home = setup
    operator = tmp_path / "fake-operator"
    real_home = Path.home().resolve()
    fake_home = operator.resolve()
    assert fake_home != real_home
    assert real_home not in fake_home.parents and fake_home not in real_home.parents
    destination = ".helpers/run.sh"
    decoy = b"DECOY - fake operator home, must never be read"
    (operator / destination).parent.mkdir(parents=True)
    (operator / destination).write_bytes(decoy)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: operator))
    receipt = p.install(inventory, tree, home)
    assert decoy.decode() not in json.dumps(receipt)
    assert all(decoy not in f.read_bytes() for f in home.rglob("*") if f.is_file())
    assert (home / destination).read_bytes() == tree.read("helpers/run.sh")


def test_stray_preexisting_file(setup: tuple[dict[str, Any], p.Tree, Path]) -> None:
    inventory, tree, home = setup
    target = home / ".helpers/run.sh"
    target.parent.mkdir()
    target.write_bytes(b"stray")
    with pytest.raises(p.Refused, match=r"different pre-existing destination: \.helpers/run.sh"):
        p.install(inventory, tree, home)
    assert target.read_bytes() == b"stray"


def test_identical_preexisting_file(setup: tuple[dict[str, Any], p.Tree, Path]) -> None:
    inventory, tree, home = setup
    target = home / ".helpers/run.sh"
    target.parent.mkdir()
    target.write_bytes(tree.read("helpers/run.sh"))
    receipt = p.install(inventory, tree, home)
    assert receipt["preexisting"] == [".helpers/run.sh"]
    assert target.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("change,expected", [("bytes", "violated"), ("mode", "violated"),
                                            ("delete", "unknown")])
def test_profile_drift(setup: tuple[dict[str, Any], p.Tree, Path], change: str, expected: str) -> None:
    inventory, tree, home = setup
    p.install(inventory, tree, home)
    target = home / ".helpers/run.sh"
    if change == "bytes":
        target.write_bytes(b"drift")
    elif change == "mode":
        target.chmod(0o644)
    else:
        target.unlink()
    results = p.verify_installed(inventory, home)["files"]
    assert len(results) == inventory["installed_surface"]["files"]
    assert {r["destination"]: r["status"] for r in results} == {
        r["destination"]: expected if r["destination"] == ".helpers/run.sh" else "satisfied"
        for r in p._install_records(inventory)}


def test_source_digest_changed(setup: tuple[dict[str, Any], p.Tree, Path]) -> None:
    inventory, tree, home = setup
    assert isinstance(tree, p.DirTree)
    (tree.root / "helpers/run.sh").write_bytes(b"changed after validation")
    with pytest.raises(p.Refused, match="source digest changed"):
        p.install(inventory, tree, home)
    assert not list(home.iterdir())


@pytest.mark.parametrize("kind", ["absent", "file", "symlink"])
def test_invalid_home(setup: tuple[dict[str, Any], p.Tree, Path], kind: str) -> None:
    inventory, tree, home = setup
    home.rmdir()
    if kind == "file":
        home.touch()
    elif kind == "symlink":
        home.symlink_to(FIXTURE.resolve(), target_is_directory=True)
    with pytest.raises(p.Refused, match="existing directory"):
        p.install(inventory, tree, home)


def test_linked_destination(setup: tuple[dict[str, Any], p.Tree, Path], tmp_path: Path) -> None:
    inventory, tree, home = setup
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / ".helpers").symlink_to(outside, target_is_directory=True)
    with pytest.raises(p.Refused, match="symlink at destination"):
        p.install(inventory, tree, home)
    assert not list(outside.iterdir())


def test_missing_tool(setup: tuple[dict[str, Any], p.Tree, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    inventory, tree, home = setup
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = p.install(inventory, tree, home)["tools"][0]
    assert result["status"] == "unknown" and result["reason"] == "missing on PATH"


def test_cli_install(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "receipt.json"
    args = ["profile", "install", str(FIXTURE / "profile.json"), "--snapshot", str(FIXTURE),
            "--home", str(home), "--out", str(out)]
    assert cli.main(args) == 0
    assert json.loads(out.read_text())["files"]
    assert cli.main(args) == 2
    assert cli.main([*args, "--overwrite"]) == 0


def test_cli_refuses_failed_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "receipt.json"
    monkeypatch.setattr(p, "verify_installed", lambda *a: {"files": [{"status": "violated"}]})
    assert cli.main(["profile", "install", str(FIXTURE / "profile.json"), "--snapshot",
                     str(FIXTURE), "--home", str(home), "--out", str(out)]) == 2
    assert not out.exists()
