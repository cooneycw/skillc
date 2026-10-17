"""SCRATCH (#412, never merged): negative control for the timing probe.

Each case injects a KNOWN delay on the real path and the probe must record
elapsed >= that delay. A probe that cannot report a slow op would make every
headroom ratio look healthy."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from test_docker_backend import _backend, base, docker_state  # noqa: F401

from skillc import docker_backend as d
from skillc.backend import Limits

DELAY = 2.0
pytestmark = pytest.mark.skipif(not os.environ.get("SKILLC_TIMING_LOG"), reason="probe not enabled")


def _records(test_fragment: str) -> list[dict[str, object]]:
    out = []
    for f in Path(os.environ["SKILLC_TIMING_LOG"]).glob("*.jsonl"):
        for line in f.read_text().splitlines():
            r = json.loads(line)
            if test_fragment in str(r["test"]):
                out.append(r)
    return out


def test_control_a_delayed_daemon_call_is_recorded_slow(base: Path, docker_state: Path) -> None:
    docker_state.mkdir(parents=True, exist_ok=True)
    (docker_state / ".delay-version").write_text(str(DELAY))
    assert d.probe_daemon(_backend(base, docker_state).docker_bin, 30.0, d._docker_env()) is not None
    recs = [r for r in _records("test_control_a_delayed") if r["kind"] == "run" and "version" in r["argv"]]
    assert recs, "the probe recorded no version call"
    assert max(float(r["elapsed"]) for r in recs) >= DELAY  # type: ignore[arg-type]


def test_control_a_slow_subject_is_recorded_slow(base: Path, docker_state: Path) -> None:
    backend = _backend(base, docker_state)
    handle = backend.prepare("a-lc-000000000412")
    backend.install(handle, {})
    res = backend.execute(handle, [sys.executable, "-c", f"import time; time.sleep({DELAY})"], Limits(timeout=10))
    assert res.reason == "exited"
    recs = [r for r in _records("test_control_a_slow_subject") if r["kind"] == "execute"]
    assert len(recs) == 1
    assert float(recs[0]["elapsed"]) >= DELAY  # type: ignore[arg-type]
