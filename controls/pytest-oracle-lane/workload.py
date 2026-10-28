"""Owned ordinary-phase contention for the unchanged artifact qualifier proof."""
import json
import os
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path


def test_competing_work_is_real_and_reaped(record_property):
    processes = []
    try:
        for _ in range(16):
            processes.append(subprocess.Popen([sys.executable, "-c", "while True: pass"]))
        time.sleep(3)
        assert all(process.poll() is None for process in processes)
        ticks = []
        for process in processes:
            stat = (Path("/proc") / str(process.pid) / "stat").read_text().rsplit(")", 1)[1].split()
            ticks.append(int(stat[11]) + int(stat[12]))
        assert all(tick > 0 for tick in ticks), "every competitor must actually consume CPU"
        record_property("competing_cpu_ticks", json.dumps(ticks))
        record_property("clock_ticks_per_second", os.sysconf("SC_CLK_TCK"))
    finally:
        for process in processes:
            with suppress(ProcessLookupError):
                process.terminate()
        for process in processes:
            process.wait(timeout=10)
    assert all(process.poll() is not None for process in processes)
    record_property("work_reaped_ns", str(time.monotonic_ns()))
