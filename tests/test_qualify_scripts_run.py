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

#: Needs real wall-clock time beyond the suite's global 120s per-test
#: default (measured 2026-10-07: ~111s, a real `uv run` subprocess tree,
#: not a hang) - a stated, explicit reason, per the orchestrator's own
#: instruction, never a silent skip. Every other discovered script
#: finishes in well under 15s.
_SLOW_REASON = {
    "slugkit-pipeline": "measured ~111s (real pipeline-validity controls, "
                         "not a hang) - over the suite's 120s per-test default",
}


def _task_name(script: Path) -> str:
    return script.parent.name


@pytest.mark.timeout(200)
@pytest.mark.parametrize("script", QUALIFY_SCRIPTS, ids=_task_name)
def test_qualify_script_certifies(script: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True,
        timeout=180, check=False, cwd=script.parent,
    )
    tail = "\n".join(proc.stdout.strip().splitlines()[-8:])
    name = _task_name(script)
    slow_note = f" ({_SLOW_REASON[name]})" if name in _SLOW_REASON else ""
    assert proc.returncode == 0, (
        f"{name}: qualify.py exited {proc.returncode}{slow_note}\n"
        f"stdout tail:\n{tail}\nstderr:\n{proc.stderr}"
    )
    assert "QUALIFY: ok" in proc.stdout, f"{name}: no 'QUALIFY: ok' in output:\n{tail}"


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
