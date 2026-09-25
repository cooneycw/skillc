"""Committed red cases for ci/negative-control.sh.

CI reads that script's green as "selftest can still refuse". Nothing downstream
re-derives it, so the script needs inputs that make it report the other verdict.
Each case swaps `skillc` for a stub through SKILLC; `rules` always delegates to
the real CLI so the derived rule and count are real.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "ci" / "negative-control.sh"
REAL = f"{sys.executable} -c 'import sys; from skillc.cli import main; sys.exit(main(sys.argv[1:]))'"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

# What the stub does on the SECOND selftest call - the one after the removal.
# The first call (the baseline) always delegates, so each case isolates the
# verdict check rather than tripping the baseline guard.
MUTATED = {
    "real": f'exec {REAL} "$@"',
    "blind": 'echo "skillc selftest: 11/11 rule(s) discriminate"; exit 0',
    "crash-only": 'echo "Traceback (most recent call last):" >&2; exit 1',
    "unproven-then-crash": (
        f'{REAL} "$@"; echo "Traceback (most recent call last):"; exit 1'
    ),
    "unproven-without-summary": (
        f'{REAL} "$@" | grep "^UNPROVEN"; exit 1'
    ),
}


def run_with(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "skillc-stub"
    count = tmp_path / "selftest-calls"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" != selftest ]; then exec {REAL} "$@"; fi\n'
        f'echo x >> "{count}"\n'
        f'if [ "$(wc -l < "{count}")" -eq 1 ]; then exec {REAL} "$@"; fi\n'
        f"{MUTATED[mode]}\n"
    )
    stub.chmod(0o755)
    env = {**os.environ, "SKILLC": str(stub), "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )


def test_a_working_selftest_passes(tmp_path: Path) -> None:
    result = run_with(tmp_path, "real")
    assert result.returncode == 0, result.stderr
    assert "negative-control: ok" in result.stdout


@pytest.mark.parametrize(
    "mode", ["blind", "crash-only", "unproven-then-crash", "unproven-without-summary"]
)
def test_a_broken_selftest_turns_the_step_red(tmp_path: Path, mode: str) -> None:
    result = run_with(tmp_path, mode)
    assert result.returncode == 1, f"{mode}: script passed\n{result.stdout}"
    assert "negative-control: FAIL" in result.stderr
