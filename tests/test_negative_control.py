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

# Each case mutates ONE call and delegates every other one to the real CLI, so it
# isolates one verdict check rather than tripping a baseline guard. Calls are
# counted per subcommand: selftest #1 is the baseline, #2 the removed control, #3
# the emptied population; check #1 is the selector baseline, #2 the bogus selector.
MUTATED: dict[str, tuple[str, int, str]] = {
    "real": ("selftest", 0, ""),
    # 1. a removed control
    "blind": ("selftest", 2, 'echo "skillc selftest: 12/12 rule(s) discriminate"; exit 0'),
    "crash-only": ("selftest", 2, 'echo "Traceback (most recent call last):" >&2; exit 1'),
    "unproven-then-crash": (
        "selftest", 2, f'{REAL} "$@"; echo "Traceback (most recent call last):"; exit 1'
    ),
    "unproven-without-summary": ("selftest", 2, f'{REAL} "$@" | grep "^UNPROVEN"; exit 1'),
    # 2. an emptied population - the pre-#2 behaviour certified it
    "empty-certified": (
        "selftest", 3, 'echo "skillc selftest: 12/12 rule(s) discriminate"; exit 0'
    ),
    "empty-misnamed": ("selftest", 3, f'{REAL} "$@" | sed "s/^EMPTY   /BLIND   /"; exit 1'),
    "empty-then-crash": (
        "selftest", 3, f'{REAL} "$@"; echo "Traceback (most recent call last):"; exit 1'
    ),
    # 3. an unknown selector - the pre-#2 behaviour read it as a clean check
    "selector-silent": (
        "check", 2, 'echo "skillc: 1 skill(s) checked, 0 error(s), 0 warning(s)"; exit 0'
    ),
    "selector-unnamed": ("check", 2, 'echo "error" >&2; exit 2'),
    "selector-scans-first": (
        "check", 2,
        'echo "skillc: 1 skill(s) checked, 0 error(s), 0 warning(s)"; '
        'echo "skillc: unknown rule \'$4\'" >&2; exit 2',
    ),
}


def run_with(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    command, nth, mutation = MUTATED[mode]
    stub = tmp_path / "skillc-stub"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" != {command} ]; then exec {REAL} "$@"; fi\n'
        f'echo x >> "{tmp_path}/calls-$1"\n'
        f'if [ "$(wc -l < "{tmp_path}/calls-$1")" -ne {nth} ]; then exec {REAL} "$@"; fi\n'
        f"{mutation}\n"
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


@pytest.mark.parametrize("mode", [m for m in MUTATED if m != "real"])
def test_a_broken_selftest_turns_the_step_red(tmp_path: Path, mode: str) -> None:
    result = run_with(tmp_path, mode)
    assert result.returncode == 1, f"{mode}: script passed\n{result.stdout}"
    assert "negative-control: FAIL" in result.stderr
