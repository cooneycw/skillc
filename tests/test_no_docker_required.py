"""EF-11 ("Optional execution layer"), #80: `skillc check` and `skillc
selftest` must run to a real result with no `docker` binary reachable at
all - the Docker backend is an optional capability layered on top of the
static checker, never a load-bearing dependency of it.

Two things are proven separately, on purpose:

1. The STRUCTURAL claim: a static command's own module never imports
   `skillc.docker_backend` at load time. This is `#80`'s own committed
   control (issue body: "The no-Docker proof fails when a static command is
   made to import the Docker backend at module load"). Checked in a
   SEPARATE subprocess per import, never inside this test process's own
   `sys.modules` - a prior test elsewhere in the suite may have already
   imported `skillc.docker_backend` through a different path, which would
   make an in-process check spuriously see it as "already imported" whether
   or not `skillc.cli` itself imports it.
2. The BEHAVIORAL claim: `skillc check`/`skillc selftest`, run as real
   subprocesses under a PATH with no `docker` executable anywhere on it,
   still complete successfully. A positive control comes first, proving the
   constructed PATH actually makes `docker` unreachable - otherwise a green
   result below would be vacuous on any host that happens to have Docker on
   its normal PATH regardless of this test's own PATH surgery.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_COLLECTION = REPO_ROOT / "tests" / "fixtures" / "codex-subject" / "collection"
REDCASE_DIR = Path(__file__).resolve().parent / "fixtures" / "conformance"


def _imports_docker_backend(module: str, extra_syspath: Path | None = None) -> bool:
    """Whether importing `module` pulls in `skillc.docker_backend` as a
    side effect - run in a FRESH subprocess, never this test process's own
    interpreter (see module docstring).

    Reads only the LAST LINE of stdout (cross-model review, PR #87): the
    prior version compared the WHOLE captured stdout against the literal
    "yes", so a module that prints anything else before importing the
    Docker backend - a startup message, a warning - produced multi-line
    stdout that never equalled "yes" and so reported a false negative,
    masking exactly the case this check exists to catch."""
    lines = ["import sys"]
    if extra_syspath is not None:
        lines.append(f"sys.path.insert(0, {str(extra_syspath)!r})")
    lines.append(f"import {module}")
    lines.append("print('yes' if 'skillc.docker_backend' in sys.modules else 'no')")
    proc = subprocess.run(
        [sys.executable, "-c", "\n".join(lines)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"probe failed importing {module!r}: {proc.stderr}")
    stripped = proc.stdout.strip()
    last_line = stripped.splitlines()[-1] if stripped else ""
    return last_line == "yes"


def test_the_cli_module_does_not_import_the_docker_backend_at_load_time() -> None:
    assert _imports_docker_backend("skillc.cli") is False


def test_the_import_check_detects_the_committed_redcase() -> None:
    """Negative control (ADR 0001): `imports_docker_backend_at_load.py` DOES
    import `skillc.docker_backend` at module load, on purpose - the check
    above must report `True` for it, proving the green result above is not
    vacuous (a checker that always says "no" would pass the CLI module for
    the wrong reason)."""
    assert _imports_docker_backend("imports_docker_backend_at_load", extra_syspath=REDCASE_DIR) is True


def test_the_import_check_is_not_fooled_by_unrelated_output_before_the_verdict() -> None:
    """Regression for a cross-model review finding (PR #87): fails on the
    pre-fix probe, which returned False for this fixture even though it
    genuinely imports the Docker backend - the unrelated print before the
    import made the whole-stdout comparison miss it."""
    assert _imports_docker_backend("imports_docker_backend_with_noise", extra_syspath=REDCASE_DIR) is True


def _docker_free_path(tmp_path: Path) -> str:
    """A single, absolute, freshly-created, guaranteed-empty directory -
    never a filtered copy of the ambient `PATH` (cross-model review, PR #87:
    the prior version inspected ambient PATH entries, possibly relative,
    against THIS PROCESS's cwd while the commands under test ran with an
    explicit different `cwd` - a relative entry could be judged "docker-free"
    against one cwd while actually resolving to a directory that has
    `docker` against the other. A single absolute empty directory removes
    the ambiguity entirely, and every subprocess in this file - the control
    and the commands under test alike - uses exactly this same value)."""
    empty_dir = tmp_path / "docker-free-path"
    empty_dir.mkdir()
    return str(empty_dir)


def test_docker_is_actually_unreachable_under_the_constructed_path(tmp_path: Path) -> None:
    """Positive control: before trusting a green `check`/`selftest` run
    below as evidence for EF-11, prove the Docker-stripped PATH this test
    builds actually makes `docker` unreachable. A broken construction that
    left `docker` reachable would make the test below pass for the wrong
    reason on any host that happens to have Docker installed."""
    env = {**os.environ, "PATH": _docker_free_path(tmp_path)}
    with pytest.raises(FileNotFoundError):
        subprocess.run(["docker", "--version"], cwd=REPO_ROOT, env=env, capture_output=True, check=False)


def test_skillc_check_runs_without_docker_on_path(tmp_path: Path) -> None:
    env = {**os.environ, "PATH": _docker_free_path(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-m", "skillc.cli", "check", str(FIXTURE_COLLECTION)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_skillc_selftest_runs_without_docker_on_path(tmp_path: Path) -> None:
    env = {**os.environ, "PATH": _docker_free_path(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-m", "skillc.cli", "selftest"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_skillc_rules_and_version_run_without_docker_on_path(tmp_path: Path) -> None:
    env = {**os.environ, "PATH": _docker_free_path(tmp_path)}
    for extra_args in (["rules"], ["--version"]):
        result = subprocess.run(
            [sys.executable, "-m", "skillc.cli", *extra_args],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
