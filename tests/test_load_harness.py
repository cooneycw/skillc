"""The #462 load harness: its own control, and its host-impact bounds.

The committed red is `test_spinners_disabled_reports_invalid`: the harness's
INVALID verdict is the only thing that separates "passed under load" from
"passed because no load was applied", so a run with the spinners disabled must
say INVALID and run nothing. The fake-/proc/stat pair shows the same verdict
logic turning on the sampled count alone, both ways.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ci import load_harness as lh

HARNESS = Path(lh.__file__)
PROC = Path("/proc/stat").is_file()
needs_proc = pytest.mark.skipif(not PROC, reason="needs Linux /proc")


def _fake_stat(tmp_path: Path, running: int) -> list[str]:
    stat = tmp_path / "stat"
    stat.write_text(f"cpu 1 2 3 4\nprocs_running {running}\nprocs_blocked 0\n")
    loadavg = tmp_path / "loadavg"
    loadavg.write_text("1.00 1.00 1.00 1/100 1\n")
    return ["--stat-path", str(stat), "--loadavg-path", str(loadavg)]


def _phase(tmp_path: Path, *opts: str, cmd: tuple[str, ...] = ()) -> tuple[int, dict, str]:
    out = tmp_path / "phase.json"
    proc = subprocess.run(
        [sys.executable, str(HARNESS), "phase", *opts, "--out", str(out), "--",
         *(cmd or (sys.executable, "-c", "pass"))],
        capture_output=True, text=True, timeout=90, check=False,
    )
    record = json.loads(out.read_text()) if out.exists() else {}
    return proc.returncode, record, proc.stderr


def _group_members(pgid: int) -> list[int]:
    members = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        # Field 5 (pgrp) follows the parenthesised comm, which may hold spaces.
        if int(stat.rsplit(")", 1)[1].split()[2]) == pgid:
            members.append(int(entry.name))
    return members


def _wait_gone(pgid: int, seconds: float = 5.0) -> list[int]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        members = _group_members(pgid)
        if not members:
            return []
        time.sleep(0.1)
    return _group_members(pgid)


@needs_proc
def test_spinners_disabled_reports_invalid(tmp_path):
    """The committed red: no spinners, a target only load can reach -> INVALID."""
    target = 4 * (os.cpu_count() or 1) + 64
    rc, record, err = _phase(tmp_path, "--cpu", "0", "--churn", "0",
                             "--target", str(target), "--reps", "3",
                             "--warmup-seconds", "6")
    assert rc == 1, err
    assert record["verdict"] == "INVALID"
    assert record["warmup_reached"] is False
    assert record["reps"] == [], "an INVALID warm-up must run no reps"
    assert "LOAD_PHASE: INVALID" in err


def test_no_samples_is_invalid_never_a_division():
    assert lh.load_verdict([], 1) == ("INVALID", 0.0)


def test_sampled_count_below_target_is_invalid(tmp_path):
    rc, record, _ = _phase(tmp_path, "--cpu", "0", "--target", "50", "--reps", "2",
                           "--warmup-seconds", "6", *_fake_stat(tmp_path, 3))
    assert (rc, record["verdict"], record["reps"]) == (1, "INVALID", [])


def test_sampled_count_at_target_is_valid_and_runs_the_reps(tmp_path):
    rc, record, err = _phase(tmp_path, "--cpu", "0", "--target", "50", "--reps", "2",
                             "--warmup-seconds", "10", *_fake_stat(tmp_path, 50))
    assert rc == 0, err
    assert record["verdict"] == "VALID"
    assert [r["outcome"] for r in record["reps"]] == ["passed", "passed"]
    assert record["uptime_before"] and record["uptime_after"]


def test_a_failing_rep_is_recorded_with_its_output(tmp_path):
    rc, record, _ = _phase(
        tmp_path, "--cpu", "0", "--target", "1", "--reps", "1", "--warmup-seconds", "10",
        *_fake_stat(tmp_path, 5),
        cmd=(sys.executable, "-c", "import sys; print('boom-462'); sys.exit(3)"),
    )
    assert rc == 0
    (rep,) = record["reps"]
    assert (rep["outcome"], rep["exit"]) == ("failed", 3)
    assert "boom-462" in rep["tail"]


def test_a_rep_running_at_the_cap_is_truncated_not_counted(tmp_path):
    rc, record, _ = _phase(
        tmp_path, "--cpu", "0", "--target", "1", "--reps", "3", "--warmup-seconds", "10",
        "--max-seconds", "8", *_fake_stat(tmp_path, 5),
        cmd=(sys.executable, "-c", "import time; time.sleep(60)"),
    )
    assert rc == 0
    assert [r["outcome"] for r in record["reps"]] == ["truncated"]
    assert record["ended_at"] - record["started_at"] < 30


def test_a_phase_over_the_cap_is_refused(tmp_path):
    rc, record, err = _phase(tmp_path, "--cpu", "1", "--target", "1", "--reps", "1",
                             "--max-seconds", str(lh.PHASE_CAP_SECONDS + 1))
    assert rc == 2 and record == {}
    assert "phase cap" in err


@needs_proc
def test_the_load_is_real_and_gone_after_the_phase(tmp_path):
    """Spinners exist during a rep and their whole group is dead afterwards."""
    probe = tmp_path / "members"
    rep = (
        "import os, pathlib, sys\n"
        f"sys.path.insert(0, {str(Path(__file__).parent)!r})\n"
        "from test_load_harness import _group_members\n"
        "g = int(os.environ['SKILLC_LOAD_PGID'])\n"
        f"pathlib.Path({str(probe)!r}).write_text(str(len(_group_members(g))))\n"
    )
    # In-process, so the parent stays alive: the supervisor's parent-death
    # backstop cannot stand in for the harness's own stop.
    out = tmp_path / "phase.json"
    rc = lh.main(["phase", "--cpu", "2", "--target", "1", "--reps", "1",
                  "--warmup-seconds", "10", "--out", str(out), "--",
                  sys.executable, "-c", rep])
    record = json.loads(out.read_text())
    assert rc == 0
    assert int(probe.read_text()) >= 3, "supervisor + 2 spinners were not running"
    assert record["load_pgid"]
    assert _group_members(record["load_pgid"]) == [], "the load outlived its phase"


def _rep_marker(tmp_path: Path) -> str:
    return f"rep-462-{tmp_path.name}"


def _reps_alive(marker: str) -> list[int]:
    alive = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if marker.encode() in (entry / "cmdline").read_bytes():
                    alive.append(int(entry.name))
            except OSError:
                continue
    return alive


def _start_phase(tmp_path: Path) -> tuple[subprocess.Popen[str], int]:
    marker = _rep_marker(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(HARNESS), "phase", "--cpu", "2", "--target", "1",
         "--reps", "1", "--warmup-seconds", "10", "--out", str(tmp_path / "p.json"),
         "--", sys.executable, "-c", f"import time; time.sleep(60); {marker!r}"],
        stderr=subprocess.PIPE, text=True,
    )
    assert proc.stderr is not None
    for line in proc.stderr:
        if line.startswith("LOAD_PGID: "):
            pgid = int(line.split()[1])
            break
    else:  # pragma: no cover - the harness always announces its group
        pytest.fail("no LOAD_PGID line")
    # The harness's own argv carries the marker too; wait for a process that is not it.
    while len(_group_members(pgid)) < 3 or not set(_reps_alive(marker)) - {proc.pid}:
        time.sleep(0.05)
    return proc, pgid


@needs_proc
def test_sigterm_kills_the_load_group_and_the_running_rep(tmp_path):
    proc, pgid = _start_phase(tmp_path)
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)
    assert _wait_gone(pgid, 2.0) == []
    assert _reps_alive(_rep_marker(tmp_path)) == [], "the running rep outlived the harness"


@needs_proc
def test_a_sigkilled_harness_still_takes_its_load_down(tmp_path):
    """The supervisor sees its parent change and kills its own group."""
    proc, pgid = _start_phase(tmp_path)
    proc.kill()
    proc.wait(timeout=10)
    assert _wait_gone(pgid, 5.0) == []


def _write_phase(path: Path, start: float, end: float, verdict: str,
                 outcomes: list[str], target: float = 48, nproc: int = 24) -> str:
    path.write_text(json.dumps({
        "started_at": start, "ended_at": end, "verdict": verdict,
        "target": target, "nproc": nproc,
        "reps": [{"outcome": o, "seconds": 1.0} for o in outcomes],
    }))
    return str(path)


def test_summarize_counts_only_valid_untruncated_reps(tmp_path):
    a = _write_phase(tmp_path / "a.json", 0, 100, "VALID", ["passed", "failed", "truncated"])
    b = _write_phase(tmp_path / "b.json", 300, 400, "INVALID", ["failed", "failed"])
    out = tmp_path / "m.json"
    assert lh.main(["summarize", "--member", "m", "--test-id", "t", "--label", "pre",
                    "--out", str(out), a, b]) == 0
    m = json.loads(out.read_text())
    assert (m["counted_reps"], m["failed"], m["truncated"]) == (2, 1, 1)
    assert m["invalid_phases"] == 1
    assert m["pauses_ok"] is True


def test_summarize_claims_2x_nproc_only_when_every_valid_phase_held_it(tmp_path):
    a = _write_phase(tmp_path / "a.json", 0, 100, "VALID", ["passed"], target=48)
    b = _write_phase(tmp_path / "b.json", 300, 400, "VALID", ["passed"], target=47)
    for phases, expected in (([a], True), ([a, b], False)):
        out = tmp_path / "m.json"
        lh.main(["summarize", "--member", "m", "--test-id", "t", "--label", "pre",
                 "--out", str(out), *phases])
        assert json.loads(out.read_text())["meets_2x_nproc"] is expected


def test_a_zero_target_is_refused(tmp_path):
    rc, record, err = _phase(tmp_path, "--cpu", "0", "--target", "0", "--reps", "1")
    assert rc == 2 and record == {}
    assert "vacuous" in err


def test_summarize_flags_a_short_pause(tmp_path):
    a = _write_phase(tmp_path / "a.json", 0, 100, "VALID", ["passed"])
    b = _write_phase(tmp_path / "b.json", 100 + lh.MIN_PAUSE_SECONDS - 1, 300, "VALID",
                     ["passed"])
    out = tmp_path / "m.json"
    lh.main(["summarize", "--member", "m", "--test-id", "t", "--label", "pre",
             "--out", str(out), a, b])
    assert json.loads(out.read_text())["pauses_ok"] is False


@pytest.mark.parametrize(("p", "reps"), [(0.5, 20), (0.1, 44), (0.05, 90), (1.0, 20)])
def test_reps_for_a_one_percent_chance_of_a_lucky_zero(p, reps):
    assert lh.reps_needed(p) == reps
    if p < 1:
        assert (1 - p) ** reps < 0.01


def test_the_driver_refuses_a_pause_under_the_floor(tmp_path):
    driver = HARNESS.parent / "load-repro.sh"
    proc = subprocess.run(
        [str(driver), "m", "tests/x.py", "1", "pre", "0"],
        capture_output=True, text=True, timeout=30, check=False,
        env=dict(os.environ, LOAD_PAUSE_SECONDS=str(lh.MIN_PAUSE_SECONDS - 1)),
    )
    assert proc.returncode == 2
    assert "floor" in proc.stderr


def test_scrub_removes_the_root_the_home_and_the_user(monkeypatch, tmp_path):
    home = tmp_path / "someuser"
    root = home / "Projects" / "skillc"
    root.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)  # conftest pins Path.home
    monkeypatch.chdir(root)
    text = (f"{root}/.venv/bin/python {home}/x "
            "/tmp/pytest-of-someuser/pytest-1/t0")
    out = lh.scrub(text)
    assert out == "<root>/.venv/bin/python ~/x /tmp/pytest-of-<user>/pytest-1/t0"
    assert "someuser" not in out
