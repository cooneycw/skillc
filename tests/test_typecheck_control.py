"""Committed red cases for ci/typecheck-control.sh.

CI reads that script's green as "the typecheck gate still reads tests/". Nothing
downstream re-derives it, so the script needs inputs that make it report the
other verdict. The narrowed-scope case is #19 itself: `files` back to skillc/
alone, which is how ten type errors in tests/ went unseen.

Each case runs the script from a copy of the repository, so the scope can be
narrowed without touching the real pyproject.toml.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REAL = f"{sys.executable} -m mypy"
SCOPE = 'files = ["skillc", "tests"]'

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("tar") is None, reason="needs bash and tar"
)


def run_in_copy(
    tmp_path: Path, *, scope: str = SCOPE, mypy: str = REAL
) -> subprocess.CompletedProcess[str]:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", ".venv", ".mypy_cache"))
    pyproject = repo / "pyproject.toml"
    text = pyproject.read_text()
    assert text.count(SCOPE) == 1, "the declared typecheck scope moved; update SCOPE"
    pyproject.write_text(text.replace(SCOPE, scope))
    env = {**os.environ, "MYPY": mypy}
    return subprocess.run(
        ["bash", str(repo / "ci" / "typecheck-control.sh")],
        env=env, capture_output=True, text=True, check=False,
    )


def test_the_declared_scope_passes(tmp_path: Path) -> None:
    result = run_in_copy(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "typecheck-control: ok" in result.stdout


def test_a_scope_that_drops_tests_turns_the_step_red(tmp_path: Path) -> None:
    result = run_in_copy(tmp_path, scope='files = ["skillc"]')
    assert result.returncode == 1, f"narrowed scope passed\n{result.stdout}"
    assert "is tests/ out of scope?" in result.stderr


def test_a_blind_mypy_turns_the_step_red(tmp_path: Path) -> None:
    result = run_in_copy(tmp_path, mypy="bash -c 'echo Success: no issues found; exit 0'")
    assert result.returncode == 1, f"blind mypy passed\n{result.stdout}"
    assert "typecheck-control: FAIL" in result.stderr
