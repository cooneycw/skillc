"""Negative control for the Makefile `test` target's pipefail claim (#134).

`make verify` is a gate that lets work through (CLAUDE.md's Negative Control
rule), and its own comment claims `pytest -rA | tee reports/pytest.log` fails
the target on a real pytest failure rather than on tee's own near-always-zero
exit. Nothing committed proved that until this file.

Reuses #152's own committed negative control
(tests/test_pytest_timeout_control.py) as the known-bad input: selected via
`PYTEST_ARGS`, it is a single failing test, so `make test` cannot recurse
into this file.

The CI image has neither git nor make (AGENTS.md, and the `needs_git`/
`needs_codex` convention in tests/test_materialize.py), so this test is
skipped there and covered only by the LOCAL `make verify` gate - stated here
and in the PR body, not assumed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

needs_make = pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")


@needs_make
def test_a_failing_pytest_run_fails_make_test_through_the_tee() -> None:
    """Confirmed red without pipefail (cross-model review on PR #156):
    temporarily dropped `-o pipefail` from the Makefile's `.SHELLFLAGS` and
    reran this exact command by hand - `make test` exited 0 despite the
    selected test failing, because tee's own exit code (0) is what a plain
    shell reports for the pipe. See the PR body for the captured run."""
    result = subprocess.run(
        ["make", "test", "PYTEST_ARGS=tests/test_pytest_timeout_control.py -k a_hang"],
        cwd=ROOT,
        env={**os.environ, "SKILLC_RUN_TIMEOUT_CONTROL": "1"},
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode != 0, (
        f"make test passed despite a failing pytest run\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
