"""The timer qualifier must reject the committed broken policy functions."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ci import check_heavy_run_load_controls as controls

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('source,failed', [
    ('intact.py', set()),
    ('always-abort.py', {'below-threshold', 'continuous-boundary',
                         'interruption-resets', 'second-continuous-boundary'}),
    ('always-continue.py', {'continuous-boundary', 'second-continuous-boundary'}),
    ('forgot-reset.py', {'below-threshold', 'interruption-resets', 'second-continuous-boundary'}),
    ('early-boundary.py', {'continuous-boundary', 'interruption-resets'}),
])
def test_committed_timer_implementations_discriminate(source: str, failed: set[str]) -> None:
    path = ROOT / 'controls/heavy-run-load' / source
    result = controls.check(path)
    assert set(result['failed']) == failed
    assert len(result['passed']) + len(result['failed']) == 4
    run = subprocess.run([sys.executable, str(ROOT / 'ci/check_heavy_run_load_controls.py'), str(path)],
                         capture_output=True, text=True, check=False, timeout=5)
    assert run.returncode == (1 if failed else 0)
    assert json.loads(run.stdout) == result


@pytest.mark.parametrize('source', ['missing', 'no-step', 'decorated-step'])
def test_unavailable_policy_is_unknown_not_a_timer_verdict(tmp_path: Path, source: str) -> None:
    path = tmp_path / 'supervisor.py'
    if source == 'no-step':
        path.write_text('def another_name(): return True\n')
    elif source == 'decorated-step':
        path.write_text('@unknown\ndef step(since, now, load): return None, False\n')
    run = subprocess.run([sys.executable, str(ROOT / 'ci/check_heavy_run_load_controls.py'), str(path)],
                         capture_output=True, text=True, check=False, timeout=5)
    assert run.returncode == 2
    assert json.loads(run.stdout)['status'] == 'UNKNOWN'
