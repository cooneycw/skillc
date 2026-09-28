"""Negative control for the pytest-timeout gate (#148, ADR 0001).

The `gate` step trusts that a stalled test is reported as a fast, named
failure rather than hanging the pipeline without limit (Woodpecker pipeline
258 ran 35+ minutes past a blocking write before anyone noticed). A configured
`timeout` that never actually fires would look identical to a working one -
green either way - so this is the committed input that proves it still fires.

Two things this control must prove, not one: that pytest-timeout can fail a
test at all (`test_a_hang_past_its_timeout_...`, a per-test
`@pytest.mark.timeout` marker), and separately that the REAL gate - the bare
`timeout = 120` key `pyproject.toml`'s `[tool.pytest.ini_options]` sets - is
what pytest actually applies, not merely a plugin that CAN enforce a timeout
when told to per-test. A marker-only control cannot tell the difference: if
the ini key were misspelled, placed under the wrong table, or dropped
entirely, pytest-timeout would still be installed and the marker case would
still fail exactly the same way, while the real per-test default silently
stopped existing (cross-model review on PR #152 caught this - confirmed by
renaming the ini key to `timeoutz` and re-running: the marker control still
passed, while `test_pytest_applies_the_configured_default` failed; see the
PR body for the captured run).

That review also suggested a second sleeping control with no marker, run
with `-o timeout=1`, as an alternative way to show the ini key is the one
pytest-timeout reads. Tried and measured wrong: `-o` sets the option
directly on the command line regardless of what pyproject.toml says, so that
control passed unchanged against the SAME broken `timeoutz` key above - it
was never reading the file at all. Dropped rather than shipped with a false
claim in its docstring; `test_pytest_applies_the_configured_default`'s
`--collect-only` header read is the one that actually depends on the file.

The marker control is skipped in the normal suite (it would otherwise fail
every run on purpose); run it explicitly with
`SKILLC_RUN_TIMEOUT_CONTROL=1 uv run pytest tests/test_pytest_timeout_control.py -k control`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_the_configured_default_is_what_the_control_below_assumes() -> None:
    """`ci/negative-control.sh`-style guard: if the default ever moves, the
    marker control's own short per-test override (well under it) stops
    proving anything about the REAL default and must be revisited. This is a
    static read of the file only - it does not show pytest applies the
    value; `test_pytest_applies_the_configured_default` below does."""
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert config["tool"]["pytest"]["ini_options"]["timeout"] == 120


def test_pytest_applies_the_configured_default() -> None:
    """pytest-timeout prints the default it is actually enforcing in the
    session header (`timeout: <N>s`) even on a plain `--collect-only`, which
    runs no test and so cannot be satisfied by any per-test marker. This is
    the assertion that fails when the ini key moves or is misspelled, which
    a marker-based control cannot see (see module docstring)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "tests/test_cost_estimate.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "timeout: 120.0s" in result.stdout, (
        f"pytest-timeout did not report the configured 120s default\n{result.stdout}"
    )


@pytest.mark.skipif(
    not os.environ.get("SKILLC_RUN_TIMEOUT_CONTROL"),
    reason="negative control for #148 - sleeps past its timeout on purpose; "
    "skipped in the normal suite, run with SKILLC_RUN_TIMEOUT_CONTROL=1",
)
@pytest.mark.timeout(1)
def test_a_hang_past_its_timeout_is_reported_as_a_timeout_failure() -> None:
    time.sleep(5)


def test_the_control_above_is_reported_as_a_timeout_failure_when_run() -> None:
    """Runs the skipped control in a subprocess with the gate flipped on, and
    requires pytest-timeout's own failure shape - not just a red exit code,
    which a plain assertion failure or a crash could also produce."""
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q",
            f"tests/{Path(__file__).name}::test_a_hang_past_its_timeout_is_reported_as_a_timeout_failure",
        ],
        cwd=ROOT,
        env={**os.environ, "SKILLC_RUN_TIMEOUT_CONTROL": "1"},
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 1, (
        f"the control did not fail\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "Timeout (>1.0s) from pytest-timeout." in result.stdout, (
        f"failed, but not with a pytest-timeout timeout\n{result.stdout}"
    )
