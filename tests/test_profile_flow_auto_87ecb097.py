"""Source identity/closure only: this module never installs a profile on the host."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from skillc import profile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/profile-cpp-codex-flow-auto-87ecb097"
DECLARATION = ROOT / "evals/subjects/cpp-codex-flow-auto-87ecb097/profile.json"
MANIFEST = "a12dce75f62cd1784ff0d426ec1ecdeb9d790cc98f60b22e9c670986a7a44f1c"


def source_manifest(root: Path = SOURCE) -> list[dict[str, Any]]:
    rows = [{"source": p, "mode": mode, "bytes": int(size), "sha256": digest}
            for p, mode, size, digest in re.findall(
                r"^\| `([^`]+)` \| (100644|100755) \| (\d+) \| ([0-9a-f]{64}) \|$",
                (root / "README.md").read_text(), re.MULTILINE)]
    assert len(rows) == 388 and len({r["source"] for r in rows}) == 388
    rows[3]["reason"] = "preserve upstream licence notice; existing skillc553"
    assert rows[3]["source"] == "LICENSE"
    assert hashlib.sha256((json.dumps(rows, indent=2) + "\n").encode()).hexdigest() == MANIFEST
    return rows


def check_source(root: Path = SOURCE) -> None:
    rows = source_manifest(root)
    paths = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() or p.is_symlink()}
    assert paths == {r["source"] for r in rows} | {"README.md"}
    for row in rows:
        p = root / row["source"]
        assert not p.is_symlink()
        assert len(p.read_bytes()) == row["bytes"]
        assert hashlib.sha256(p.read_bytes()).hexdigest() == row["sha256"]
        assert ("100755" if p.stat().st_mode & 0o111 else "100644") == row["mode"]
    assert sum(r["bytes"] for r in rows) == 8_168_295


def declaration() -> profile.Profile:
    return profile.Profile.load(DECLARATION)


def inventory() -> tuple[dict[str, Any], profile.DirTree]:
    tree = profile.DirTree(SOURCE)
    return profile.validate(declaration(), tree), tree


def test_exact_pinned_source_and_selected_closure() -> None:
    check_source()
    inv, tree = inventory()
    assert inv["selection"] == ["flow-auto", "flow-eli5"]
    assert len(profile.installed_home_files(inv, tree)) == 121
    modes = profile.installed_home_modes(inv, tree)
    assert modes[".claude/scripts/stash-worktree-guard.sh"] == "100755"


@pytest.mark.parametrize("fault", ["changed", "missing", "extra", "empty", "mode"])
def test_source_manifest_distinguishes_bad_inputs(tmp_path: Path, fault: str) -> None:
    # Hardlinks are deliberately avoided: the source snapshot is immutable.
    import shutil
    shutil.copytree(SOURCE, tmp_path / "source")
    root = tmp_path / "source"
    check_source(root)
    p = root / "scripts/stash-worktree-guard.sh"
    if fault == "changed":
        p.write_bytes(p.read_bytes() + b"\n# changed control\n")
    elif fault == "missing":
        p.unlink()
    elif fault == "extra":
        (root / "unexpected").write_text("control")
    elif fault == "empty":
        (root / "README.md").write_text("no manifest")
    else:
        p.chmod(0o644)
    with pytest.raises(AssertionError):
        check_source(root)


def test_literal_missing_dependency_refuses_normal_validator() -> None:
    raw = json.loads(DECLARATION.read_text())
    raw["dependencies"] = [d for d in raw["dependencies"] if d["id"] != "helper-gate-lib"]
    with pytest.raises(profile.Refused):
        profile.validate(profile.Profile.from_dict(raw, DECLARATION.parent), profile.DirTree(SOURCE))


def test_mypy_snapshot_exemption_is_exact(tmp_path: Path) -> None:
    import subprocess
    import sys
    (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text())
    prefix = SOURCE.relative_to(ROOT).as_posix()
    paths = [f"{prefix}/snapshot_probe.py", f"{prefix}x/sibling_probe.py",
             f"tests/{Path(__file__).name}", "tests/test_profile_flow_auto_87ecb097_cold.py"]
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("probe: int = 'not an int'\n")
    result = subprocess.run([sys.executable, "-m", "mypy", "tests"], cwd=tmp_path,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1, result.stdout + result.stderr
    assert [p for p in paths if f"{p}:1: error:" in result.stdout] == paths[1:]
