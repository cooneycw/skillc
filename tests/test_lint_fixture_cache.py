"""Published lint commands must preserve immutable fixtures and still find defects."""
from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from test_profile_flow_auto_87ecb097 import SOURCE, check_source

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = SOURCE.relative_to(ROOT)


def _copy(tmp_path: Path) -> Path:
    for name in ("Makefile", "pyproject.toml", "uv.lock", ".gitignore"):
        shutil.copy2(ROOT / name, tmp_path / name)
    shutil.copytree(SOURCE, tmp_path / FIXTURE)  # independent bytes, never hardlinks
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True, timeout=10)
    check_source(tmp_path / FIXTURE)
    return tmp_path


def _command(producer: str) -> list[str]:
    if producer == "make":
        # Run the real recipe; dev dependencies are already installed by the outer gate.
        return ["make", "--assume-old=sync", "lint"]
    config = yaml.safe_load((ROOT / ".woodpecker/ci.yml").read_text())
    gate = next(step for step in config["steps"] if step["name"] == "gate")
    commands = [shlex.split(command) for command in gate["commands"] if isinstance(command, str)]
    lint = [argv for argv in commands if argv[:5] == ["uv", "run", "--no-sync", "ruff", "check"]]
    assert len(lint) == 1, "the actual CI gate must publish one Ruff command"
    return lint[0]


def _run(root: Path, producer: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": sys.prefix}
    # Exercise the published command's own cache policy, without ambient overrides.
    for name in ("RUFF_CACHE_DIR", "RUFF_NO_CACHE"):
        env.pop(name, None)
    return subprocess.run(_command(producer), cwd=root, env=env,
                          capture_output=True, text=True, timeout=60, check=False)


def _fingerprint(root: Path) -> dict[str, tuple[int, str]]:
    return {p.relative_to(root).as_posix(): (p.stat().st_mode & 0o777, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("producer", ["make", "ci"])
def test_repeated_published_lint_preserves_exact_fixture(tmp_path: Path, producer: str) -> None:
    root = _copy(tmp_path)
    fixture = root / FIXTURE
    before = _fingerprint(fixture)
    assert len(before) == 389
    for _ in range(2):
        result = _run(root, producer)
        assert result.returncode == 0, result.stdout + result.stderr
        check_source(fixture)  # pre-fix: Ruff passes but this existing membership check fails
        assert _fingerprint(fixture) == before
    assert (root / ".ruff_cache").is_dir(), "cache generation must be exercised, outside the fixture"


def test_generated_cache_is_rejected_by_existing_manifest_checker(tmp_path: Path) -> None:
    fixture = _copy(tmp_path) / FIXTURE
    cache = fixture / ".ruff_cache"
    cache.mkdir()
    (cache / "CACHEDIR.TAG").write_text("generated cache control\n")
    with pytest.raises(AssertionError):
        check_source(fixture)


@pytest.mark.parametrize("producer", ["make", "ci"])
@pytest.mark.parametrize("location", ["root", "vendor"])
def test_published_lint_still_detects_root_and_vendor_defects(
        tmp_path: Path, producer: str, location: str) -> None:
    root = _copy(tmp_path)
    target = root / ("authored_probe.py" if location == "root" else str(FIXTURE / "lib/cicd/state.py"))
    prior = target.read_bytes() if target.exists() else b""
    target.write_bytes(prior + b"\nfixture_cache_probe_missing()\n")
    result = _run(root, producer)
    assert result.returncode != 0
    assert "F821" in result.stdout and str(target.relative_to(root)) in result.stdout, result.stdout + result.stderr
