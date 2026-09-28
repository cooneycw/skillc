"""Negative control for the pytest-timeout gate (#148, ADR 0001).

The `gate` step trusts that a stalled test is reported as a fast, named
failure rather than hanging the pipeline without limit (Woodpecker pipeline
258 ran 35+ minutes past a blocking write before anyone noticed). A configured
`timeout` that never actually fires would look identical to a working one -
green either way - so this is the committed input that proves it still fires.

The control itself is skipped in the normal suite (it would otherwise fail
every run on purpose); run it explicitly with
`SKILLC_RUN_TIMEOUT_CONTROL=1 uv run pytest tests/test_pytest_timeout_control.py -k control`
to see it reported as a timeout failure, per issue #148's negative-control
requirement.
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
    control test's own short per-test override (well under it) stops proving
    anything about the REAL default and must be revisited."""
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert config["tool"]["pytest"]["ini_options"]["timeout"] == 120


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
