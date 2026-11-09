"""Staging-mode regression; no Docker copying is performed.

Normal local-to-container docker cp makes the destination root-owned while
preserving source permissions. The smoke command runs as candidate 10001.
Thus its staged source needs read/search permission for a nonowner. This test
checks that necessary mode contract, not Docker's implementation or host ACLs.
"""
from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest


@pytest.mark.parametrize("mask", [0o022, 0o077], ids=["ordinary", "restrictive"])
@pytest.mark.parametrize("private", [False, True], ids=["readable-input", "private-input"])
def test_smoke_staged_tree_is_readable_by_nonowner(
    tmp_path: Path, mask: int, private: bool,
) -> None:
    builder_path = Path(__file__).resolve().parents[1] / "docker/cicd-project-trial/build.py"
    spec = importlib.util.spec_from_file_location("smoke_permissions_builder", builder_path)
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    # Vary staging umask independently of the original project's permissions.
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    for directory in (project, project / "src"):
        directory.chmod(0o700 if private else 0o755)
    for name in ("pyproject.toml", "uv.lock", "src/package.py", "src/tool.sh"):
        path = project / name
        path.write_text("# controlled readable input\n")
        path.chmod((0o700 if private else 0o755) if name.endswith(".sh")
                   else (0o600 if private else 0o644))
    source_modes = {p.relative_to(project): stat.S_IMODE(p.stat().st_mode)
                    for p in project.rglob("*")}

    context = tmp_path / "context"
    previous = os.umask(mask)
    try:
        builder._warm_context(project, context)
    finally:
        os.umask(previous)

    warm = context / "warm"
    for staged in (warm, *warm.rglob("*")):
        mode = stat.S_IMODE(staged.stat().st_mode)
        # A root-owned copy cannot grant candidate access via owner bits.
        needed = stat.S_IROTH | (stat.S_IXOTH if staged.is_dir() else 0)
        assert mode & needed == needed, (
            f"staged smoke input {staged.relative_to(warm)} mode {mode:04o} "
            "denies candidate access with Docker's default root ownership"
        )
        if staged.is_file():
            original = project / staged.relative_to(warm)
            assert staged.read_bytes() == original.read_bytes()
            assert bool(mode & stat.S_IXOTH) == original.name.endswith(".sh")
    assert {p.relative_to(project): stat.S_IMODE(p.stat().st_mode)
            for p in project.rglob("*")} == source_modes
