"""Explicit ordinary-phase CPU competition for the #462 scheduling proof."""
import json
import subprocess
import sys
import time


def test_competing_work_finishes_and_is_reaped(record_property):
    processes = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(4)]
    try:
        time.sleep(2)
        assert all(process.poll() is None for process in processes)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)
    record_property("competing_pids", json.dumps([process.pid for process in processes]))
    record_property("work_reaped_ns", str(time.monotonic_ns()))
    assert all(process.poll() is not None for process in processes)
