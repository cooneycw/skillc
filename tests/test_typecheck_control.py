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
SCOPE = 'files = ["skillc", "tests", "ci"]'

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
    assert "mypy exited 0 with an error planted" in result.stderr, result.stderr


def stub(tmp_path: Path, on_red_run: str) -> str:
    """A mypy whose FIRST call (the baseline) is real, so each case reaches the
    verdict it names instead of tripping the baseline guard."""
    path, count = tmp_path / "mypy-stub", tmp_path / "mypy-calls"
    path.write_text(
        "#!/usr/bin/env bash\n"
        f'echo x >> "{count}"\n'
        f'if [ "$(wc -l < "{count}")" -eq 1 ]; then exec {REAL} "$@"; fi\n'
        f"{on_red_run}\n"
    )
    path.chmod(0o755)
    return str(path)


def test_a_blind_mypy_turns_the_step_red(tmp_path: Path) -> None:
    mypy = stub(tmp_path, 'echo "Success: no issues found"; exit 0')
    result = run_in_copy(tmp_path, mypy=mypy)
    assert result.returncode == 1, f"blind mypy passed\n{result.stdout}"
    assert "mypy exited 0 with an error planted" in result.stderr, result.stderr


def test_a_red_that_names_another_file_turns_the_step_red(tmp_path: Path) -> None:
    mypy = stub(tmp_path, 'echo "skillc/cli.py:1: error: unrelated  [misc]"; exit 1')
    result = run_in_copy(tmp_path, mypy=mypy)
    assert result.returncode == 1, f"misattributed red passed\n{result.stdout}"
    assert "mypy exited 1 without reporting tests/" in result.stderr, result.stderr


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root bypasses chmod(0o000) (DAC override), so this probe cannot "
    "become unreadable under a root test runner (cross-model review, PR #116)",
)
def test_an_unreadable_source_file_turns_the_step_red(tmp_path: Path) -> None:
    """A copy that genuinely fails must still fail (#20 comment 5850673964):
    the fix for the tar-vs-parallel-writer race must not turn every copy
    failure into a silent pass."""
    repo = tmp_path / "repo"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", ".venv", ".mypy_cache"))
    unreadable = repo / "skillc" / "_test_unreadable_probe.py"
    unreadable.write_text("x = 1\n")
    unreadable.chmod(0o000)
    try:
        result = subprocess.run(
            ["bash", str(repo / "ci" / "typecheck-control.sh")],
            env={**os.environ, "MYPY": REAL}, capture_output=True, text=True, check=False,
        )
    finally:
        unreadable.chmod(0o644)
    assert result.returncode == 1, f"unreadable source file passed\n{result.stdout}"
    assert "could not copy the tree" in result.stderr, result.stderr
