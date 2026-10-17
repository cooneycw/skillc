"""Negative control on the certification scripts themselves (orchestrator
direction, 2026-10-07, following the `gate-stops-early`/`claims-outran-
evidence`/`report-outran-evidence` `_WitnessBackend` drift found while
wiring #270): that drift crashed `qualify.py` with a `TypeError` on every
`request=True` call, and went undetected for as long as it did because
NOTHING in the pytest suite ever ran these scripts - a green suite said
nothing about whether any of them still worked. This file runs every eval
task's own `qualify.py` as a real subprocess and asserts `QUALIFY: ok`, so
a future drift like that one reds the normal suite instead of waiting for
someone to run it by hand.

Discovered via `rglob`, never hand-listed - the whole point is that a NEW
qualify.py is covered automatically, not only the ones named here at the
time of writing. `test_every_qualify_script_is_discovered_and_none_
quietly_ignored` floors the discovered count so a broken `rglob` (e.g. a
future refactor that moves `evals/` or renames the pattern) cannot silently
collapse the population to zero and still read as "every task certified."
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EVALS_ROOT = Path(__file__).resolve().parent.parent / "evals"

QUALIFY_SCRIPTS = sorted(EVALS_ROOT.rglob("qualify.py"))

#: CI 735 (#371) exhausted 180s after certifying slugkit-pipeline's
#: candidates and running its broken-grader controls, before its remaining
#: pipeline-validity probes completed. Give this known expensive script a
#: bounded 360s budget under parallel CI; preserve 180s for every other task.
_SLOW_REASON = {
    "slugkit-pipeline": "CI 735 exceeded 180s while executing real pipeline-validity controls",
}


def _task_name(script: Path) -> str:
    return script.parent.name


@pytest.mark.parametrize("script,timeout_seconds", [
    pytest.param(script, 360 if _task_name(script) in _SLOW_REASON else 180,
                 id=_task_name(script),
                 marks=pytest.mark.timeout(380 if _task_name(script) in _SLOW_REASON else 200))
    for script in QUALIFY_SCRIPTS
])
def test_qualify_script_certifies(script: Path, timeout_seconds: float) -> None:
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True,
        timeout=timeout_seconds, check=False, cwd=script.parent,
    )
    tail = "\n".join(proc.stdout.strip().splitlines()[-8:])
    name = _task_name(script)
    slow_note = f" ({_SLOW_REASON[name]})" if name in _SLOW_REASON else ""
    assert proc.returncode == 0, (
        f"{name}: qualify.py exited {proc.returncode}{slow_note}\n"
        f"stdout tail:\n{tail}\nstderr:\n{proc.stderr}"
    )
    assert "QUALIFY: ok" in proc.stdout, f"{name}: no 'QUALIFY: ok' in output:\n{tail}"


@pytest.mark.timeout(5)
def test_hung_qualify_script_is_rejected(tmp_path: Path) -> None:
    """A larger budget still refuses a script that never completes."""
    script = tmp_path / "qualify.py"
    script.write_text("import time\nprint('QUALIFY: ok', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
    with pytest.raises(subprocess.TimeoutExpired):
        test_qualify_script_certifies(script, timeout_seconds=0.1)


def test_every_qualify_script_is_discovered_and_none_quietly_ignored() -> None:
    """Membership floor: pins that discovery found a non-trivial, known
    population today, so a collection failure (e.g. `rglob` silently
    returning nothing after a future `evals/` reorganization) cannot pass
    as "every task certified" over an empty population - the same failure
    class `tests/test_private_citations.py`'s own empty-population check
    exists to catch, applied here."""
    assert len(QUALIFY_SCRIPTS) >= 13, (
        f"expected at least 13 qualify.py scripts (the count at the time this test was "
        f"written), found {len(QUALIFY_SCRIPTS)}: {[str(p) for p in QUALIFY_SCRIPTS]}"
    )
